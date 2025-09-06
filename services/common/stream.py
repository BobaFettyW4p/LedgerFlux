"""
Message broker abstraction for the market data fan-out system.

Supports both NATS JetStream and Redis Streams as backends.
"""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Callable
from dataclasses import dataclass

from .models import Tick, Snapshot


@dataclass
class BrokerConfig:
    """Configuration for message broker"""
    kind: str = "nats"  # "nats" or "redis"
    urls: Optional[str] = None
    stream_name: str = "market.ticks"
    retention_minutes: int = 30
    max_age_seconds: int = 1800  # 30 minutes


class Broker(ABC):
    """Abstract base class for message brokers"""
    
    @abstractmethod
    async def connect(self) -> None:
        """Connect to the broker"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the broker"""
        pass
    
    @abstractmethod
    async def publish_tick(self, tick: Tick, shard: int) -> None:
        """Publish a tick to a specific shard"""
        pass
    
    @abstractmethod
    async def publish_snapshot(self, snapshot: Snapshot) -> None:
        """Publish a snapshot"""
        pass
    
    @abstractmethod
    async def subscribe_to_shard(self, shard: int, callback: Callable[[Tick], None]) -> None:
        """Subscribe to messages from a specific shard"""
        pass


class NatsBroker(Broker):
    """NATS JetStream implementation"""
    
    def __init__(self, config: BrokerConfig):
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
        self.nc = await nats.connect(self.config.urls or "nats://localhost:4222")
        self.js = self.nc.jetstream()
        
        # Create stream if it doesn't exist
        try:
            await self.js.add_stream(
                name=self.config.stream_name,
                subjects=[f"{self.config.stream_name}.*"],
                retention=nats.js.RetentionPolicy.LIMITS,
                max_age=self.config.max_age_seconds,
                max_msgs=1000000,
                max_bytes=1024*1024*1024  # 1GB
            )
            print(f"✅ Created NATS stream: {self.config.stream_name}")
        except Exception as e:
            # Stream might already exist
            print(f"ℹ️ Stream {self.config.stream_name} already exists or error: {e}")
    
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


class RedisBroker(Broker):
    """Redis Streams implementation"""
    
    def __init__(self, config: BrokerConfig):
        self.config = config
        self.redis = None
        self.subscriptions: Dict[int, Any] = {}
    
    async def connect(self) -> None:
        """Connect to Redis"""
        try:
            import redis.asyncio as redis
        except ImportError:
            raise ImportError("redis is required for Redis broker. Install with: pip install redis")
        
        self.redis = redis.from_url(self.config.urls or "redis://localhost:6379")
        await self.redis.ping()  # Test connection
    
    async def disconnect(self) -> None:
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.close()
    
    async def publish_tick(self, tick: Tick, shard: int) -> None:
        """Publish a tick to a specific shard"""
        stream_name = f"{self.config.stream_name}:{shard}"
        data = tick.model_dump()
        await self.redis.xadd(stream_name, data)
    
    async def publish_snapshot(self, snapshot: Snapshot) -> None:
        """Publish a snapshot"""
        stream_name = f"{self.config.stream_name}:snapshot"
        data = snapshot.model_dump()
        await self.redis.xadd(stream_name, data)
    
    async def subscribe_to_shard(self, shard: int, callback: Callable[[Tick], None]) -> None:
        """Subscribe to messages from a specific shard"""
        stream_name = f"{self.config.stream_name}:{shard}"
        
        async def message_handler():
            while True:
                try:
                    messages = await self.redis.xread({stream_name: "$"}, count=1, block=1000)
                    for stream, msgs in messages:
                        for msg_id, fields in msgs:
                            tick = Tick(**fields)
                            await callback(tick)
                except Exception as e:
                    print(f"Error processing Redis message: {e}")
                    await asyncio.sleep(1)
        
        task = asyncio.create_task(message_handler())
        self.subscriptions[shard] = task


def create_broker(config: BrokerConfig) -> Broker:
    """Factory function to create a broker instance"""
    if config.kind == "nats":
        return NatsBroker(config)
    elif config.kind == "redis":
        return RedisBroker(config)
    else:
        raise ValueError(f"Unsupported broker kind: {config.kind}")
