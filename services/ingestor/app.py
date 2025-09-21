
import asyncio
import json
import websockets
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from services.common import Tick, TickFields, TradeData, create_tick, NATSStreamManager, NATSConfig, shard_product
from services.common.config import load_nats_config


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
        self.ws_uri = str(config.get('ws_uri', 'wss://ws-feed.exchange.coinbase.com'))
        
        nats_config = load_nats_config(stream_name=self.stream_name)
        self.broker = NATSStreamManager(nats_config)
        
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
        
        await self.broker.connect()
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
            
            shard = shard_product(tick.product, self.num_shards)
            
            try:
                await self.broker.publish_tick(tick, shard)
                
                self.stats['messages_published'] += 1
                self.stats['products'][tick.product] += 1
                
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
        await self.broker.disconnect()
        print("Ingestor stopped")


async def main() -> None:
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
