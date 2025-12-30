
import asyncio
import json
import websockets
from fastapi import FastAPI
from fastapi.responses import Response
import uvicorn
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from services.common import Tick, TickFields, TradeData, create_tick, NATSStreamManager, NATSConfig, shard_product
from services.common.config import load_nats_config
from services.common import get_metrics_response, set_build_info
from services.common.metrics import (
    ingestor_ticks_received_total,
    ingestor_ticks_published_total,
    ingestor_websocket_connected
)


def _load_service_config() -> Dict[str, Any]:
    cfg_path = Path(__file__).with_name("config.json")
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def transform_coinbase_ticker(coinbase_data: dict) -> Tick:
    event_time = datetime.fromisoformat(coinbase_data['time'].replace('Z', '+00:00'))
    ts_event = int(event_time.timestamp() * 1_000_000_000)
    
    fields = TickFields()
    
    if 'price' in coinbase_data and 'last_size' in coinbase_data:
        fields.last_trade = TradeData(
            px=float(coinbase_data['price']), 
            qty=float(coinbase_data['last_size'])
        )
    
    if 'best_bid' in coinbase_data and 'best_bid_size' in coinbase_data:
        fields.best_bid = TradeData(
            px=float(coinbase_data['best_bid']), 
            qty=float(coinbase_data['best_bid_size'])
        )
    
    if 'best_ask' in coinbase_data and 'best_ask_size' in coinbase_data:
        fields.best_ask = TradeData(
            px=float(coinbase_data['best_ask']), 
            qty=float(coinbase_data['best_ask_size'])
        )
    
    return create_tick(
        product=coinbase_data['product_id'],
        seq=coinbase_data['sequence'],
        ts_event=ts_event,
        fields=fields
    )


