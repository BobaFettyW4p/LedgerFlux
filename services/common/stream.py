import asyncio
import json
from typing import Any, Dict, Optional, List, Callable

from .models import Tick, Snapshot
from .config import NATSConfig


class NATSStreamManager:
    def __init__(self, config: NATSConfig):
        self.config = config
        self.nats_connection = None
        self.jetstream = None
        self.subscriptions: Dict[int, Any] = {}
        self.fetch_tasks: Dict[int, Any] = {}

    async def connect(self) -> None:
        try:
            import nats
            import nats.js
        except ImportError:
            raise ImportError(
                "nats-py is required for NATS broker. Install with: pip install nats-py"
            )

        print(f"Connecting to NATS at {self.config.urls}...")
        self.nats_connection = await asyncio.wait_for(
            nats.connect(self.config.urls), timeout=10.0
        )
        print("Connected to NATS")
        self.jetstream = self.nats_connection.jetstream()
        print("JetStream context created")

        # delete existing stream; use carefully
        if self.config.delete_existing:
            try:
                await self.jetstream.delete_stream(self.config.stream_name)
                print(f"Deleted existing stream: {self.config.stream_name}")
            except Exception:
                pass

        try:
            await self.jetstream.add_stream(
                name=self.config.stream_name,
                subjects=[f"{self.config.stream_name}.*"],
                retention=nats.js.api.RetentionPolicy.LIMITS,
                max_age=self.config.max_age_seconds,
                max_msgs=1000000,
                max_bytes=1024 * 1024 * 1024,  # 1GB
            )
            print(f"Created NATS stream: {self.config.stream_name}")
        except Exception as e:
            msg = str(e).lower()
            if (
                "already in use" in msg
                or "stream name already in use" in msg
                or "exists" in msg
            ):
                print(f"Stream already exists: {self.config.stream_name}")
            else:
                print(f"Failed to create stream: {e}")
                raise

    async def disconnect(self) -> None:
        if self.nats_connection:
            await self.nats_connection.close()

    async def close(self) -> None:
        await self.disconnect()

    async def publish_tick(self, tick: Tick, shard: int) -> None:
        subject = f"{self.config.stream_name}.{shard}"
        data = tick.model_dump_json()
        await self.jetstream.publish(subject, data.encode())

    async def publish_snapshot(self, snapshot: Snapshot) -> None:
        subject = f"{self.config.stream_name}.snapshot"
        data = snapshot.model_dump_json()
        await self.jetstream.publish(subject, data.encode())

    async def subscribe_to_shard(
        self,
        shard: int,
        callback: Callable[[Tick], None],
        consumer_name: Optional[str] = None,
    ) -> None:
        subject = f"{self.config.stream_name}.{shard}"
        if consumer_name:
            print(
                f"Creating pull subscription for {subject} with consumer {consumer_name}"
            )
            sub = await self.jetstream.pull_subscribe(subject, durable=consumer_name)
        else:
            print(f"Creating ephemeral pull subscription for {subject}")
            sub = await self.jetstream.pull_subscribe(subject)
        self.subscriptions[shard] = sub

        print(f"Created pull subscription for shard {shard}")

        fetch_task = asyncio.create_task(self._fetch_messages(sub, callback, shard))
        self.fetch_tasks[shard] = fetch_task

        print(f"Started fetch task for shard {shard}")

    async def _fetch_messages(self, sub, callback: Callable[[Tick], None], shard: int):
        print(f"Starting message fetching for shard {shard}")

        while True:
            try:
                msgs = await sub.fetch(10, timeout=1.0)

                if msgs:
                    print(f"Fetched {len(msgs)} messages from shard {shard}")

                # Process each message
                for msg in msgs:
                    try:
                        data = json.loads(msg.data.decode())
                        tick = Tick.model_validate(data)
                        print(
                            f"Processing message from shard {shard}: {tick.product} - {tick.type}"
                        )
                        await callback(tick)
                        await msg.ack()
                    except Exception as e:
                        print(f"Error processing message from shard {shard}: {e}")
                        # if we don't ack here, the message will simply be redelivered

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Error fetching messages from shard {shard}: {e}")
                await asyncio.sleep(1)

    async def get_latest_messages(self, shard: int, count: int = 100) -> List[Tick]:
        subject = f"{self.config.stream_name}.{shard}"
        try:
            messages = await self.jetstream.fetch(subject, last=count)
            ticks = []
            for msg in messages:
                data = json.loads(msg.data.decode())
                tick = Tick.model_validate(data)
                ticks.append(tick)
            return ticks
        except Exception as e:
            print(f"Error fetching messages: {e}")
            return []

    async def backfill_since(
        self,
        shard: int,
        from_seq: Dict[str, int],
        products: List[str],
        max_messages: int = 5000,
        fetch_batch: int = 64,
        fetch_timeout: float = 1.0,
    ) -> List[Tick]:
        """Fetch recent ticks from JetStream for a shard and filter by per-product seq.

        Creates a short-lived durable consumer with DeliverPolicy.ALL and a filter subject
        for the shard, then pulls up to max_messages, filtering by product and sequence.
        """
        subject = f"{self.config.stream_name}.{shard}"
        try:
            import time

            # Defer imports to runtime to avoid import errors if nats is not installed
            import nats.js.api as jsapi

            durable = f"gateway-bf-{shard}-{int(time.time() * 1000)}"
            try:
                await self.jetstream.add_consumer(
                    self.config.stream_name,
                    jsapi.ConsumerConfig(
                        durable_name=durable,
                        deliver_policy=jsapi.DeliverPolicy.ALL,
                        ack_policy=jsapi.AckPolicy.EXPLICIT,
                        filter_subject=subject,
                        max_deliver=1,
                    ),
                )
            except Exception as e:
                # If already exists, continue; otherwise re-raise
                if "consumer already exists" not in str(e).lower():
                    print(f"backfill: add_consumer failed: {e}")
            sub = await self.jetstream.pull_subscribe(subject, durable=durable)
            collected: List[Tick] = []
            try:
                while len(collected) < max_messages:
                    try:
                        msgs = await sub.fetch(
                            min(fetch_batch, max_messages - len(collected)),
                            timeout=fetch_timeout,
                        )
                    except Exception:
                        break
                    if not msgs:
                        break
                    for msg in msgs:
                        try:
                            data = json.loads(msg.data.decode())
                            tick = Tick.model_validate(data)
                            if tick.product in products and tick.seq > from_seq.get(
                                tick.product, 0
                            ):
                                collected.append(tick)
                            await msg.ack()
                        except Exception as pe:
                            print(f"backfill: error processing message: {pe}")
                return collected
            finally:
                # Cleanup: delete the consumer to avoid leaks
                try:
                    await self.jetstream.delete_consumer(
                        self.config.stream_name, durable
                    )
                except Exception:
                    pass
        except Exception as e:
            print(f"Error during backfill: {e}")
            return []
