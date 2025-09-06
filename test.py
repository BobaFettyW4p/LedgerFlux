import asyncio, json, websockets
from pydantic import BaseModel
from typing import Dict, Any
from datetime import datetime

class TradeData(BaseModel):
    px: float
    qty: float

class TickFields(BaseModel):
    last_trade: TradeData
    best_bid: TradeData
    best_ask: TradeData

class Tick(BaseModel):
    v: int = 1
    type: str = "tick"
    product: str
    seq: int
    ts_event: int
    ts_ingest: int
    fields: TickFields


def transform_coinbase_ticker(coinbase_data: dict) -> Tick:
    """Transform Coinbase ticker data to our canonical Tick format"""
    # Convert ISO timestamp to nanoseconds
    event_time = datetime.fromisoformat(coinbase_data['time'].replace('Z', '+00:00'))
    ts_event = int(event_time.timestamp() * 1_000_000_000)  # Convert to nanoseconds
    
    # Current time for ingest timestamp
    ts_ingest = int(datetime.now().timestamp() * 1_000_000_000)
    
    return Tick(
        product=coinbase_data['product_id'],
        seq=coinbase_data['sequence'],
        ts_event=ts_event,
        ts_ingest=ts_ingest,
        fields=TickFields(
            last_trade=TradeData(
                px=float(coinbase_data['price']),
                qty=float(coinbase_data['last_size'])
            ),
            best_bid=TradeData(
                px=float(coinbase_data['best_bid']),
                qty=float(coinbase_data['best_bid_size'])
            ),
            best_ask=TradeData(
                px=float(coinbase_data['best_ask']),
                qty=float(coinbase_data['best_ask_size'])
            )
        )
    )


URI = 'wss://ws-feed.exchange.coinbase.com'

channel = 'ticker'  # Using ticker instead of level2 for simpler data
product_ids = ['BTC-USD']


async def websocket_listener():
    # Simple subscribe message for public feed (no authentication needed)
    subscribe_message = json.dumps({
        'type': 'subscribe',
        'product_ids': product_ids,
        'channels': [channel]
    })

    while True:
        try:
            async with websockets.connect(URI, ping_interval=None) as websocket:
                await websocket.send(subscribe_message)
                while True:
                    response = await websocket.recv()
                    json_response = json.loads(response)
                    
                    # Handle different message types
                    if json_response.get('type') == 'subscriptions':
                        print(f"✅ Subscribed to: {json_response}")
                    elif json_response.get('type') == 'ticker':
                        # Transform to our canonical format
                        tick = transform_coinbase_ticker(json_response)
                        print(f"📈 {tick.product}: ${tick.fields.last_trade.px} (seq: {tick.seq})")
                        print(f"   Canonical format: {tick.model_dump_json()}")
                    else:
                        print(f"📨 {json_response.get('type', 'unknown')}: {json_response}")

        except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK):
            print('Connection closed, retrying..')
            await asyncio.sleep(1)


if __name__ == '__main__':
    try:
        asyncio.run(websocket_listener())
    except KeyboardInterrupt:
        print("Exiting WebSocket..")