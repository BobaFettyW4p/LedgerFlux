#!/usr/bin/env python3
"""
Test client for Market Data Gateway
Usage: python test_client.py [--products BTC-USD,ETH-USD] [--no-snapshot] [--quiet]
"""
import asyncio
import json
import argparse
from datetime import datetime
import websockets


class GatewayTestClient:
    def __init__(self, uri: str, products: list[str], want_snapshot: bool = True, quiet: bool = False):
        self.uri = uri
        self.products = products
        self.want_snapshot = want_snapshot
        self.quiet = quiet
        self.message_count = 0
        self.snapshot_count = 0
        self.incr_count = 0
        self.rate_limit_count = 0
        self.error_count = 0
        self.start_time = None
        self.last_stats_print = None

    async def run(self):
        """Connect to gateway and subscribe to products"""
        print(f"Connecting to {self.uri}...")

        try:
            async with websockets.connect(self.uri) as websocket:
                print(f"Connected! Subscribing to: {', '.join(self.products)}")

                # Send subscribe message
                subscribe_msg = {
                    "op": "subscribe",
                    "products": self.products,
                    "want_snapshot": self.want_snapshot
                }
                await websocket.send(json.dumps(subscribe_msg))
                print(f"Sent subscribe request (want_snapshot={self.want_snapshot})")
                print("-" * 80)

                # Receive messages
                while True:
                    message = await websocket.recv()
                    self._handle_message(message)

        except websockets.exceptions.ConnectionClosed:
            print("\nConnection closed by server")
        except KeyboardInterrupt:
            print("\nDisconnected by user")
        except Exception as e:
            print(f"\nError: {e}")
        finally:
            self._print_stats()

    def _handle_message(self, message: str):
        """Parse and display received message"""
        try:
            data = json.loads(message)
            self.message_count += 1

            # Check if message has 'op' field (envelope format)
            if "op" in data:
                msg_type = data.get("op")
                payload = data.get("data", {})
            else:
                # Fallback to direct type field
                msg_type = data.get("type", "unknown")
                payload = data

            if msg_type == "snapshot":
                self._handle_snapshot(payload)
            elif msg_type == "incr":
                self._handle_incr(payload)
            elif msg_type == "rate_limit":
                self._handle_rate_limit(payload)
            elif msg_type == "pong":
                self._handle_pong(payload)
            elif msg_type == "error":
                self._handle_error(payload)
            else:
                print(f"Unknown message type: {msg_type}")
                print(json.dumps(data, indent=2))

        except json.JSONDecodeError:
            print(f"Invalid JSON: {message}")

    def _handle_snapshot(self, data: dict):
        """Handle snapshot message"""
        self.snapshot_count += 1
        product = data.get("product", "N/A")
        seq = data.get("seq", 0)
        state = data.get("state", {})
        ts_snapshot = data.get("ts_snapshot", 0)

        # Convert nanosecond timestamp to readable format
        ts_sec = ts_snapshot / 1_000_000_000
        ts_str = datetime.fromtimestamp(ts_sec).strftime("%H:%M:%S.%f")[:-3]

        print(f"[SNAPSHOT #{self.snapshot_count}] {product}")
        print(f"  Sequence: {seq}")
        print(f"  Timestamp: {ts_str}")
        print(f"  State: {json.dumps(state, indent=4)}")
        print()

    def _handle_incr(self, data: dict):
        """Handle incremental update message"""
        self.incr_count += 1
        product = data.get("product", "N/A")
        seq = data.get("seq", 0)
        ts_event = data.get("ts_event", 0)

        # Convert nanosecond timestamp to readable format
        ts_sec = ts_event / 1_000_000_000
        ts_str = datetime.fromtimestamp(ts_sec).strftime("%H:%M:%S.%f")[:-3]

        print(f"[INCR #{self.incr_count}] {product} seq={seq} ts={ts_str}")

        # Show updates if present
        updates = data.get("updates", {})
        if updates:
            print(f"  Updates: {json.dumps(updates, indent=4)}")

    def _handle_rate_limit(self, data: dict):
        """Handle rate limit message"""
        retry_ms = data.get("retry_ms", 0)
        print(f"[RATE_LIMIT] Retry after {retry_ms}ms")

    def _handle_pong(self, data: dict):
        """Handle pong message"""
        t = data.get("t", 0)
        print(f"[PONG] t={t}")

    def _handle_error(self, data: dict):
        """Handle error message"""
        code = data.get("code", "UNKNOWN")
        msg = data.get("msg", "No message")
        print(f"[ERROR] {code}: {msg}")

    def _print_stats(self):
        """Print session statistics"""
        print("\n" + "=" * 80)
        print("Session Statistics:")
        print(f"  Total messages: {self.message_count}")
        print(f"  Snapshots: {self.snapshot_count}")
        print(f"  Incremental updates: {self.incr_count}")
        print("=" * 80)


async def main():
    parser = argparse.ArgumentParser(description="Test client for Market Data Gateway")
    parser.add_argument(
        "--uri",
        default="ws://localhost:8000/ws",
        help="WebSocket URI (default: ws://localhost:8000/ws)"
    )
    parser.add_argument(
        "--products",
        default="BTC-USD",
        help="Comma-separated list of products (default: BTC-USD)"
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="Don't request snapshot on subscribe"
    )

    args = parser.parse_args()

    # Parse products
    products = [p.strip() for p in args.products.split(",")]

    # Create and run client
    client = GatewayTestClient(
        uri=args.uri,
        products=products,
        want_snapshot=not args.no_snapshot
    )

    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
