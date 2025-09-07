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


class NATSStreamManager:
    """NATS JetStream implementation"""
    
    def __init__(self, config: NATSConfig):
        self.config = config
        self.nc = None
        self.js = None
        self.subscriptions: Dict[int, Any] = {}
    
    async def connect(self) -> None:
        """Connect to NATS JetStream"""
        try:
            import nats
            import nats.js
        except ImportError:
            raise ImportError("nats-py is required for NATS broker. Install with: pip install nats-py")
        
        # Connect to NATS
        self.nc = await nats.connect(self.config.urls)
        self.js = self.nc.jetstream()
        
        # Try to delete existing stream first to avoid conflicts
        try:
            await self.js.delete_stream(self.config.stream_name)
            print(f"🗑️ Deleted existing stream: {self.config.stream_name}")
        except Exception:
            # Stream might not exist, that's fine
            pass
        
        # Create stream
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
            print(f"❌ Failed to create stream: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from NATS"""
        if self.nc:
            await self.nc.close()
    
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
    
    async def subscribe_to_shard(self, shard: int, callback: Callable[[Tick], None]) -> None:
        """Subscribe to messages from a specific shard"""
        subject = f"{self.config.stream_name}.{shard}"
        
        async def message_handler(msg):
            try:
                data = json.loads(msg.data.decode())
                tick = Tick(**data)
                await callback(tick)
            except Exception as e:
                print(f"Error processing message: {e}")
        
        sub = await self.js.subscribe(subject, cb=message_handler)
        self.subscriptions[shard] = sub
    
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