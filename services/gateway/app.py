"""
Gateway Service

FastAPI WebSocket server that provides market data to clients with backfill and rate limiting.
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Set, Optional, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn

from ..common import (
    SubscribeRequest, UnsubscribeRequest, PingRequest,
    SnapshotMessage, IncrMessage, RateLimitMessage, PongMessage, ErrorMessage,
    Tick, Snapshot, NATSStreamManager, NATSConfig, validate_product_list
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market Data Gateway")
    parser.add_argument('--nats-urls', type=str, default='nats://localhost:4222',
                       help='NATS JetStream URLs')
    parser.add_argument('--input-stream', type=str, default='market.normalized',
                       help='Input stream name')
    parser.add_argument('--num-shards', type=int, default=4,
                       help='Number of input shards')
    parser.add_argument('--port', type=int, default=8000,
                       help='WebSocket server port')
    parser.add_argument('--max-msgs-per-sec', type=int, default=100,
                       help='Maximum messages per second per client')
    parser.add_argument('--burst', type=int, default=200,
                       help='Burst capacity for rate limiting')
    return parser.parse_args()


class RateLimiter:
    """Token bucket rate limiter"""
    
    def __init__(self, max_rate: int, burst: int):
        self.max_rate = max_rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.time()
    
    def is_allowed(self) -> bool:
        """Check if a message is allowed"""
        now = time.time()
        elapsed = now - self.last_update
        
        # Add tokens based on elapsed time
        self.tokens = min(self.burst, self.tokens + elapsed * self.max_rate)
        self.last_update = now
        
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
    
    def get_retry_delay(self) -> int:
        """Get retry delay in milliseconds"""
        return int(1000 / self.max_rate)


class ClientConnection:
    """Represents a connected WebSocket client"""
    
    def __init__(self, websocket: WebSocket, rate_limiter: RateLimiter):
        self.websocket = websocket
        self.rate_limiter = rate_limiter
        self.subscribed_products: Set[str] = set()
        self.last_sequences: Dict[str, int] = {}
        self.connected_at = datetime.now()
    
    async def send_message(self, message: dict):
        """Send a message to the client"""
        if not self.rate_limiter.is_allowed():
            # Send rate limit message
            rate_limit_msg = RateLimitMessage(
                retry_ms=self.rate_limiter.get_retry_delay()
            )
            await self.websocket.send_text(rate_limit_msg.model_dump_json())
            return False
        
        await self.websocket.send_text(json.dumps(message))
        return True
    
    async def send_error(self, code: str, message: str):
        """Send an error message to the client"""
        error_msg = ErrorMessage(code=code, msg=message)
        await self.websocket.send_text(error_msg.model_dump_json())


class Gateway:
    """Market data gateway with WebSocket server"""
    
    def __init__(self, args):
        self.args = args
        self.app = FastAPI(title="Market Data Gateway")
        self.clients: Dict[WebSocket, ClientConnection] = {}
        
        # NATS JetStream setup
        nats_config = NATSConfig(
            urls=args.nats_urls,
            stream_name=args.input_stream,
            retention_minutes=30
        )
        self.broker = NATSStreamManager(nats_config)
        
        # Statistics
        self.stats = {
            'clients_connected': 0,
            'messages_sent': 0,
            'rate_limits': 0,
            'errors': 0
        }
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes"""
        
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
                    <pre>{"op": "subscribe", "products": ["BTC-USD"], "want_snapshot": true}</pre>
                    <h3>Unsubscribe</h3>
                    <pre>{"op": "unsubscribe", "products": ["BTC-USD"]}</pre>
                    <h3>Ping</h3>
                    <pre>{"op": "ping", "t": 1234567890}</pre>
                </body>
            </html>
            """.format(self.args.port))
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self._handle_websocket(websocket)
    
    async def start(self):
        """Start the gateway"""
        print(f"🚀 Starting Market Data Gateway")
        print(f"🌐 WebSocket: ws://localhost:{self.args.port}/ws")
        print(f"📊 Input: {self.args.input_stream}")
        print(f"🔌 Broker: {self.args.broker_kind}")
        print(f"⚡ Rate Limit: {self.args.max_msgs_per_sec} msg/sec")
        
        # Connect to message broker
        await self.broker.connect()
        print("✅ Connected to message broker")
        
        # Start message processing
        await self._start_message_processing()
    
    async def _handle_websocket(self, websocket: WebSocket):
        """Handle a WebSocket connection"""
        await websocket.accept()
        
        # Create client connection
        rate_limiter = RateLimiter(self.args.max_msgs_per_sec, self.args.burst)
        client = ClientConnection(websocket, rate_limiter)
        self.clients[websocket] = client
        
        self.stats['clients_connected'] += 1
        print(f"✅ Client connected (total: {len(self.clients)})")
        
        try:
            while True:
                # Receive message from client
                data = await websocket.receive_text()
                await self._handle_client_message(client, data)
                
        except WebSocketDisconnect:
            print(f"👋 Client disconnected")
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            self.stats['errors'] += 1
        finally:
            # Clean up client
            if websocket in self.clients:
                del self.clients[websocket]
            self.stats['clients_connected'] -= 1
    
    async def _handle_client_message(self, client: ClientConnection, data: str):
        """Handle a message from a client"""
        try:
            message = json.loads(data)
            op = message.get('op')
            
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
            print(f"❌ Error handling client message: {e}")
            await client.send_error('INTERNAL_ERROR', str(e))
    
    async def _handle_subscribe(self, client: ClientConnection, message: dict):
        """Handle a subscribe request"""
        try:
            request = SubscribeRequest(**message)
            products = validate_product_list(request.products)
            
            # Add to subscribed products
            client.subscribed_products.update(products)
            
            # Send initial snapshots if requested
            if request.want_snapshot:
                for product in products:
                    # TODO: Fetch snapshot from DynamoDB
                    # For now, send a placeholder
                    snapshot = Snapshot(
                        product=product,
                        seq=0,
                        ts_snapshot=int(datetime.now().timestamp() * 1_000_000_000),
                        state={'last_trade': {'px': 0, 'qty': 0}}
                    )
                    
                    snapshot_msg = SnapshotMessage(data=snapshot)
                    await client.send_message(snapshot_msg.model_dump())
            
            print(f"📡 Client subscribed to: {products}")
            
        except Exception as e:
            await client.send_error('SUBSCRIBE_ERROR', str(e))
    
    async def _handle_unsubscribe(self, client: ClientConnection, message: dict):
        """Handle an unsubscribe request"""
        try:
            request = UnsubscribeRequest(**message)
            products = validate_product_list(request.products)
            
            # Remove from subscribed products
            client.subscribed_products.difference_update(products)
            
            print(f"📡 Client unsubscribed from: {products}")
            
        except Exception as e:
            await client.send_error('UNSUBSCRIBE_ERROR', str(e))
    
    async def _handle_ping(self, client: ClientConnection, message: dict):
        """Handle a ping request"""
        try:
            request = PingRequest(**message)
            pong_msg = PongMessage(t=request.t)
            await client.send_message(pong_msg.model_dump())
            
        except Exception as e:
            await client.send_error('PING_ERROR', str(e))
    
    async def _start_message_processing(self):
        """Start processing messages from the broker"""
        print("🔄 Starting message processing...")
        
        # Subscribe to all shards
        for shard_id in range(self.args.num_shards):
            async def message_handler(tick: Tick):
                await self._broadcast_tick(tick)
            
            await self.broker.subscribe_to_shard(shard_id, message_handler)
    
    async def _broadcast_tick(self, tick: Tick):
        """Broadcast a tick to subscribed clients"""
        if not self.clients:
            return
        
        # Create increment message
        incr_msg = IncrMessage(data=tick)
        message = incr_msg.model_dump()
        
        # Send to all clients subscribed to this product
        for client in self.clients.values():
            if tick.product in client.subscribed_products:
                success = await client.send_message(message)
                if success:
                    self.stats['messages_sent'] += 1
                else:
                    self.stats['rate_limits'] += 1
    
    async def stop(self):
        """Stop the gateway"""
        print("🛑 Stopping gateway...")
        await self.broker.disconnect()
        print("✅ Gateway stopped")


async def main() -> None:
    args = parse_args()
    
    gateway = Gateway(args)
    
    try:
        # Start the gateway
        await gateway.start()
        
        # Start the web server
        config = uvicorn.Config(
            app=gateway.app,
            host="0.0.0.0",
            port=args.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
        
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        await gateway.stop()


if __name__ == '__main__':
    asyncio.run(main())
