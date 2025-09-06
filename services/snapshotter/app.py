"""
Snapshotter Service

Maintains per-product state, writes latest data to DynamoDB, and batches snapshots to S3.
"""

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from ..common.models import Tick, Snapshot, create_snapshot
from ..common.stream import Broker, BrokerConfig, create_broker


def parse_args():
    parser = argparse.ArgumentParser(description="Market Data Snapshotter")
    parser.add_argument('--broker-kind', type=str, default='nats', choices=['nats', 'redis'],
                       help='Message broker type')
    parser.add_argument('--broker-urls', type=str,
                       help='Broker URLs (e.g., nats://localhost:4222)')
    parser.add_argument('--input-stream', type=str, default='market.normalized',
                       help='Input stream name')
    parser.add_argument('--num-shards', type=int, default=4,
                       help='Number of input shards')
    parser.add_argument('--shard-id', type=int, required=True,
                       help='Shard ID this snapshotter instance handles (0 to num-shards-1)')
    parser.add_argument('--snapshot-period-ms', type=int, default=60000,
                       help='Snapshot period in milliseconds')
    parser.add_argument('--ddb-table', type=str, default='market-data-latest',
                       help='DynamoDB table name for latest data')
    parser.add_argument('--s3-bucket', type=str, default='market-data-snapshots',
                       help='S3 bucket for batched snapshots')
    return parser.parse_args()


class Snapshotter:
    """Market data snapshotter with state management and persistence"""
    
    def __init__(self, args):
        self.args = args
        self.shard_id = args.shard_id
        self.num_shards = args.num_shards
        self.snapshot_period_ms = args.snapshot_period_ms
        
        # Message broker setup
        broker_config = BrokerConfig(
            kind=args.broker_kind,
            urls=args.broker_urls,
            stream_name=args.input_stream,
            retention_minutes=30
        )
        self.broker = create_broker(broker_config)
        
        # State management
        self.product_states: Dict[str, Dict[str, Any]] = {}
        self.last_snapshots: Dict[str, datetime] = {}
        
        # Statistics
        self.stats = {
            'messages_processed': 0,
            'states_updated': 0,
            'snapshots_created': 0,
            'ddb_writes': 0,
            's3_writes': 0,
            'errors': 0
        }
        
        # Initialize AWS clients (stub for now)
        self.ddb_client = None
        self.s3_client = None
    
    async def start(self):
        """Start the snapshotter"""
        print(f"🚀 Starting Snapshotter (Shard {self.shard_id})")
        print(f"📊 Input: {self.args.input_stream}.{self.shard_id}")
        print(f"💾 DDB Table: {self.args.ddb_table}")
        print(f"🪣 S3 Bucket: {self.args.s3_bucket}")
        print(f"⏰ Snapshot Period: {self.snapshot_period_ms}ms")
        
        # Connect to message broker
        await self.broker.connect()
        print("✅ Connected to message broker")
        
        # Start periodic snapshot task
        snapshot_task = asyncio.create_task(self._periodic_snapshots())
        
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
        """Process a tick and update product state"""
        try:
            self.stats['messages_processed'] += 1
            
            # Update product state
            await self._update_product_state(tick)
            
            # Check if we should create a snapshot
            if self._should_create_snapshot(tick.product):
                await self._create_snapshot(tick.product)
            
            # Print tick info
            print(f"📊 {tick.product}: ${tick.fields.last_trade.px:,.2f} "
                  f"seq: {tick.seq} (state updated)")
            
            # Print stats every 100 messages
            if self.stats['messages_processed'] % 100 == 0:
                print(f"\n📊 Stats: processed={self.stats['messages_processed']}, "
                      f"states={self.stats['states_updated']}, "
                      f"snapshots={self.stats['snapshots_created']}\n")
                
        except Exception as e:
            print(f"❌ Error processing tick: {e}")
            self.stats['errors'] += 1
    
    async def _update_product_state(self, tick: Tick):
        """Update the state for a product"""
        product = tick.product
        
        # Initialize state if needed
        if product not in self.product_states:
            self.product_states[product] = {
                'last_trade': None,
                'best_bid': None,
                'best_ask': None,
                'last_seq': 0,
                'last_update': datetime.now()
            }
        
        # Update state with latest tick data
        state = self.product_states[product]
        
        if tick.fields.last_trade:
            state['last_trade'] = {
                'px': tick.fields.last_trade.px,
                'qty': tick.fields.last_trade.qty,
                'ts': tick.ts_event
            }
        
        if tick.fields.best_bid:
            state['best_bid'] = {
                'px': tick.fields.best_bid.px,
                'qty': tick.fields.best_bid.qty,
                'ts': tick.ts_event
            }
        
        if tick.fields.best_ask:
            state['best_ask'] = {
                'px': tick.fields.best_ask.px,
                'qty': tick.fields.best_ask.qty,
                'ts': tick.ts_event
            }
        
        state['last_seq'] = tick.seq
        state['last_update'] = datetime.now()
        
        self.stats['states_updated'] += 1
        
        # Write to DynamoDB (stub for now)
        await self._write_to_ddb(product, state)
    
    def _should_create_snapshot(self, product: str) -> bool:
        """Check if we should create a snapshot for a product"""
        if product not in self.last_snapshots:
            return True
        
        last_snapshot = self.last_snapshots[product]
        now = datetime.now()
        
        # Create snapshot if enough time has passed
        return (now - last_snapshot).total_seconds() * 1000 >= self.snapshot_period_ms
    
    async def _create_snapshot(self, product: str):
        """Create a snapshot for a product"""
        if product not in self.product_states:
            return
        
        state = self.product_states[product]
        
        # Create snapshot
        snapshot = create_snapshot(
            product=product,
            seq=state['last_seq'],
            ts_snapshot=int(state['last_update'].timestamp() * 1_000_000_000),
            state=state
        )
        
        # Publish snapshot
        await self.broker.publish_snapshot(snapshot)
        
        # Update last snapshot time
        self.last_snapshots[product] = datetime.now()
        
        self.stats['snapshots_created'] += 1
        
        print(f"📸 Created snapshot for {product} (seq: {snapshot.seq})")
    
    async def _write_to_ddb(self, product: str, state: Dict[str, Any]):
        """Write latest state to DynamoDB (stub implementation)"""
        # TODO: Implement actual DynamoDB write
        # For now, just simulate the write
        self.stats['ddb_writes'] += 1
        
        # In production, this would be:
        # await self.ddb_client.put_item(
        #     TableName=self.args.ddb_table,
        #     Item={
        #         'product': {'S': product},
        #         'state': {'S': json.dumps(state)},
        #         'timestamp': {'N': str(int(datetime.now().timestamp()))}
        #     }
        # )
    
    async def _periodic_snapshots(self):
        """Periodic task to create snapshots"""
        while True:
            try:
                await asyncio.sleep(self.snapshot_period_ms / 1000)
                
                # Create snapshots for all products
                for product in self.product_states:
                    if self._should_create_snapshot(product):
                        await self._create_snapshot(product)
                        
            except Exception as e:
                print(f"❌ Error in periodic snapshots: {e}")
                self.stats['errors'] += 1
    
    async def stop(self):
        """Stop the snapshotter"""
        print("🛑 Stopping snapshotter...")
        await self.broker.disconnect()
        print("✅ Snapshotter stopped")


async def main():
    args = parse_args()
    
    snapshotter = Snapshotter(args)
    
    try:
        await snapshotter.start()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        await snapshotter.stop()


if __name__ == '__main__':
    asyncio.run(main())
