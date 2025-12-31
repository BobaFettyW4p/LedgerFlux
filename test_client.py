#!/usr/bin/env python3
"""
Test client for the LedgerFlux Market Data Gateway

This client connects to the WebSocket gateway and validates the market data flow.
"""

import asyncio
import json
import websockets
import argparse
from datetime import datetime
from typing import List, Set


class MarketDataTestClient:
    """Test client for market data WebSocket gateway"""

    def __init__(self, gateway_url: str, products: List[str]):
        self.gateway_url = gateway_url
        self.products = products
        self.websocket = None
        self.received_messages: List[dict] = []
        self.subscribed_products: Set[str] = set()
        self.stats = {
            "messages_received": 0,
            "snapshots_received": 0,
            "increments_received": 0,
            "errors": 0,
            "products": {product: 0 for product in products},
        }

    async def connect(self):
        """Connect to the WebSocket gateway"""
        print(f"🔌 Connecting to {self.gateway_url}")
        self.websocket = await websockets.connect(self.gateway_url)
        print("✅ Connected to gateway")

    async def disconnect(self):
        """Disconnect from the WebSocket gateway"""
        if self.websocket:
            await self.websocket.close()
            print("👋 Disconnected from gateway")

    async def subscribe(self, products: List[str], want_snapshot: bool = True):
        """Subscribe to market data for products"""
        message = {
            "op": "subscribe",
            "products": products,
            "want_snapshot": want_snapshot,
        }

        await self.websocket.send(json.dumps(message))
        self.subscribed_products.update(products)
        print(f"📡 Subscribed to: {', '.join(products)}")

    async def unsubscribe(self, products: List[str]):
        """Unsubscribe from market data for products"""
        message = {"op": "unsubscribe", "products": products}

        await self.websocket.send(json.dumps(message))
        self.subscribed_products.difference_update(products)
        print(f"📡 Unsubscribed from: {', '.join(products)}")

    async def ping(self):
        """Send a ping to the gateway"""
        timestamp = int(datetime.now().timestamp())
        message = {"op": "ping", "t": timestamp}

        await self.websocket.send(json.dumps(message))
        print(f"🏓 Ping sent (t={timestamp})")
        return timestamp

    async def listen(self, duration_seconds: int = 30):
        """Listen for messages for a specified duration"""
        print(f"👂 Listening for messages for {duration_seconds} seconds...")

        start_time = datetime.now()
        end_time = start_time.timestamp() + duration_seconds

        try:
            while datetime.now().timestamp() < end_time:
                try:
                    # Wait for message with timeout
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                    await self._handle_message(message)

                except asyncio.TimeoutError:
                    # No message received, continue
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("🔌 Connection closed by server")
                    break

        except KeyboardInterrupt:
            print("\n🛑 Interrupted by user")

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            self.received_messages.append(data)
            self.stats["messages_received"] += 1

            op = data.get("op")

            if op == "snapshot":
                await self._handle_snapshot(data)
            elif op == "incr":
                await self._handle_increment(data)
            elif op == "pong":
                await self._handle_pong(data)
            elif op == "rate_limit":
                await self._handle_rate_limit(data)
            elif op == "error":
                await self._handle_error(data)
            else:
                print(f"⚠️ Unknown message type: {op}")

        except json.JSONDecodeError:
            print(f"❌ Invalid JSON: {message[:100]}...")
            self.stats["errors"] += 1
        except Exception as e:
            print(f"❌ Error handling message: {e}")
            self.stats["errors"] += 1

    async def _handle_snapshot(self, data: dict):
        """Handle snapshot message"""
        self.stats["snapshots_received"] += 1
        snapshot_data = data.get("data", {})
        product = snapshot_data.get("product", "unknown")

        if product in self.stats["products"]:
            self.stats["products"][product] += 1

        print(f"📸 Snapshot: {product} (seq: {snapshot_data.get('seq', 'N/A')})")

    async def _handle_increment(self, data: dict):
        """Handle increment message"""
        self.stats["increments_received"] += 1
        tick_data = data.get("data", {})
        product = tick_data.get("product", "unknown")

        if product in self.stats["products"]:
            self.stats["products"][product] += 1

        # Extract price information
        fields = tick_data.get("fields", {})
        last_trade = fields.get("last_trade", {})
        price = last_trade.get("px", 0) if last_trade else 0

        print(f"📈 {product}: ${price:,.2f} (seq: {tick_data.get('seq', 'N/A')})")

    async def _handle_pong(self, data: dict):
        """Handle pong response"""
        timestamp = data.get("t", "N/A")
        print(f"🏓 Pong received (t={timestamp})")

    async def _handle_rate_limit(self, data: dict):
        """Handle rate limit message"""
        retry_ms = data.get("retry_ms", 0)
        print(f"⏱️ Rate limited, retry in {retry_ms}ms")

    async def _handle_error(self, data: dict):
        """Handle error message"""
        code = data.get("code", "UNKNOWN")
        msg = data.get("msg", "No message")
        print(f"❌ Error: {code} - {msg}")
        self.stats["errors"] += 1

    def print_stats(self):
        """Print test statistics"""
        print("\n" + "=" * 50)
        print("📊 TEST STATISTICS")
        print("=" * 50)
        print(f"Messages received: {self.stats['messages_received']}")
        print(f"Snapshots: {self.stats['snapshots_received']}")
        print(f"Increments: {self.stats['increments_received']}")
        print(f"Errors: {self.stats['errors']}")
        print("\nPer-product messages:")
        for product, count in self.stats["products"].items():
            print(f"  {product}: {count}")
        print("=" * 50)


