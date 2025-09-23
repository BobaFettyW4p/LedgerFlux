import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from services.common import Tick, create_snapshot, NATSStreamManager, NATSConfig
from services.common.pg_store import PostgresSnapshotStore
from services.common.config import load_nats_config


def _load_service_config() -> Dict[str, Any]:
    cfg_path = Path(__file__).with_name('config.json')
    import json
    with cfg_path.open('r', encoding='utf-8') as f:
        return json.load(f)


class Snapshotter:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        shard_id = config.get('shard_id', 0)
        if shard_id is None or str(shard_id).lower() == 'auto':
            import re, os
            pod_name = os.environ.get('HOSTNAME', '')
            match = re.search(r'-(\d+)$', pod_name)
            shard_id = int(match.group(1)) if match else 0
        self.shard_id = int(shard_id)
        self.num_shards = int(config.get('num_shards', 4))
        self.snapshot_period_ms = int(config.get('snapshot_period_ms', 60000))
        self.input_stream = str(config.get('input_stream', 'market_normalized'))
        # Postgres connection is read from PG_* env vars or config 'pg_dsn'
        self.pg_dsn = config.get('pg_dsn')
        
        nats_config = load_nats_config(stream_name=self.input_stream)
        self.broker = NATSStreamManager(nats_config)
        self.store = PostgresSnapshotStore(self.pg_dsn)
        
        self.product_states: Dict[str, Dict[str, Any]] = {}
        self.last_snapshots: Dict[str, datetime] = {}
        
        self.stats = {
            'messages_processed': 0,
            'states_updated': 0,
            'snapshots_created': 0,
            'pg_writes': 0,
            'errors': 0
        }
        
        self._store_ready = False
    
    async def start(self):
        print(f"Starting Snapshotter (Shard {self.shard_id})")
        print(f"Input: {self.input_stream}.{self.shard_id}")
        print("Snapshot store: Postgres (table: snapshots)")
        print(f"Snapshot Period: {self.snapshot_period_ms}ms")
        
        await self.broker.connect()
        print("Connected to message broker")
        await self._init_store()
        
        snapshot_task = asyncio.create_task(self._periodic_snapshots())
        
        await self._process_messages()
    
    async def _process_messages(self):
        print(f"Processing messages from shard {self.shard_id}...")
        
        async def message_handler(tick: Tick):
            await self._process_tick(tick)
        
        import os
        hostname = os.environ.get('HOSTNAME', 'local')
        consumer_name = f"snapshotter-{hostname}-{self.shard_id}"
        await self.broker.subscribe_to_shard(self.shard_id, message_handler, consumer_name=consumer_name)
    
    async def _process_tick(self, tick: Tick):
        try:
            self.stats['messages_processed'] += 1
            
            await self._update_product_state(tick)
            
            if self._should_create_snapshot(tick.product):
                await self._create_snapshot(tick.product)
            
            print(f"{tick.product}: ${tick.fields.last_trade.px:,.2f} "
                  f"seq: {tick.seq} (state updated)")
            
            # Print stats periodically
            if self.stats['messages_processed'] % 100 == 0:
                print(f"\nStats: processed={self.stats['messages_processed']}, "
                      f"states={self.stats['states_updated']}, "
                      f"snapshots={self.stats['snapshots_created']}\n")
                
        except Exception as e:
            print(f"Error processing tick: {e}")
            self.stats['errors'] += 1
    
    async def _update_product_state(self, tick: Tick):
        product = tick.product
        
        if product not in self.product_states:
            self.product_states[product] = {
                'last_trade': None,
                'best_bid': None,
                'best_ask': None,
                'last_seq': 0,
                'last_update': datetime.now()
            }
        
        #update state with latest tick data
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
        
        await self._write_to_pg(product, state)
    
    def _should_create_snapshot(self, product: str) -> bool:
        if product not in self.last_snapshots:
            return True
        
        last_snapshot = self.last_snapshots[product]
        now = datetime.now()
        
        return (now - last_snapshot).total_seconds() * 1000 >= self.snapshot_period_ms
    
    async def _create_snapshot(self, product: str):
        if product not in self.product_states:
            return
        
        state = self.product_states[product]
        
        snapshot = create_snapshot(
            product=product,
            seq=state['last_seq'],
            ts_snapshot=int(state['last_update'].timestamp() * 1_000_000_000),
            state=state
        )
        
        await self.broker.publish_snapshot(snapshot)
        
        self.last_snapshots[product] = datetime.now()
        
        self.stats['snapshots_created'] += 1
        
        print(f"📸 Created snapshot for {product} (seq: {snapshot.seq})")
    
    async def _init_store(self) -> None:
        try:
            await self.store.ensure_schema()
            self._store_ready = True
            print("Connected to Postgres and ensured schema")
        except Exception as e:
            print(f"Failed to initialize Postgres store: {e}")
            self._store_ready = False

    async def _write_to_pg(self, product: str, state: Dict[str, Any]):
        if not self._store_ready:
            return
        try:
            last_seq = int(state['last_seq'])
            ts_snapshot_ns = int(state['last_update'].timestamp() * 1_000_000_000)
            await self.store.upsert_latest(
                product=product,
                version=1,
                last_seq=last_seq,
                ts_snapshot_ns=ts_snapshot_ns,
                state=state,
            )
            self.stats['pg_writes'] += 1
        except Exception as e:
            print(f"Error writing snapshot to Postgres: {e}")
            self.stats['errors'] += 1
    
    async def _periodic_snapshots(self):
        while True:
            try:
                await asyncio.sleep(self.snapshot_period_ms / 1000)
                
                for product in self.product_states:
                    if self._should_create_snapshot(product):
                        await self._create_snapshot(product)
                        
            except Exception as e:
                print(f"Error in periodic snapshots: {e}")
                self.stats['errors'] += 1
    
    async def stop(self):
        print("Stopping snapshotter...")
        await self.broker.disconnect()
        await self.store.close()
        print("Snapshotter stopped")


async def main() -> None:
    config = _load_service_config()
    snapshotter = Snapshotter(config)
    
    try:
        await snapshotter.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        await snapshotter.stop()


if __name__ == '__main__':
    asyncio.run(main())
