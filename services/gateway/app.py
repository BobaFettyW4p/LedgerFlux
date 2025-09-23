import asyncio
import json
import time
import os
from datetime import datetime
from typing import Dict, Set
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

from services.common import (
    SubscribeRequest, UnsubscribeRequest, PingRequest,
    SnapshotMessage, IncrMessage, RateLimitMessage, PongMessage, ErrorMessage,
    Tick, Snapshot, NATSStreamManager, NATSConfig
)
from services.common import validate_product_list
from services.common.config import load_nats_config
from services.common.pg_store import PostgresSnapshotStore


class RateLimiter:
    def __init__(self, max_rate: int, burst: int):
        self.max_rate = max_rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.time()
    
    def is_allowed(self) -> bool:
        now = time.time()
        elapsed = now - self.last_update

        self.tokens = min(self.burst, self.tokens + elapsed * self.max_rate)
        self.last_update = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
    
    def get_retry_delay(self) -> int:
        return int(1000 / self.max_rate)


class ClientConnection:
    def __init__(self, websocket: WebSocket, rate_limiter: RateLimiter):
        self.websocket = websocket
        self.rate_limiter = rate_limiter
        self.subscribed_products: Set[str] = set()
        self.last_sequences: Dict[str, int] = {}
        self.connected_at = datetime.now()
    
    async def send_message(self, message: dict):
        if not self.rate_limiter.is_allowed():
            rate_limit_msg = RateLimitMessage(
                retry_ms=self.rate_limiter.get_retry_delay()
            )
            await self.websocket.send_text(rate_limit_msg.model_dump_json())
            return False
        
        await self.websocket.send_text(json.dumps(message))
        return True
    
    async def send_error(self, code: str, message: str):
        error_msg = ErrorMessage(code=code, msg=message)
        await self.websocket.send_text(error_msg.model_dump_json())


