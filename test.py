import asyncio, json, websockets

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
                        print(f"📈 {json_response['product_id']}: ${json_response['price']} (seq: {json_response['sequence']})")
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