import asyncio
import json
import os
import websockets
from datetime import datetime
from typing import Dict, Any, List

import uvicorn
from fastapi import FastAPI

from services.common import (
    Tick,
    TickFields,
    TradeData,
    create_tick,
    NATSStreamManager,
    shard_product,
)
from services.common.config import load_nats_config
from pathlib import Path


def transform_coinbase_ticker(coinbase_data: dict) -> Tick:
    event_time = datetime.fromisoformat(coinbase_data["time"].replace("Z", "+00:00"))
    ts_event = int(event_time.timestamp() * 1_000_000_000)

    fields = TickFields()

    if "price" in coinbase_data and "last_size" in coinbase_data:
        fields.last_trade = TradeData(
            px=float(coinbase_data["price"]), qty=float(coinbase_data["last_size"])
        )

    if "best_bid" in coinbase_data and "best_bid_size" in coinbase_data:
        fields.best_bid = TradeData(
            px=float(coinbase_data["best_bid"]),
            qty=float(coinbase_data["best_bid_size"]),
        )

    if "best_ask" in coinbase_data and "best_ask_size" in coinbase_data:
        fields.best_ask = TradeData(
            px=float(coinbase_data["best_ask"]),
            qty=float(coinbase_data["best_ask_size"]),
        )

    return create_tick(
        product=coinbase_data["product_id"],
        seq=coinbase_data["sequence"],
        ts_event=ts_event,
        fields=fields,
    )


