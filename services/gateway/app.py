import asyncio
import json
import time
import os
from datetime import datetime
from typing import Dict, Set
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
import uvicorn

from services.common import (
    SubscribeRequest, UnsubscribeRequest, PingRequest,
    SnapshotMessage, IncrMessage, RateLimitMessage, PongMessage, ErrorMessage,
    Tick, Snapshot, NATSStreamManager, NATSConfig,
    get_metrics_response, set_build_info
)
from services.common import validate_product_list
from services.common.config import load_nats_config
from services.common.pg_store import PostgresSnapshotStore
from services.common.metrics import (
    gateway_clients_connected,
    gateway_clients_total,
    gateway_messages_sent_total,
    gateway_rate_limits_total,
    gateway_subscriptions_total,
    gateway_active_subscriptions
)


def _load_service_config() -> dict:
    cfg_path = Path(__file__).with_name("config.json")
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


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
        # Use small epsilon to handle floating point precision issues
        # Epsilon of 0.005 handles millisecond-level time precision
        if self.tokens >= 1.0 - 0.005:
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
        self.input_stream = str(config.get('input_stream', 'market.ticks'))
        self.stream_name = str(config.get('stream_name', 'market_ticks'))
        self.num_shards = int(config.get('num_shards', 4))
        self.port = int(config.get('port', 8000))
        self.max_msgs_per_sec = int(config.get('max_msgs_per_sec', 100))
        self.burst = int(config.get('burst', 200))

        self.app = FastAPI(title="Market Data Gateway")
        self.clients: Dict[WebSocket, ClientConnection] = {}
        nats_config = load_nats_config(
            stream_name=self.stream_name,
            subject_prefix=self.input_stream,
        )
        self.broker = NATSStreamManager(nats_config)
        self.store = PostgresSnapshotStore()
        self.stats = {
            'clients_connected': 0,
            'messages_sent': 0,
            'rate_limits': 0,
            'errors': 0
        }

        # Set build info for metrics
        set_build_info('gateway', version='0.1.0')

        self._setup_routes()
    
    def _setup_routes(self):
        port = self.port  # Capture port in closure

        @self.app.get("/")
        async def root():
            return HTMLResponse(f"""
            <html>
                <head><title>Market Data Gateway</title></head>
                <body>
                    <h1>Market Data Gateway</h1>
                    <p>WebSocket endpoint: <code>ws://localhost:{port}/ws</code></p>
                    <h2>Protocol</h2>
                    <h3>Subscribe</h3>
                    <pre>{{"op": "subscribe", "products": ["BTC-USD"], "want_snapshot": true}}</pre>
                    <h3>Unsubscribe</h3>
                    <pre>{{"op": "unsubscribe", "products": ["BTC-USD"]}}</pre>
                    <h3>Ping</h3>
                    <pre>{{"op": "ping", "t": 1234567890}}</pre>
                </body>
            </html>
            """)
        
        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "clients": len(self.clients)}
        
        @self.app.get("/ready")
        async def ready():
            # Check if broker is connected
            if self.broker and self.broker.nats_connection:
                return {"status": "ready", "broker": "connected"}
            return {"status": "not_ready", "broker": "disconnected"}

        @self.app.get("/metrics")
        async def metrics():
            content, media_type = get_metrics_response()
            return Response(content=content, media_type=media_type)

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self._handle_websocket(websocket)
    
    async def start(self):
        print(f"Starting Market Data Gateway")
        print(f"WebSocket: ws://localhost:{self.port}/ws")
        print(f"Input: {self.input_stream}")
        print(f"Rate Limit: {self.max_msgs_per_sec} msg/sec")

        await self.broker.connect(timeout=60.0)
        try:
            await self.store.connect()
            await self.store.ensure_schema()
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
        gateway_clients_connected.inc()
        gateway_clients_total.labels(status='connected').inc()
        print(f"Client connected (total: {len(self.clients)})")

        try:
            while True:
                data = await websocket.receive_text()
                await self._handle_client_message(client, data)

        except WebSocketDisconnect:
            print(f"Client disconnected")
            gateway_clients_total.labels(status='disconnected').inc()
        except Exception as e:
            print(f"WebSocket error: {e}")
            self.stats['errors'] += 1
        finally:
            if websocket in self.clients:
                # Unsubscribe from all products
                for product in list(client.subscribed_products):
                    gateway_active_subscriptions.labels(product=product).dec()
                del self.clients[websocket]
            self.stats['clients_connected'] -= 1
            gateway_clients_connected.dec()
    
    async def _handle_client_message(self, client: ClientConnection, data: str):
        try:
            message = json.loads(data)
            op = message.get('op') or message.get('operation')
            
            if op == 'subscribe':
                await self._handle_subscribe(client, message)
            elif op == 'unsubscribe':
                await self._handle_unsubscribe(client, message)
            elif op == 'ping':
                await self._handle_ping(client, message)
            else:
                await client.send_error('INVALID_OPERATION', f'Unknown operation: {op}')
                
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

            # Track subscriptions in metrics
            for product in products:
                gateway_subscriptions_total.labels(product=product, operation='subscribe').inc()
                gateway_active_subscriptions.labels(product=product).inc()

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
                            gateway_messages_sent_total.labels(product=product, message_type='snapshot').inc()
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
                        gateway_messages_sent_total.labels(product=product, message_type='snapshot').inc()

            print(f"Client subscribed to: {products}")

        except Exception as e:
            await client.send_error('SUBSCRIBE_ERROR', str(e))
    
    async def _handle_unsubscribe(self, client: ClientConnection, message: dict):
        try:
            request = UnsubscribeRequest.model_validate(message)
            products = validate_product_list(request.products)

            client.subscribed_products.difference_update(products)

            # Track unsubscriptions in metrics
            for product in products:
                gateway_subscriptions_total.labels(product=product, operation='unsubscribe').inc()
                gateway_active_subscriptions.labels(product=product).dec()

            print(f"Client unsubscribed from: {products}")

        except Exception as e:
            await client.send_error('UNSUBSCRIBE_ERROR', str(e))
    
    async def _handle_ping(self, client: ClientConnection, message: dict):
        try:
            request = PingRequest.model_validate(message)
            pong_msg = PongMessage(t=request.t)
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
                    gateway_messages_sent_total.labels(product=tick.product, message_type='incr').inc()
                else:
                    self.stats['rate_limits'] += 1
                    gateway_rate_limits_total.inc()
    
    async def stop(self):
        print("Stopping gateway...")
        await self.broker.disconnect()
        await self.store.close()
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
