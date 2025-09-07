'''
This is the normalizer service.

It consumes raw market data from NATS JetStream, validates and normalizes the data,
and routes it to appropriate shards for downstream processing.

Required fields:
--nats-urls: NATS JetStream URLs
--input-stream: Input stream name to consume from
--output-stream: Output stream name to publish to
--num-shards: Number of output shards for message distribution
--shard-id: Shard ID this normalizer instance handles (0 to num-shards-1)
'''

import argparse
import asyncio
from typing import Dict

from ..common import Tick, Snapshot, NATSStreamManager, NATSConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market Data Normalizer")
    parser.add_argument('--nats-urls', type=str, default='nats://localhost:4222',
                       help='NATS JetStream URLs')
    parser.add_argument('--input-stream', type=str, default='market_ticks',
                       help='Input stream name')
    parser.add_argument('--output-stream', type=str, default='market.normalized',
                       help='Output stream name')
    parser.add_argument('--num-shards', type=int, default=4,
                       help='Number of output shards')
    parser.add_argument('--shard-id', type=int, required=True,
                       help='Shard ID this normalizer instance handles (0 to num-shards-1)')
    return parser.parse_args()


class Normalizer:
    """Market data normalizer with validation and sharding"""
    
    def __init__(self, args):
        self.args = args
        self.shard_id = args.shard_id
        self.num_shards = args.num_shards
        
        # NATS JetStream setup
        nats_config = NATSConfig(
            urls=args.nats_urls,
            stream_name=args.output_stream,
            retention_minutes=30
        )
        self.broker = NATSStreamManager(nats_config)
        
        # Statistics
        self.stats = {
            'messages_processed': 0,
            'messages_validated': 0,
            'messages_rejected': 0,
            'products_seen': set(),
            'errors': 0
        }
        
        # Validation state
        self.last_sequences: Dict[str, int] = {}
    
    async def start(self):
        """Start the normalizer"""
        print(f"🚀 Starting Normalizer (Shard {self.shard_id})")
        print(f"📊 Input: {self.args.input_stream}.{self.shard_id}")
        print(f"📤 Output: {self.args.output_stream}")
        print(f"🔌 NATS: {self.args.nats_urls}")
        
        # Connect to message broker
        await self.broker.connect()
        print("✅ Connected to message broker")
        
        # Start processing messages
        await self._process_messages()
    
    async def _process_messages(self):
        """Process messages from the input stream"""
        print(f"🔄 Processing messages from shard {self.shard_id}...")
        
        async def message_handler(tick: Tick):
            await self._process_tick(tick)
        
        # Subscribe to our assigned shard
        await self.broker.subscribe_to_shard(self.shard_id, message_handler)
    
    async def _process_tick(self, tick: Tick):
        """Process and validate a tick"""
        try:
            self.stats['messages_processed'] += 1
            self.stats['products_seen'].add(tick.product)
            
            # Validate the tick
            if not self._validate_tick(tick):
                self.stats['messages_rejected'] += 1
                return
            
            # Update sequence tracking
            self.last_sequences[tick.product] = tick.seq
            
            # Determine output shard (stable hash of product)
            output_shard = stable_hash(tick.product, self.num_shards)
            
            # Publish to output stream
            await self.broker.publish_tick(tick, output_shard)
            
            self.stats['messages_validated'] += 1
            
            # Print tick info
            print(f"✅ {tick.product}: ${tick.fields.last_trade.px:,.2f} "
                  f"seq: {tick.seq} → shard: {output_shard}")
            
            # Print stats every 50 messages
            if self.stats['messages_processed'] % 50 == 0:
                print(f"\n📊 Stats: processed={self.stats['messages_processed']}, "
                      f"validated={self.stats['messages_validated']}, "
                      f"rejected={self.stats['messages_rejected']}, "
                      f"products={len(self.stats['products_seen'])}\n")
                
        except Exception as e:
            print(f"❌ Error processing tick: {e}")
            self.stats['errors'] += 1
    
    def _validate_tick(self, tick: Tick) -> bool:
        """Validate a tick for data quality"""
        try:
            # Check required fields
            if not tick.product or not tick.fields:
                print(f"⚠️ Missing required fields: {tick}")
                return False
            
            # Check price validity
            if tick.fields.last_trade and tick.fields.last_trade.px <= 0:
                print(f"⚠️ Invalid price: {tick.fields.last_trade.px}")
                return False
            
            if tick.fields.best_bid and tick.fields.best_bid.px <= 0:
                print(f"⚠️ Invalid bid price: {tick.fields.best_bid.px}")
                return False
            
            if tick.fields.best_ask and tick.fields.best_ask.px <= 0:
                print(f"⚠️ Invalid ask price: {tick.fields.best_ask.px}")
                return False
            
            # Check bid-ask spread
            if (tick.fields.best_bid and tick.fields.best_ask and 
                tick.fields.best_ask.px <= tick.fields.best_bid.px):
                print(f"⚠️ Invalid spread: bid={tick.fields.best_bid.px}, ask={tick.fields.best_ask.px}")
                return False
            
            # Check sequence monotonicity (optional - can be relaxed for WebSocket)
            if tick.product in self.last_sequences:
                if tick.seq < self.last_sequences[tick.product]:
                    print(f"⚠️ Out-of-order sequence: {tick.product} {tick.seq} < {self.last_sequences[tick.product]}")
                    # Don't reject - WebSocket is best effort
            
            return True
            
        except Exception as e:
            print(f"❌ Validation error: {e}")
            return False
    
    async def stop(self):
        """Stop the normalizer"""
        print("🛑 Stopping normalizer...")
        await self.broker.disconnect()
        print("✅ Normalizer stopped")


async def main() -> None:
    args = parse_args()
    
    normalizer = Normalizer(args)
    
    try:
        await normalizer.start()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        await normalizer.stop()


if __name__ == '__main__':
    asyncio.run(main())