class CoinbaseIngester:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.products = [str(p).strip().upper() for p in config.get('products', [])]
        self.channels = [str(c).strip() for c in config.get('channels', ['ticker', 'heartbeat'])]
        self.num_shards = int(config.get('num_shards', 4))
        self.stream_name = str(config.get('stream_name', 'market_ticks'))
        self.subject_prefix = str(config.get('subject_prefix', 'market.ticks'))
        self.ws_uri = str(config.get('ws_uri', 'wss://ws-feed.exchange.coinbase.com'))
        self.health_port = int(config.get('health_port', 8080))
        
        nats_config = load_nats_config(
            stream_name=self.stream_name,
            subject_prefix=self.subject_prefix,
        )
        self.broker = NATSStreamManager(nats_config)
        self.health_app = self._build_health_app()
        self._health_server: uvicorn.Server | None = None
        self._health_task: asyncio.Task | None = None
        self._ready = False
        self._broker_ready = False
        self._ws_connected = False

        # Set build info for metrics
        set_build_info('ingestor', version='0.1.0')

        self.stats = {
            'messages_received': 0,
            'messages_published': 0,
            'errors': 0,
            'products': {product: 0 for product in self.products}
        }
    
    async def start(self) -> None:
        print(f"Starting Coinbase Ingester")
        print(f"Products: {', '.join(self.products)}")
        print(f"Channels: {', '.join(self.channels)}")
        print(f"NATS: configured via nats.config.json")
        print(f"Shards: {self.num_shards}")
        await self._start_health_server()

        await self.broker.connect(timeout=60.0)
        self._broker_ready = True
        self._ready = True
        print("Connected to message broker")
        
        await self._websocket_loop()
    
    async def _websocket_loop(self) -> None:
        subscribe_message = json.dumps({
            'type': 'subscribe',
            'product_ids': self.products,
            'channels': self.channels
        })
        
        print(f"Connecting to: {self.ws_uri}")
        
        try:
            async with websockets.connect(self.ws_uri) as websocket:
                print("WebSocket connected!")
                self._ws_connected = True
                ingestor_websocket_connected.set(1)
                
                await websocket.send(subscribe_message)
                print("Subscription sent")
                
                try:
                    async for message in websocket:
                        try:
                            await self._process_message(message)
                        except Exception as e:
                            print(f"Error processing message: {e}")
                            self.stats['errors'] += 1
                except asyncio.CancelledError:
                    print("WebSocket loop cancelled")
                    raise
                except websockets.exceptions.ConnectionClosed:
                    print("WebSocket connection closed")
                except Exception as e:
                    print(f"WebSocket error: {e}")
                    self.stats['errors'] += 1
                finally:
                    self._ws_connected = False
                    ingestor_websocket_connected.set(0)
        except asyncio.CancelledError:
            print("WebSocket connection cancelled")
            raise
        except Exception as e:
            print(f"Failed to connect to WebSocket: {e}")
            self.stats['errors'] += 1
    
    async def _process_message(self, message: str) -> None:
        try:
            data = json.loads(message)
            self.stats['messages_received'] += 1
            
            if data.get('type') == 'subscriptions':
                print(f"Subscribed: {data}")
                return
            
            if data.get('type') == 'ticker':
                await self._process_ticker(data)
            elif data.get('type') == 'heartbeat':
                # TODO: Handle heartbeat messages
                pass
            else:
                print(f"Unknown message type: {data.get('type')}")
                
        except json.JSONDecodeError:
            print(f"Invalid JSON: {message[:100]}...")
            self.stats['errors'] += 1
        except Exception as e:
            print(f"Error processing message: {e}")
            self.stats['errors'] += 1
    
    async def _process_ticker(self, data: dict) -> None:
        try:
            tick = transform_coinbase_ticker(data)

            # Track tick received
            ingestor_ticks_received_total.labels(product=tick.product).inc()

            shard = shard_product(tick.product, self.num_shards)

            try:
                await self.broker.publish_tick(tick, shard)

                self.stats['messages_published'] += 1
                self.stats['products'][tick.product] += 1

                # Track tick published
                ingestor_ticks_published_total.labels(product=tick.product, shard=str(shard)).inc()

                last_trade_price = tick.fields.last_trade.px if tick.fields.last_trade else 0.0
                bid_price = tick.fields.best_bid.px if tick.fields.best_bid else 0.0
                ask_price = tick.fields.best_ask.px if tick.fields.best_ask else 0.0

                print(f"{tick.product}: ${last_trade_price:,.2f} "
                      f"(bid: ${bid_price:,.2f}, ask: ${ask_price:,.2f}) "
                      f"shard: {shard}")
                
                #print stats on a regular cadence, but not too often
                if self.stats['messages_published'] % 100 == 0:
                    print(f"\nStats: {self.stats}\n")
                    
            except Exception as publish_error:
                print(f"Error publishing tick to NATS: {publish_error}")
                self.stats['errors'] += 1
                
        except Exception as e:
            print(f"Error processing ticker: {e}")
            self.stats['errors'] += 1
    
    async def stop(self) -> None:
        print("Stopping ingestor...")
        self._ready = False
        await self.broker.disconnect()
        await self._stop_health_server()
        print("Ingestor stopped")

    def _build_health_app(self) -> FastAPI:
        app = FastAPI(title="LedgerFlux Ingestor Health")

        @app.get("/health")
        async def health():
            return {
                "status": "ok",
                "messages_received": self.stats['messages_received'],
                "messages_published": self.stats['messages_published'],
                "errors": self.stats['errors'],
            }

        @app.get("/ready")
        async def ready():
            broker_status = "connected" if self._broker_ready else "disconnected"
            ws_status = "connected" if self._ws_connected else "disconnected"
            status = "ready" if self._ready else "not_ready"
            return {
                "status": status,
                "broker": broker_status,
                "websocket": ws_status,
            }

        @app.get("/metrics")
        async def metrics():
            content, media_type = get_metrics_response()
            return Response(content=content, media_type=media_type)

        return app

    async def _start_health_server(self) -> None:
        if self._health_task:
            return

        config = uvicorn.Config(
            self.health_app,
            host="0.0.0.0",
            port=self.health_port,
            log_level="info",
            loop="asyncio",
        )
        self._health_server = uvicorn.Server(config)
        self._health_task = asyncio.create_task(self._health_server.serve())
        print(f"Health server listening on 0.0.0.0:{self.health_port}")

    async def _stop_health_server(self) -> None:
        if not self._health_server or not self._health_task:
            return
        self._health_server.should_exit = True
        await self._health_task
        self._health_server = None
        self._health_task = None


async def main() -> None:
    config = _load_service_config()
    ingester = CoinbaseIngester(config)
    
    try:
        await ingester.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        await ingester.stop()


if __name__ == '__main__':
    asyncio.run(main())
