"""
NATS JetStream client for the market data fan-out system.
"""

import asyncio
import json
from typing import Any, Dict, Optional, List, Callable
from dataclasses import dataclass

from .models import Tick, Snapshot


@dataclass
class NATSConfig:
    """Configuration for NATS JetStream"""
    urls: str = "nats://localhost:4222"
    stream_name: str = "market_ticks"
    retention_minutes: int = 30
    max_age_seconds: int = 1800  # 30 minutes
    # Deleting streams on connect is dangerous in multi-service setups; default off
    delete_existing: bool = False


class NATSStreamManager:
    """NATS JetStream implementation"""
    
    def __init__(self, config: NATSConfig):
        self.config = config
        self.nc = None
        self.js = None
        self.subscriptions: Dict[int, Any] = {}
        self.fetch_tasks: Dict[int, Any] = {}
    
    async def connect(self) -> None:
        """Connect to NATS JetStream"""
        try:
            import nats
            import nats.js
        except ImportError:
            raise ImportError("nats-py is required for NATS broker. Install with: pip install nats-py")
        
        # Connect to NATS with timeout
        print(f"🔌 Connecting to NATS at {self.config.urls}...")
        self.nc = await asyncio.wait_for(nats.connect(self.config.urls), timeout=10.0)
        print("✅ Connected to NATS")
        self.js = self.nc.jetstream()
        print("✅ JetStream context created")
        
        # Optionally delete existing stream (rarely used; dangerous)
        if self.config.delete_existing:
            try:
                await self.js.delete_stream(self.config.stream_name)
                print(f"🗑️ Deleted existing stream: {self.config.stream_name}")
            except Exception:
                # Stream might not exist; ignore
                pass

        # Ensure stream exists (idempotent)
        try:
            await self.js.add_stream(
                name=self.config.stream_name,
                subjects=[f"{self.config.stream_name}.*"],
                retention=nats.js.api.RetentionPolicy.LIMITS,
                max_age=self.config.max_age_seconds,
                max_msgs=1000000,
                max_bytes=1024*1024*1024  # 1GB
            )
            print(f"✅ Created NATS stream: {self.config.stream_name}")
        except Exception as e:
            # If stream already exists, continue; otherwise bubble up
            msg = str(e).lower()
            if "already in use" in msg or "stream name already in use" in msg or "exists" in msg:
                print(f"ℹ️ Stream already exists: {self.config.stream_name}")
            else:
                print(f"❌ Failed to create stream: {e}")
                raise
    
    async def disconnect(self) -> None:
        """Disconnect from NATS"""
        if self.nc:
            await self.nc.close()

    # Backwards-compatible alias used by tests
    async def close(self) -> None:
        await self.disconnect()
    
    async def publish_tick(self, tick: Tick, shard: int) -> None:
        """Publish a tick to a specific shard"""
        subject = f"{self.config.stream_name}.{shard}"
        data = tick.model_dump_json()
        await self.js.publish(subject, data.encode())
    
    async def publish_snapshot(self, snapshot: Snapshot) -> None:
        """Publish a snapshot"""
        subject = f"{self.config.stream_name}.snapshot"
        data = snapshot.model_dump_json()
        await self.js.publish(subject, data.encode())
    
    async def subscribe_to_shard(self, shard: int, callback: Callable[[Tick], None], consumer_name: Optional[str] = None) -> None:
        """Subscribe to messages from a specific shard.
        If consumer_name is provided, a durable with that name is used; otherwise an ephemeral consumer is created.
        """
        subject = f"{self.config.stream_name}.{shard}"
        if consumer_name:
            print(f"🔗 Creating pull subscription for {subject} with consumer {consumer_name}")
            sub = await self.js.pull_subscribe(subject, durable=consumer_name)
        else:
            print(f"🔗 Creating ephemeral pull subscription for {subject}")
            sub = await self.js.pull_subscribe(subject)
        self.subscriptions[shard] = sub
        
        print(f"✅ Created pull subscription for shard {shard}")
        
        # Start fetching messages
        fetch_task = asyncio.create_task(self._fetch_messages(sub, callback, shard))
        self.fetch_tasks[shard] = fetch_task
        
        print(f"🚀 Started fetch task for shard {shard}")
    
    async def _fetch_messages(self, sub, callback: Callable[[Tick], None], shard: int):
        """Continuously fetch messages from a pull subscription"""
        print(f"🔄 Starting message fetching for shard {shard}")
        
        while True:
            try:
                # Fetch up to 10 messages at a time
                msgs = await sub.fetch(10, timeout=1.0)
                
                if msgs:
                    print(f"📨 Fetched {len(msgs)} messages from shard {shard}")
                
                # Process each message
                for msg in msgs:
                    try:
                        data = json.loads(msg.data.decode())
                        tick = Tick(**data)
                        print(f"📤 Processing message from shard {shard}: {tick.product} - {tick.type}")
                        await callback(tick)
                        # Acknowledge the message
                        await msg.ack()
                    except Exception as e:
                        print(f"❌ Error processing message from shard {shard}: {e}")
                        # Don't ack on error so message can be redelivered
                        
            except asyncio.TimeoutError:
                # No messages available, continue
                continue
            except Exception as e:
                print(f"❌ Error fetching messages from shard {shard}: {e}")
                await asyncio.sleep(1)
    
    async def get_latest_messages(self, shard: int, count: int = 100) -> List[Tick]:
        """Get the latest messages from a shard for backfill"""
        subject = f"{self.config.stream_name}.{shard}"
        
        try:
            messages = await self.js.fetch(subject, last=count)
            ticks = []
            for msg in messages:
                data = json.loads(msg.data.decode())
                tick = Tick(**data)
                ticks.append(tick)
            return ticks
        except Exception as e:
            print(f"Error fetching messages: {e}")
            return []