class CoinbaseIngester:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.products = [str(p).strip().upper() for p in config.get("products", [])]
        self.channels = [
            str(c).strip() for c in config.get("channels", ["ticker", "heartbeat"])
        ]
        self.num_shards = int(config.get("num_shards", 4))
        self.stream_name = str(config.get("stream_name", "market_ticks"))
        self.ws_uri = str(config.get("ws_uri", "wss://ws-feed.exchange.coinbase.com"))

        nats_config = load_nats_config(stream_name=self.stream_name)
        self.broker = NATSStreamManager(nats_config)

        self.stats = {
            "messages_received": 0,
            "messages_published": 0,
            "errors": 0,
            "products": {product: 0 for product in self.products},
            "seq_gaps": 0,
            "resyncs": 0,
        }
        # health/readiness flags
        self._ready = False
        self._ws_connected = False

        # Per-product sequencing and resync control
        self.last_seq: Dict[str, int] = {}
        self.paused: Dict[str, bool] = {product: False for product in self.products}
        self.buffers: Dict[str, List[Tick]] = {product: [] for product in self.products}
        self._resync_tasks: Dict[str, asyncio.Task] = {}
        self.resync_max_queue_ms: int = int(
            os.environ.get(
                "RESYNC_MAX_QUEUE_MS", str(config.get("resync_max_queue_ms", 2000))
            )
        )
        self.gap_threshold: int = int(
            os.environ.get("GAP_THRESHOLD", str(config.get("gap_threshold", 500)))
        )

        # lightweight HTTP health server
        self.app = FastAPI(title="Ingestor")

        @self.app.get("/health")
        async def health():
            return {"status": "healthy"}

        @self.app.get("/ready")
        async def ready():
            broker_connected = bool(getattr(self.broker, "nats_connection", None))
            return {
                "status": "ready" if broker_connected else "not_ready",
                "broker": "connected" if broker_connected else "disconnected",
                "ws": "connected" if self._ws_connected else "disconnected",
            }

        self._http_server: uvicorn.Server | None = None
        self._http_task: asyncio.Task | None = None

    async def start(self) -> None:
        print("Starting Coinbase Ingester")
        print(f"Products: {', '.join(self.products)}")
        print(f"Channels: {', '.join(self.channels)}")
        print("NATS: configured via nats.config.json")
        print(f"Shards: {self.num_shards}")

        # start HTTP health server in background first so probes succeed early
        http_cfg = uvicorn.Config(self.app, host="0.0.0.0", port=8080, log_level="info")
        self._http_server = uvicorn.Server(http_cfg)
        self._http_task = asyncio.create_task(self._http_server.serve())

        # connect to broker; readiness will flip once connected
        try:
            await self.broker.connect()
            print("Connected to message broker")
            self._ready = True
        except Exception as e:
            print(f"Failed to connect to message broker: {e}")

        # run websocket loop with reconnects (non-blocking for probes)
        await self._websocket_loop()

    async def _websocket_loop(self) -> None:
        subscribe_message = json.dumps(
            {
                "type": "subscribe",
                "product_ids": self.products,
                "channels": self.channels,
            }
        )

        backoff = 1.0
        while True:
            print(f"Connecting to: {self.ws_uri}")
            try:
                async with websockets.connect(self.ws_uri) as websocket:
                    print("WebSocket connected!")
                    self._ws_connected = True

                    await websocket.send(subscribe_message)
                    print("Subscription sent")

                    try:
                        async for message in websocket:
                            try:
                                await self._process_message(message)
                            except Exception as e:
                                print(f"Error processing message: {e}")
                                self.stats["errors"] += 1
                    except asyncio.CancelledError:
                        print("WebSocket loop cancelled")
                        raise
                    except websockets.exceptions.ConnectionClosed:
                        print("WebSocket connection closed")
                    except Exception as e:
                        print(f"WebSocket error: {e}")
                        self.stats["errors"] += 1
            except asyncio.CancelledError:
                print("WebSocket connection cancelled")
                raise
            except Exception as e:
                print(f"Failed to connect to WebSocket: {e}")
                self.stats["errors"] += 1
            finally:
                self._ws_connected = False

            # reconnect with backoff (cap at 30s)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _process_message(self, message: str) -> None:
        try:
            data = json.loads(message)
            self.stats["messages_received"] += 1

            if data.get("type") == "subscriptions":
                print(f"Subscribed: {data}")
                return

            if data.get("type") == "ticker":
                await self._process_ticker(data)
            elif data.get("type") == "heartbeat":
                # TODO: Handle heartbeat messages
                pass
            else:
                print(f"Unknown message type: {data.get('type')}")

        except json.JSONDecodeError:
            print(f"Invalid JSON: {message[:100]}...")
            self.stats["errors"] += 1
        except Exception as e:
            print(f"Error processing message: {e}")
            self.stats["errors"] += 1

    async def _process_ticker(self, data: dict) -> None:
        try:
            tick = transform_coinbase_ticker(data)

            # Gap detection and product pause/buffer handling
            product = tick.product
            last = self.last_seq.get(product)
            if last is not None:
                if tick.seq == last + 1 and not self.paused.get(product, False):
                    # contiguous, proceed to publish
                    await self._publish_tick(tick)
                    self.last_seq[product] = tick.seq
                    return
                if tick.seq <= last:
                    # stale or duplicate; drop
                    print(
                        f"Stale/out-of-order tick dropped for {product}: seq={tick.seq} < last={last}"
                    )
                    return
                # gap detected
                gap = tick.seq - last
                self.stats["seq_gaps"] += 1
                print(
                    f"Sequence gap detected for {product}: last={last} new={tick.seq} (+{gap})"
                )
                self.paused[product] = True
                self.buffers[product].append(tick)
                # schedule a resync timer if not already running
                if product not in self._resync_tasks:
                    self._resync_tasks[product] = asyncio.create_task(
                        self._resync_timer(product)
                    )
                return
            else:
                # first tick for the product, set baseline and publish
                await self._publish_tick(tick)
                self.last_seq[product] = tick.seq
                return

            # If paused, buffer and skip publish
            if self.paused.get(product, False):
                self.buffers[product].append(tick)
                return

        except Exception as e:
            print(f"Error processing ticker: {e}")
            self.stats["errors"] += 1

    async def _publish_tick(self, tick: Tick) -> None:
        shard = shard_product(tick.product, self.num_shards)
        try:
            await self.broker.publish_tick(tick, shard)
            self.stats["messages_published"] += 1
            self.stats["products"][tick.product] += 1
            last_trade_price = (
                tick.fields.last_trade.px if tick.fields.last_trade else 0.0
            )
            bid_price = tick.fields.best_bid.px if tick.fields.best_bid else 0.0
            ask_price = tick.fields.best_ask.px if tick.fields.best_ask else 0.0
            print(
                f"{tick.product}: ${last_trade_price:,.2f} "
                f"(bid: ${bid_price:,.2f}, ask: ${ask_price:,.2f}) "
                f"shard: {shard}"
            )
            if self.stats["messages_published"] % 100 == 0:
                print(f"\nStats: {self.stats}\n")
        except Exception as publish_error:
            print(f"Error publishing tick to NATS: {publish_error}")
            self.stats["errors"] += 1

    async def _resync_timer(self, product: str) -> None:
        """Placeholder resync handler.

        Buffers incoming ticks for a short window, drops buffered messages,
        and resumes publishing from the latest observed sequence.
        """
        try:
            await asyncio.sleep(self.resync_max_queue_ms / 1000.0)
            buffer = self.buffers.get(product, [])
            if not buffer:
                # nothing buffered; just unpause
                self.paused[product] = False
                return
            # adopt the latest sequence as new baseline
            latest_seq = buffer[-1].seq
            self.last_seq[product] = latest_seq
            # drop buffered messages (cannot safely replay without snapshot)
            self.buffers[product] = []
            self.paused[product] = False
            self.stats["resyncs"] += 1
            print(
                f"Resync window elapsed for {product}; adopting seq={latest_seq} and resuming"
            )
        except Exception as e:
            print(f"Resync handler error for {product}: {e}")
        finally:
            # clear task reference
            self._resync_tasks.pop(product, None)

    async def stop(self) -> None:
        print("Stopping ingestor...")
        await self.broker.disconnect()
        self._ready = False
        if self._http_server:
            self._http_server.should_exit = True
        if self._http_task:
            try:
                await asyncio.wait_for(self._http_task, timeout=5)
            except asyncio.TimeoutError:
                pass
        print("Ingestor stopped")


async def main() -> None:
    # Load static service config mounted at services/ingestor/config.json
    def _load_service_config() -> Dict[str, Any]:
        cfg_path = Path(__file__).with_name("config.json")
        with cfg_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    config = _load_service_config()
    ingester = CoinbaseIngester(config)

    try:
        await ingester.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        await ingester.stop()


if __name__ == "__main__":
    asyncio.run(main())
