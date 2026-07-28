#!/usr/bin/env python3
"""
kalshi_live_ingester.py — Live UDP streaming for Kalshi Lead-Lag Arbitrage

1. Discovers the current daily BTC market (e.g. KXBTC).
2. Subscribes to the Kalshi V2 WebSocket `orderbook_delta`.
3. Isolates the "Yes" contract best Bid and Ask.
4. Blasts data to Java (UDP 8891) in binary format: >Qdd (24 bytes).

Usage:
    export KALSHI_KEY_ID="your_key_id"
    export KALSHI_PRIVATE_KEY="/path/to/private_key.pem"
    python kalshi_live_ingester.py
"""

import asyncio
import base64
import json
import os
import signal
import struct
import time
from datetime import datetime, timezone
import socket

import ssl
import certifi
import aiohttp
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from dotenv import load_dotenv

load_dotenv()

# Configuration

KALSHI_API_BASE = "https://demo-api.kalshi.co/trade-api/v2"
KALSHI_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"

# UDP destination for Java Receiver
JAVA_UDP_HOST = "127.0.0.1"
JAVA_UDP_PORT = 8891
UDP_PACKET_FMT = ">Qdd" # 8 byte unsigned long, 2 x 8 byte doubles = 24 bytes

ssl_context = ssl.create_default_context(cafile=certifi.where())

# Authentication

def get_auth_headers(method: str, path: str) -> dict:
    key_id = os.environ.get("KALSHI_KEY_ID")
    priv_key_env = os.environ.get("KALSHI_PRIVATE_KEY")
    
    if not key_id or not priv_key_env:
        return {}

    if os.path.exists(priv_key_env):
        with open(priv_key_env, "rb") as f:
            key_data = f.read()
    else:
        key_data = priv_key_env.encode("utf-8")
        
    try:
        private_key = serialization.load_pem_private_key(key_data, password=None)
    except Exception as e:
        return {}

    if not isinstance(private_key, rsa.RSAPrivateKey):
        return {}

    timestamp = str(int(time.time() * 1000))
    message = timestamp + method + path

    signature = private_key.sign(
        message.encode('utf-8'),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode('utf-8'),
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }

# Market Discovery

async def get_target_btc_market() -> str:
    """Finds the most relevant active BTC market (e.g. daily close)."""
    headers = get_auth_headers("GET", "/trade-api/v2/markets")
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        params = {"limit": 100, "series_ticker": "KXBTC"} 
        
        async with session.get(f"{KALSHI_API_BASE}/markets", params=params) as resp:
            if resp.status != 200:
                print(f"[ERROR] Failed to fetch KXBTC markets: {resp.status}")
                return ""
                
            data = await resp.json()
            markets = data.get("markets", [])
            
            # We sort by close_time to get the nearest expiration
            active_markets = []
            for m in markets:
                close_time_str = m.get("close_time", "")
                if m.get("status") == "active" and close_time_str:
                    try:
                        close_time_str = close_time_str.replace("Z", "+00:00")
                        dt = datetime.fromisoformat(close_time_str)
                        active_markets.append((m["ticker"], dt.timestamp()))
                    except:
                        pass
                        
            active_markets.sort(key=lambda x: x[1])
            if active_markets:
                target = active_markets[0][0]
                # STRICT 1-MARKET BTC-ONLY ENFORCEMENT
                assert "KXBTC" in target, f"CRITICAL: Selected market {target} is not a BTC market!"
                print(f"[Kalshi] Selected target market: {target} (expires nearest)")
                return target
    return ""

# Streaming

async def stream_kalshi(shutdown_event: asyncio.Event):
    target_market = await get_target_btc_market()
    if not target_market:
        print("[ERROR] No target Kalshi market found. Exiting.")
        return

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    message_id = 1
    
    while not shutdown_event.is_set():
        try:
            async with websockets.connect(KALSHI_WS_URL, ssl=ssl_context) as ws:
                print(f"[Kalshi] Connected to WebSocket. Subscribing to {target_market}...")
                
                sub_msg = {
                    "id": message_id,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": [target_market]
                    }
                }
                message_id += 1
                await ws.send(json.dumps(sub_msg))
                
                yes_bids = {}
                yes_asks = {}
                
                async for msg_str in ws:
                    if shutdown_event.is_set():
                        break
                        
                    msg = json.loads(msg_str)
                    if msg.get("type") == "orderbook_delta":
                        delta = msg.get("msg", {})
                        
                        bids = delta.get("bids", [])
                        asks = delta.get("asks", [])
                        
                        for price, qty in bids:
                            if qty == 0:
                                yes_bids.pop(price, None)
                            else:
                                yes_bids[price] = qty
                                
                        for price, qty in asks:
                            if qty == 0:
                                yes_asks.pop(price, None)
                            else:
                                yes_asks[price] = qty
                                
                        best_bid = max(yes_bids.keys()) if yes_bids else 0.0
                        best_ask = min(yes_asks.keys()) if yes_asks else 0.0
                        
                        if best_bid > 0.0 or best_ask > 0.0:
                            # Pack data: >Qdd (Timestamp, Yes Bid Price, Yes Ask Price)
                            timestamp_ns = time.time_ns()
                            bid_prob = best_bid / 100.0
                            ask_prob = best_ask / 100.0
                            
                            payload = struct.pack(UDP_PACKET_FMT, timestamp_ns, bid_prob, ask_prob)
                            udp_sock.sendto(payload, (JAVA_UDP_HOST, JAVA_UDP_PORT))
                            
        except Exception as exc:
            print(f"[Kalshi] Connection error: {exc}. Reconnecting in 3s...")
            await asyncio.sleep(3)


def main():
    shutdown = asyncio.Event()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)
        
    try:
        loop.run_until_complete(stream_kalshi(shutdown))
    except KeyboardInterrupt:
        shutdown.set()
        loop.run_until_complete(asyncio.sleep(0.5))
    finally:
        loop.close()

if __name__ == "__main__":
    main()
