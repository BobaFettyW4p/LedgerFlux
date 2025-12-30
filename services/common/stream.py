import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .config import NATSConfig
from .models import Snapshot, Tick


class NATSStreamManager:
    def __init__(self, config: NATSConfig):
        self.config = config
        self.nats_connection: Any = None
        self.jetstream: Any = None
        self.subscriptions: Dict[int, Any] = {}
        self.fetch_tasks: Dict[int, Any] = {}

    async def connect(self, timeout: float = 30.0) -> None:
        try:
            import nats
            import nats.js
            import nats.js.api as jsapi
        except ImportError as exc:
            raise ImportError(
                "nats-py is required for NATS broker. Install with: pip install nats-py"
            ) from exc

        print(f"Connecting to NATS at {self.config.urls}...")

        # Retry connection with exponential backoff
        start_time = asyncio.get_event_loop().time()
        attempt = 0
        last_error = None

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            attempt += 1
            try:
                self.nats_connection = await asyncio.wait_for(
                    nats.connect(self.config.urls), timeout=5.0
                )
                print("Connected to NATS")
                self.jetstream = self.nats_connection.jetstream()
                print("JetStream context created")
                break
            except Exception as e:
                last_error = e
                elapsed = asyncio.get_event_loop().time() - start_time
                remaining = timeout - elapsed

                if remaining <= 0:
                    break

                # Exponential backoff: 1s, 2s, 4s, 8s, 16s, capped by remaining time
                wait_time = min(2 ** (attempt - 1), remaining)
                print(f"NATS connection failed (attempt {attempt}): {e}. Retrying in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)

        if self.nats_connection is None:
            raise ConnectionError(
                f"Failed to connect to NATS at {self.config.urls} after {timeout}s: {last_error}"
            )

        # Check if the stream already exists before attempting creation. This avoids
        # failing on creation when the stream is already present or when the server
        # returns a non-JSON response that bubbles up as "invalid JSON".
        try:
            info = await self.jetstream.stream_info(self.config.stream_name)
            if info:
                print(f"Stream already exists: {self.config.stream_name}")
                return
        except Exception:
            # If stream_info fails, we'll attempt to create the stream below.
            pass

        if self.config.delete_existing:
            try:
                await self.jetstream.delete_stream(self.config.stream_name)
                print(f"Deleted existing stream: {self.config.stream_name}")
            except Exception:
                # It's fine if the stream didn't exist yet.
                pass

        # Build stream config - skip max_age for now to avoid serialization issues
        try:
            config_obj = jsapi.StreamConfig(
                name=self.config.stream_name,
                subjects=[f"{self.config.subject_prefix}.*"],
            )
            await self.jetstream.add_stream(config=config_obj)
            print(f"Created NATS stream: {self.config.stream_name}")
        except Exception as exc:
            msg = str(exc).lower()
            if (
                "already in use" in msg
                or "stream name already in use" in msg
                or "exists" in msg
            ):
                print(f"Stream already exists: {self.config.stream_name}")
            else:
                print(
                    f"Failed to create stream '{self.config.stream_name}': {exc}"
                )
                raise

    async def disconnect(self) -> None:
        if self.nats_connection:
            await self.nats_connection.close()

    async def close(self) -> None:
        await self.disconnect()

    async def publish_tick(self, tick: Tick, shard: int) -> None:
        if not self.jetstream:
            raise RuntimeError("JetStream is not connected")
        subject = f"{self.config.subject_prefix}.{shard}"
        data = tick.model_dump_json()
        await self.jetstream.publish(subject, data.encode())

    async def publish_snapshot(self, snapshot: Snapshot) -> None:
        if not self.jetstream:
            raise RuntimeError("JetStream is not connected")
        subject = f"{self.config.subject_prefix}.snapshot"
        data = snapshot.model_dump_json()
        await self.jetstream.publish(subject, data.encode())

    async def subscribe_to_shard(
        self,
        shard: int,
        callback: Callable[[Tick], Awaitable[None]],
        consumer_name: Optional[str] = None,
    ) -> None:
        if not self.jetstream:
            raise RuntimeError("JetStream is not connected")
        subject = f"{self.config.subject_prefix}.{shard}"
        if consumer_name:
            print(f"Creating pull subscription for {subject} with consumer {consumer_name}")
            sub = await self.jetstream.pull_subscribe(subject, durable=consumer_name)
        else:
            print(f"Creating ephemeral pull subscription for {subject}")
            sub = await self.jetstream.pull_subscribe(subject)
        self.subscriptions[shard] = sub

        print(f"Created pull subscription for shard {shard}")

        fetch_task = asyncio.create_task(self._fetch_messages(sub, callback, shard))
        self.fetch_tasks[shard] = fetch_task

        print(f"Started fetch task for shard {shard}")

    async def _fetch_messages(
        self,
        sub: Any,
        callback: Callable[[Tick], Awaitable[None]],
        shard: int,
    ) -> None:
        print(f"Starting message fetching for shard {shard}")

        while True:
            try:
                msgs = await sub.fetch(10, timeout=1.0)

                if msgs:
                    print(f"Fetched {len(msgs)} messages from shard {shard}")

                for msg in msgs:
                    try:
                        data = json.loads(msg.data.decode())
                        tick = Tick.model_validate(data)
                        print(
                            f"Processing message from shard {shard}: "
                            f"{tick.product} - {tick.type}"
                        )
                        await callback(tick)
                        await msg.ack()
                    except Exception as exc:
                        print(f"Error processing message from shard {shard}: {exc}")
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                print(f"Error fetching messages from shard {shard}: {exc}")
                await asyncio.sleep(1)

    async def get_latest_messages(self, shard: int, count: int = 100) -> List[Tick]:
        if not self.jetstream:
            raise RuntimeError("JetStream is not connected")
        subject = f"{self.config.subject_prefix}.{shard}"
        try:
            import nats.js.api as jsapi
        except ImportError as exc:
            raise ImportError(
                "nats-py is required for NATS broker. Install with: pip install nats-py"
            ) from exc

        try:
            sub = await self.jetstream.pull_subscribe(
                subject,
                config=jsapi.ConsumerConfig(
                    deliver_policy=jsapi.DeliverPolicy.LAST_PER_SUBJECT
                ),
            )
            msgs = await sub.fetch(count, timeout=1.0)
            ticks: List[Tick] = []
            for msg in msgs:
                data = json.loads(msg.data.decode())
                tick = Tick.model_validate(data)
                ticks.append(tick)
                await msg.ack()
            await sub.unsubscribe()
            return ticks
        except Exception as exc:
            print(f"Error fetching messages: {exc}")
            return []