async def run_basic_test(gateway_url: str, products: List[str], duration: int = 30):
    """Run basic connectivity and data flow test"""
    print("🧪 Running Basic Connectivity Test")
    print("=" * 50)

    client = MarketDataTestClient(gateway_url, products)

    try:
        # Connect to gateway
        await client.connect()

        # Test ping/pong
        print("\n🏓 Testing ping/pong...")
        await client.ping()
        await asyncio.sleep(1)

        # Subscribe to products
        print("\n📡 Subscribing to products...")
        await client.subscribe(products, want_snapshot=True)

        # Listen for messages
        print("\n👂 Listening for market data...")
        await client.listen(duration)

        # Test unsubscribe
        print("\n📡 Unsubscribing from products...")
        await client.unsubscribe(products)

        # Final ping
        print("\n🏓 Final ping...")
        await client.ping()
        await asyncio.sleep(1)

    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        await client.disconnect()
        client.print_stats()


async def run_load_test(
    gateway_url: str, products: List[str], num_clients: int = 5, duration: int = 60
):
    """Run load test with multiple concurrent clients"""
    print(f"🚀 Running Load Test ({num_clients} clients)")
    print("=" * 50)

    clients = []

    try:
        # Create and connect clients
        for i in range(num_clients):
            client = MarketDataTestClient(f"{gateway_url}?client_id={i}", products)
            await client.connect()
            await client.subscribe(products)
            clients.append(client)
            print(f"✅ Client {i + 1} connected")

        # Run all clients concurrently
        print(f"\n👂 All clients listening for {duration} seconds...")
        tasks = [client.listen(duration) for client in clients]
        await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        print(f"❌ Load test failed: {e}")
    finally:
        # Disconnect all clients
        for i, client in enumerate(clients):
            await client.disconnect()
            print(f"👋 Client {i + 1} disconnected")

        # Print combined stats
        total_stats = {
            "messages_received": sum(c.stats["messages_received"] for c in clients),
            "snapshots_received": sum(c.stats["snapshots_received"] for c in clients),
            "increments_received": sum(c.stats["increments_received"] for c in clients),
            "errors": sum(c.stats["errors"] for c in clients),
        }

        print("\n" + "=" * 50)
        print("📊 LOAD TEST STATISTICS")
        print("=" * 50)
        for key, value in total_stats.items():
            print(f"{key}: {value}")
        print("=" * 50)


def parse_args():
    parser = argparse.ArgumentParser(description="LedgerFlux Test Client")
    parser.add_argument(
        "--gateway-url",
        type=str,
        default="ws://localhost:8000/ws",
        help="WebSocket gateway URL",
    )
    parser.add_argument(
        "--products",
        type=str,
        default="BTC-USD,ETH-USD",
        help="Comma-separated products to test",
    )
    parser.add_argument(
        "--duration", type=int, default=30, help="Test duration in seconds"
    )
    parser.add_argument(
        "--load-test", action="store_true", help="Run load test with multiple clients"
    )
    parser.add_argument(
        "--num-clients", type=int, default=5, help="Number of clients for load test"
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    products = [p.strip().upper() for p in args.products.split(",")]

    print("🧪 LedgerFlux Market Data Test Client")
    print("=" * 50)
    print(f"Gateway: {args.gateway_url}")
    print(f"Products: {', '.join(products)}")
    print(f"Duration: {args.duration}s")

    if args.load_test:
        await run_load_test(args.gateway_url, products, args.num_clients, args.duration)
    else:
        await run_basic_test(args.gateway_url, products, args.duration)


if __name__ == "__main__":
    asyncio.run(main())
