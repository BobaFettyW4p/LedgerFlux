"""
Coinbase WebSocket Ingester Service

Connects to Coinbase WebSocket feed, normalizes data, and publishes to message broker.
"""

import argparse
import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List

import websockets

from ..common.models import Tick, TickFields, TradeData, create_tick
from ..common.stream import Broker, BrokerConfig, create_broker
from ..common.util import get_shard_subject


def parse_args():
    parser = argparse.ArgumentParser(description="Coinbase WebSocket Ingester")
    parser.add_argument('--products', type=str, required=True, 
                       help='Comma-separated products (e.g., BTC-USD,ETH-USD)')
    parser.add_argument('--channels', type=str, default='ticker,heartbeat',
                       help='Comma-separated channels (e.g., ticker,heartbeat)')
    parser.add_argument('--ws-uri', type=str, default='wss://ws-feed.exchange.coinbase.com',
                       help='WebSocket URI')
    parser.add_argument('--broker-kind', type=str, default='nats', choices=['nats', 'redis'],
                       help='Message broker type')
    parser.add_argument('--broker-urls', type=str, 
                       help='Broker URLs (e.g., nats://localhost:4222)')
    parser.add_argument('--num-shards', type=int, default=4,
                       help='Number of shards for message distribution')
    parser.add_argument('--stream-name', type=str, default='market.ticks',
                       help='Stream name for message broker')
    return parser.parse_args()


def transform_coinbase_ticker(coinbase_data: dict) -> Tick:
    """Transform Coinbase ticker data to canonical Tick format"""
    # Convert ISO timestamp to nanoseconds
    event_time = datetime.fromisoformat(coinbase_data['time'].replace('Z', '+00:00'))
    ts_event = int(event_time.timestamp() * 1_000_000_000)
    
    # Create tick fields
    fields = TickFields(
        last_trade=TradeData(
            px=float(coinbase_data['price']), 
            qty=float(coinbase_data['last_size'])
        ),
        best_bid=TradeData(
            px=float(coinbase_data['best_bid']), 
            qty=float(coinbase_data['best_bid_size'])
        ),
        best_ask=TradeData(
            px=float(coinbase_data['best_ask']), 
            qty=float(coinbase_data['best_ask_size'])
        )
    )
    
    return create_tick(
        product=coinbase_data['product_id'],
        seq=coinbase_data['sequence'],
        ts_event=ts_event,
        fields=fields
    )


class CoinbaseIngester:
    """Coinbase WebSocket ingester with message broker integration"""
    
    def __init__(self, args):
        self.args = args
        self.products = [p.strip().upper() for p in args.products.split(',')]
        self.channels = [c.strip() for c in args.channels.split(',')]
        self.num_shards = args.num_shards
        
        # Message broker setup
        broker_config = BrokerConfig(
            kind=args.broker_kind,
            urls=args.broker_urls,
            stream_name=args.stream_name,
            retention_minutes=30
        )
        self.broker = create_broker(broker_config)
        
        # Statistics
        self.stats = {
            'messages_received': 0,
            'messages_published': 0,
            'errors': 0,
            'products': {product: 0 for product in self.products}
        }
    
    async def start(self):
        """Start the ingester"""
        print(f"🚀 Starting Coinbase Ingester")
        print(f"📡 Products: {', '.join(self.products)}")
        print(f"📺 Channels: {', '.join(self.channels)}")
        print(f"🔌 Broker: {self.args.broker_kind}")
        print(f"📊 Shards: {self.num_shards}")
        
        # Connect to message broker
        await self.broker.connect()
        print("✅ Connected to message broker")
        
        # Start WebSocket connection
        await self._websocket_loop()
    
    async def _websocket_loop(self):
        """Main WebSocket processing loop"""
        subscribe_message = json.dumps({
            'type': 'subscribe',
            'product_ids': self.products,
            'channels': self.channels
        })
        
        print(f"🔌 Connecting to: {self.args.ws_uri}")
        
        async with websockets.connect(self.args.ws_uri) as websocket:
            print("✅ WebSocket connected!")
            
            # Send subscription
            await websocket.send(subscribe_message)
            print("📤 Subscription sent")
            
            # Process messages
            async for message in websocket:
                try:
                    await self._process_message(message)
                except Exception as e:
                    print(f"❌ Error processing message: {e}")
                    self.stats['errors'] += 1
    
    async def _process_message(self, message: str):
        """Process a WebSocket message"""
        try:
            data = json.loads(message)
            self.stats['messages_received'] += 1
            
            if data.get('type') == 'subscriptions':
                print(f"✅ Subscribed: {data}")
                return
            
            if data.get('type') == 'ticker':
                await self._process_ticker(data)
            elif data.get('type') == 'heartbeat':
                # Heartbeat messages - could be used for health checks
                pass
            else:
                print(f"⚠️ Unknown message type: {data.get('type')}")
                
        except json.JSONDecodeError:
            print(f"⚠️ Invalid JSON: {message[:100]}...")
            self.stats['errors'] += 1
        except Exception as e:
            print(f"❌ Error processing message: {e}")
            self.stats['errors'] += 1
    
    async def _process_ticker(self, data: dict):
        """Process a ticker message"""
        try:
            # Transform to canonical format
            tick = transform_coinbase_ticker(data)
            
            # Determine shard
            shard = hash(tick.product) % self.num_shards
            
            # Publish to broker
            await self.broker.publish_tick(tick, shard)
            
            # Update stats
            self.stats['messages_published'] += 1
            self.stats['products'][tick.product] += 1
            
            # Print tick info
            print(f"📈 {tick.product}: ${tick.fields.last_trade.px:,.2f} "
                  f"(bid: ${tick.fields.best_bid.px:,.2f}, ask: ${tick.fields.best_ask.px:,.2f}) "
                  f"shard: {shard}")
            
            # Print stats every 100 messages
            if self.stats['messages_published'] % 100 == 0:
                print(f"\n📊 Stats: {self.stats}\n")
                
        except Exception as e:
            print(f"❌ Error processing ticker: {e}")
            self.stats['errors'] += 1
    
    async def stop(self):
        """Stop the ingester"""
        print("🛑 Stopping ingester...")
        await self.broker.disconnect()
        print("✅ Ingester stopped")


async def main():
    args = parse_args()
    
    ingester = CoinbaseIngester(args)
    
    try:
        await ingester.start()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        await ingester.stop()


if __name__ == '__main__':
    asyncio.run(main())
