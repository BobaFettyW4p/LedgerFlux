import asyncio
import json
import os
import re
import traceback
from pathlib import Path
from typing import Dict, Any

from services.common import Tick, Snapshot, NATSStreamManager, NATSConfig, shard_index
from services.common.config import load_nats_config


def _load_service_config() -> Dict[str, Any]:
    cfg_path = Path(__file__).with_name('config.json')
    with cfg_path.open('r', encoding='utf-8') as f:
        return json.load(f)


class Normalizer:
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        shard_id = config.get('shard_id', 0)
        if shard_id is None or str(shard_id).lower() == 'auto':
            pod_name = os.environ.get('HOSTNAME', '')
            match = re.search(r'-(\d+)$', pod_name)
            shard_id = int(match.group(1)) if match else 0
        self.shard_id = int(shard_id)
        self.num_shards = int(config.get('num_shards', 4))
        self.input_stream = str(config.get('input_stream', 'market.ticks'))
        self.output_stream = str(config.get('output_stream', 'market.ticks'))
        self.stream_name = str(config.get('stream_name', 'market_ticks'))

        nats_config = load_nats_config(
            stream_name=self.stream_name,
            subject_prefix=self.output_stream,
        )
        self.broker = NATSStreamManager(nats_config)
        
        self.stats = {
            'messages_processed': 0,
            'messages_validated': 0,
            'messages_rejected': 0,
            'products_seen': set(),
            'errors': 0
        }
        
        self.last_sequences: Dict[str, int] = {}
    
    async def start(self):
        print(f"Starting Normalizer (Shard {self.shard_id})")
        print(f"Input: {self.input_stream}.{self.shard_id}")
        print(f"Output: {self.output_stream}")
        print(f"NATS: configured via nats.config.json")
        
        print("Attempting to connect to NATS...")
        try:
            await self.broker.connect(timeout=60.0)
            print("Connected to message broker")
        except Exception as e:
            print(f"Failed to connect to NATS: {e}")
            raise
        
        await self._process_messages()
    
    async def _process_messages(self):
        print(f"Processing messages from shard {self.shard_id}...")
        
        subject = f"{self.input_stream}.{self.shard_id}"
        consumer_name = f"normalizer-{self.shard_id}"
        
        print(f"Creating pull subscription for {subject} with consumer {consumer_name}...")
        
        try:
            psub = await asyncio.wait_for(
                self.broker.jetstream.pull_subscribe(subject, consumer_name), 
                timeout=5.0
            )
            print(f"Successfully created pull subscription for {subject}")
            
            print("Listening for messages...")
            while True:
                try:
                    msgs = await asyncio.wait_for(psub.fetch(10, timeout=1.0), timeout=2.0)
                    
                    for msg in msgs:
                        try:
                            data = json.loads(msg.data.decode())
                            tick = Tick.model_validate(data)
                            print(f"Received message: {tick.product} - {tick.type} (seq: {tick.seq})")
                            await self._process_tick(tick)
                            await msg.ack()
                        except Exception as e:
                            print(f"Error processing message: {e}")
                            
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f"Error fetching messages: {e}")
                    await asyncio.sleep(1)
                    
        except asyncio.TimeoutError:
            print(f"Failed to create subscription - timeout after 5 seconds")
            return
        except Exception as e:
            print(f"Failed to create subscription: {e}")
            traceback.print_exc()
            return
    
    async def _process_tick(self, tick: Tick):
        try:
            print(f"Processing tick: {tick.product} - {tick.type} (seq: {tick.seq})")
            self.stats['messages_processed'] += 1
            self.stats['products_seen'].add(tick.product)

            if not self._validate_tick(tick):
                self.stats['messages_rejected'] += 1
                return

            output_shard = shard_index(tick.product, self.num_shards)
            
            # Publish to output stream
            print(f"Publishing tick to output shard {output_shard}...")
            await self.broker.publish_tick(tick, output_shard)
            print(f"Successfully published tick to output shard {output_shard}")
            
            self.stats['messages_validated'] += 1
            
            # Print tick info
            print(f"{tick.product}: ${tick.fields.last_trade.px:,.2f} "
                  f"seq: {tick.seq} → shard: {output_shard}")
            
            # Print stats every 50 messages
            if self.stats['messages_processed'] % 50 == 0:
                print(f"\nStats: processed={self.stats['messages_processed']}, "
                      f"validated={self.stats['messages_validated']}, "
                      f"rejected={self.stats['messages_rejected']}, "
                      f"products={len(self.stats['products_seen'])}\n")
                
        except Exception as e:
            print(f"Error processing tick: {e}")
            self.stats['errors'] += 1
    
    def _validate_tick(self, tick: Tick) -> bool:
        try:
            if not tick.product or not tick.fields:
                print(f"Missing required fields: {tick}")
                return False

            if tick.fields.last_trade and tick.fields.last_trade.px <= 0:
                print(f"Invalid price: {tick.fields.last_trade.px}")
                return False

            if tick.fields.best_bid and tick.fields.best_bid.px <= 0:
                print(f"Invalid bid price: {tick.fields.best_bid.px}")
                return False

            if tick.fields.best_ask and tick.fields.best_ask.px <= 0:
                print(f"Invalid ask price: {tick.fields.best_ask.px}")
                return False

            if (tick.fields.best_bid and tick.fields.best_ask and
                tick.fields.best_ask.px <= tick.fields.best_bid.px):
                print(f"Invalid spread: bid={tick.fields.best_bid.px}, ask={tick.fields.best_ask.px}")
                return False

            if tick.product in self.last_sequences:
                if tick.seq < self.last_sequences[tick.product]:
                    print(f"Out-of-order sequence: {tick.product} {tick.seq} < {self.last_sequences[tick.product]}")

            # Update sequence tracking after validation passes
            self.last_sequences[tick.product] = tick.seq

            return True

        except Exception as e:
            print(f"Validation error: {e}")
            return False
    
    async def stop(self):
        print("Stopping normalizer...")
        await self.broker.disconnect()
        print("Normalizer stopped")


async def main() -> None:
    print("Normalizer main function started!")
    config = _load_service_config()
    normalizer = Normalizer(config)
    print("Normalizer instance created")
    
    try:
        print("Starting normalizer...")
        await normalizer.start()
        print("Normalizer started successfully")
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Stopping normalizer...")
        await normalizer.stop()
        print("Normalizer stopped")


if __name__ == '__main__':
    asyncio.run(main())
