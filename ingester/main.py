import asyncio
import json
import time
import ssl
import certifi
import websockets
import struct
from socket import socket, AF_INET, SOCK_DGRAM

async def listen_stream():
    '''Listen to the Binance WebSocket stream for BTC/USDT depth data and send it via UDP
    This function connects to the Binance WebSocket stream for BTC/USDT depth data, receives the data, extracts the best bid and ask prices and quantities, packs the data into a binary format, and sends it via UDP to a specified IP and port.
    ''' 
    url = 'wss://data-stream.binance.vision/ws/btcusdt@depth5@100ms'
    ssl_context = ssl.create_default_context(cafile=certifi.where()) # Create an SSL context using certifi's CA bundle
    frmt = ">Qdddd"
    cast = socket(AF_INET, SOCK_DGRAM) # Create a UDP socket
    print("Socket created")
    async with websockets.connect(url, ssl=ssl_context) as ws:
        try: 
            print("Connected to Binance WebSocket stream for BTC/USDT")
            while True:
                message = await ws.recv()
                time_now = time.time_ns()
                data = json.loads(message)
                bid_price, bid_quantity = float(data['bids'][0][0]), float(data['bids'][0][1])  # Get the best bid or ask price
                ask_price, ask_quantity = float(data['asks'][0][0]), float(data['asks'][0][1])  # Get the best ask price
                payload = struct.pack(frmt, time_now, bid_price, bid_quantity, ask_price, ask_quantity) # Pack the data into binary format (40 bytes)
                print(f"Sending payload: {payload.hex()}") # Print the payload in hexadecimal format for debugging
                cast.sendto(payload, ("127.0.0.1", 8888)) # send the binary payload to the specified IP and port
            
        except websockets.ConnectionClosed as e:
            print(f"Connection closed: {e}")
        except Exception as e:
            print(f"Error: {e}")
            
if __name__ == "__main__":
    asyncio.run(listen_stream())