class Gateway:
    def __init__(self, config: dict):
        self.config = config
        self.input_stream = str(config.get('input_stream', 'market.normalized'))
        self.num_shards = int(config.get('num_shards', 4))
        self.port = int(config.get('port', 8000))
        self.max_msgs_per_sec = int(config.get('max_msgs_per_sec', 100))
        self.burst = int(config.get('burst', 200))

        self.app = FastAPI(title="Market Data Gateway")
        self.clients: Dict[WebSocket, ClientConnection] = {}
        nats_config = load_nats_config(stream_name=self.input_stream)
        self.broker = NATSStreamManager(nats_config)
        self.store = PostgresSnapshotStore()
        self.stats = {
            'clients_connected': 0,
            'messages_sent': 0,
            'rate_limits': 0,
            'errors': 0
        }
        self._setup_routes()
    
    def _setup_routes(self):
        
        @self.app.get("/")
        async def root():
            return HTMLResponse("""
            <html>
                <head><title>Market Data Gateway</title></head>
                <body>
                    <h1>Market Data Gateway</h1>
                    <p>WebSocket endpoint: <code>ws://localhost:{}/ws</code></p>
                    <h2>Protocol</h2>
                    <h3>Subscribe</h3>
                    <pre>{"operation": "subscribe", "products": ["BTC-USD"], "want_snapshot": true}</pre>
                    <h3>Unsubscribe</h3>
                    <pre>{"operation": "unsubscribe", "products": ["BTC-USD"]}</pre>
                    <h3>Ping</h3>
                    <pre>{"operation": "ping", "t": 1234567890}</pre>
                </body>
            </html>
            """.format(self.port))
        
        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "clients": len(self.clients)}
        
        @self.app.get("/ready")
        async def ready():
            # Check if broker is connected
            if self.broker and self.broker.nats_connection:
                return {"status": "ready", "broker": "connected"}
            return {"status": "not_ready", "broker": "disconnected"}
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self._handle_websocket(websocket)
    
    async def start(self):
        print(f"Starting Market Data Gateway")
        print(f"WebSocket: ws://localhost:{self.port}/ws")
        print(f"Input: {self.input_stream}")
        print(f"Rate Limit: {self.max_msgs_per_sec} msg/sec")

        await self.broker.connect()
        try:
            await self.store.connect()
            print("Connected to Postgres snapshot store")
        except Exception as e:
            print(f"Warning: could not connect to Postgres snapshot store: {e}")
        print("Connected to message broker")

        await self._start_message_processing()
    
    async def _handle_websocket(self, websocket: WebSocket):
        await websocket.accept()
        
        rate_limiter = RateLimiter(self.max_msgs_per_sec, self.burst)
        client = ClientConnection(websocket, rate_limiter)
        self.clients[websocket] = client
        
        self.stats['clients_connected'] += 1
        print(f"Client connected (total: {len(self.clients)})")
        
        try:
            while True:
                data = await websocket.receive_text()
                await self._handle_client_message(client, data)
                
        except WebSocketDisconnect:
            print(f"Client disconnected")
        except Exception as e:
            print(f"WebSocket error: {e}")
            self.stats['errors'] += 1
        finally:
            if websocket in self.clients:
                del self.clients[websocket]
            self.stats['clients_connected'] -= 1
    
    async def _handle_client_message(self, client: ClientConnection, data: str):
        try:
            message = json.loads(data)
            operation = message.get('operation')
            
            if operation == 'subscribe':
                await self._handle_subscribe(client, message)
            elif operation == 'unsubscribe':
                await self._handle_unsubscribe(client, message)
            elif operation == 'ping':
                await self._handle_ping(client, message)
            else:
                await client.send_error('INVALID_OPERATION', f'Unknown operation: {operation}')
                
        except json.JSONDecodeError:
            await client.send_error('INVALID_JSON', 'Invalid JSON message')
        except Exception as e:
            print(f"Error handling client message: {e}")
            await client.send_error('INTERNAL_ERROR', str(e))
    
    async def _handle_subscribe(self, client: ClientConnection, message: dict):
        try:
            request = SubscribeRequest.model_validate(message)
            products = validate_product_list(request.products)
            
            client.subscribed_products.update(products)
            
            if request.want_snapshot:
                for product in products:
                    sent = False
                    try:
                        row = await self.store.get_latest(product)
                        if row:
                            snapshot = Snapshot(
                                product=row['product'],
                                seq=int(row['last_seq']),
                                ts_snapshot=int(row['ts_snapshot']),
                                state=row['state'],
                            )
                            snapshot_msg = SnapshotMessage(data=snapshot)
                            await client.send_message(snapshot_msg.model_dump())
                            sent = True
                    except Exception as e:
                        print(f"Error fetching snapshot from Postgres for {product}: {e}")
                    if not sent:
                        # fallback placeholder if no persisted snapshot yet
                        snapshot = Snapshot(
                            product=product,
                            seq=0,
                            ts_snapshot=int(datetime.now().timestamp() * 1_000_000_000),
                            state={'last_trade': {'px': 0, 'qty': 0}}
                        )
                        snapshot_msg = SnapshotMessage(data=snapshot)
                        await client.send_message(snapshot_msg.model_dump())
            
            print(f"Client subscribed to: {products}")
            
        except Exception as e:
            await client.send_error('SUBSCRIBE_ERROR', str(e))
    
    async def _handle_unsubscribe(self, client: ClientConnection, message: dict):
        try:
            request = UnsubscribeRequest.model_validate(message)
            products = validate_product_list(request.products)
            
            client.subscribed_products.difference_update(products)
            
            print(f"📡 Client unsubscribed from: {products}")
            
        except Exception as e:
            await client.send_error('UNSUBSCRIBE_ERROR', str(e))
    
    async def _handle_ping(self, client: ClientConnection, message: dict):
        try:
            request = PingRequest.model_validate(message)
            pong_msg = PongMessage(timestamp=request.timestamp)
            await client.send_message(pong_msg.model_dump())
            
        except Exception as e:
            await client.send_error('PING_ERROR', str(e))
    
    async def _start_message_processing(self):
        print("Starting message processing...")
        
        for shard_id in range(self.num_shards):
            async def message_handler(tick: Tick):
                await self._broadcast_tick(tick)

            hostname = os.environ.get('HOSTNAME', 'local')
            consumer_name = f"gateway-{hostname}-{shard_id}"
            await self.broker.subscribe_to_shard(shard_id, message_handler, consumer_name=consumer_name)
    
    async def _broadcast_tick(self, tick: Tick):
        if not self.clients:
            return
        
        incr_msg = IncrMessage(data=tick)
        message = incr_msg.model_dump()
        
        for client in self.clients.values():
            if tick.product in client.subscribed_products:
                success = await client.send_message(message)
                if success:
                    self.stats['messages_sent'] += 1
                else:
                    self.stats['rate_limits'] += 1
    
    async def stop(self):
        print("Stopping gateway...")
        await self.broker.disconnect()
        print("Gateway stopped")


async def main() -> None:
    config = _load_service_config()
    gateway = Gateway(config)
    try:
        await gateway.start()
        config = uvicorn.Config(
            app=gateway.app,
            host="0.0.0.0",
            port=gateway.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
        
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        await gateway.stop()


if __name__ == '__main__':
    asyncio.run(main())
