import asyncio
import json
import ssl
import certifi
import websockets

async def listen_stream():
    url = 'wss://data-stream.binance.vision/ws/btcusdt@depth5@100ms'
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    
    async with websockets.connect(url, ssl=ssl_context) as ws:
        try:
            while True:
                message = await ws.recv()
                data = json.loads(message)
                print(data)
        except websockets.ConnectionClosed as e:
            print(f"Connection closed: {e}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(listen_stream())