#!/usr/bin/env python3
"""
kalshi_recorder.py —  Collector for Kalshi Crypto Prediction Markets
"""

import asyncio
import base64
import json
import os
import signal
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import ssl
import certifi
import aiohttp
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration

KALSHI_API_BASE = "https://demo-api.kalshi.co/trade-api/v2"
KALSHI_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"

# Dual-trigger flush parameters
FLUSH_BATCH_SIZE = 10_000
FLUSH_INTERVAL_SECONDS = 60

OUTPUT_FILE = f"kalshi_training_data_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.parquet"

# Parquet Schema
PARQUET_SCHEMA = pa.schema([
    ("timestamp_ns", pa.int64()),
    ("ticker", pa.string()),
    ("best_yes_bid_price", pa.float64()),
    ("best_yes_bid_qty", pa.float64()),
    ("best_yes_ask_price", pa.float64()),
    ("best_yes_ask_qty", pa.float64()),
    ("midprice", pa.float64()),
    ("microprice", pa.float64()),
    ("obi", pa.float64()),
    ("spread", pa.float64()),
    ("time_to_expiry_seconds", pa.float64()),
])

ssl_context = ssl.create_default_context(cafile=certifi.where())


def get_auth_headers(method, path) -> dict:
    """Generates Kalshi V2 RSA-PSS authentication headers."""
    key_id = os.environ.get("KALSHI_KEY_ID")
    priv_key_env = os.environ.get("KALSHI_PRIVATE_KEY") 
    
    if not key_id or not priv_key_env:
        print(" KALSHIKEYID or KALSHIPRIVATEKEY missing.")
        return {}

    if os.path.exists(priv_key_env):
        with open(priv_key_env, "rb") as f:
            key_data = f.read()
    else:
        key_data = priv_key_env.encode("utf-8")
        
    try:
        private_key = serialization.load_pem_private_key(key_data, password=None)
        if not isinstance(private_key, rsa.RSAPrivateKey):
            return {}
    except Exception as e:
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

# rest

async def discover_crypto_markets():
    """
    Fetches active Crypto markets from Kalshi REST API.
    Returns a dictionary mapping ticker -> expiration_unix_timestamp.
    """

    markets_dict = {}
    
    headers = get_auth_headers("GET", "/trade-api/v2/markets")
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        for series in ["KXBTC", "KXETH"]:
            params = {"limit": 100, "series_ticker": series} 
            
            async with session.get(f"{KALSHI_API_BASE}/markets", params=params) as resp:
                if resp.status != 200:
                    print(f"[ERROR] Failed to fetch {series} markets: {resp.status} - {await resp.text()}")
                    continue
                    
                data = await resp.json()
                markets = data.get("markets", [])
                
                for m in markets:
                    ticker = m.get("ticker", "")
                    close_time_str = m.get("close_time", "")
                    if close_time_str and ticker:
                        try:
                            close_time_str = close_time_str.replace("Z", "+00:00")
                            dt = datetime.fromisoformat(close_time_str)
                            markets_dict[ticker] = dt.timestamp()
                        except Exception as e:
                            print(f"[WARN] Could not parse close_time for {ticker}: {e}")
                            
    if not markets_dict:
        print("No active Crypto markets found.")
        return {}

    print(f"\n[Discovery] Found {len(markets_dict)} active Crypto markets.")
    
    # Sort by expiration timestamp
    sorted_markets = sorted(markets_dict.items(), key=lambda x: x[1])
    
    for idx, (ticker, exp_ts) in enumerate(sorted_markets):
        exp_dt = datetime.fromtimestamp(exp_ts, timezone.utc)
        print(f"  [{idx}] [Exp: {exp_dt.strftime('%Y-%m-%d %H:%M')} UTC] {ticker}")
        
    loop = asyncio.get_event_loop()
    while True:
        try:
            choice_str = await loop.run_in_executor(None, input, "\nSelect a market by number: ")
            choice = int(choice_str)
            if 0 <= choice < len(sorted_markets):
                selected_ticker, selected_ts = sorted_markets[choice]
                print(f"[Discovery] Locked onto: {selected_ticker}")
                return {selected_ticker: selected_ts}
        except (ValueError, EOFError):
            pass
        print("Invalid choice, try again.")

# Math & Universal Features

class OrderBookState:
    """Maintains the top of book state for a specific market."""
    def __init__(self, ticker: str, expiration_ts: float):
        self.ticker = ticker
        self.expiration_ts = expiration_ts
        self.best_yes_bid_price = 0.0
        self.best_yes_bid_qty = 0.0
        self.best_yes_ask_price = 100.0 # Bounded binary contract max
        self.best_yes_ask_qty = 0.0

    def apply_update(self, yes_bids: list, no_bids: list) -> bool:
        """
        Applies orderbook delta/snapshot. 
        Kalshi gives us YES bids and NO bids. 
        Because YES price + NO price = 100 (cents), a NO bid at price X is a YES ask at price (100 - X).
        Returns True if the top of book changed (meaning we should emit a feature vector).
        """
        changed = False
        
        # 1. Update Best YES Bid
        if yes_bids:
            # Find the highest price bid
            highest_bid = max(yes_bids, key=lambda x: x[0])
            price = highest_bid[0] / 100.0 # Convert cents to dollars
            qty = highest_bid[1]
            if price != self.best_yes_bid_price or qty != self.best_yes_bid_qty:
                self.best_yes_bid_price = price
                self.best_yes_bid_qty = qty
                changed = True
                
        # 2. Update Best YES Ask (Derived from best NO bid)
        if no_bids:
            # Find the highest price NO bid (which translates to the lowest price YES ask)
            highest_no_bid = max(no_bids, key=lambda x: x[0])
            price = (100 - highest_no_bid[0]) / 100.0 # Convert cents to dollars
            qty = highest_no_bid[1]
            if price != self.best_yes_ask_price or qty != self.best_yes_ask_qty:
                self.best_yes_ask_price = price
                self.best_yes_ask_qty = qty
                changed = True
                
        return changed

    def compute_features(self) -> Optional[dict]:
        """Computes the domain-agnostic physical features."""
        bid_px = self.best_yes_bid_price
        bid_qty = self.best_yes_bid_qty
        ask_px = self.best_yes_ask_price
        ask_qty = self.best_yes_ask_qty
        
        # We need both sides of the book to calculate reliable metrics
        if bid_qty == 0 or ask_qty == 0:
            return None

        total_qty = bid_qty + ask_qty
        
        midprice = (bid_px + ask_px) / 2.0
        microprice = ((bid_qty * ask_px) + (ask_qty * bid_px)) / total_qty
        obi = (bid_qty - ask_qty) / total_qty  # Bounded [-1.0, 1.0]
        spread = ask_px - bid_px
        
        current_ts = time.time()
        time_to_expiry = self.expiration_ts - current_ts
        
        return {
            "timestamp_ns": time.time_ns(),
            "ticker": self.ticker,
            "best_yes_bid_price": bid_px,
            "best_yes_bid_qty": bid_qty,
            "best_yes_ask_price": ask_px,
            "best_yes_ask_qty": ask_qty,
            "midprice": midprice,
            "microprice": microprice,
            "obi": obi,
            "spread": spread,
            "time_to_expiry_seconds": time_to_expiry,
        }

# Parquet Writer & Memory Management

class MemorySafeParquetWriter:
    """Handles appending batches to Parquet and enforcing the dual-trigger flush."""
    
    def __init__(self, filename: str):
        self.filename = filename
        self.batch: List[dict] = []
        self.last_flush_time = time.monotonic()
        self.writer = None
        self.lock = asyncio.Lock()

    async def add_row(self, row: dict):
        """Thread-safe append. Flushes if batch size exceeds limit."""
        async with self.lock:
            self.batch.append(row)
            
        if len(self.batch) >= FLUSH_BATCH_SIZE:
            await self.flush()

    async def background_timer_flush(self):
        """Background task enforcing the 60-second time limit trigger."""
        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            if (now - self.last_flush_time) >= FLUSH_INTERVAL_SECONDS:
                async with self.lock:
                    if len(self.batch) > 0:
                        await self.flush(timer_triggered=True)

    async def flush(self, timer_triggered=False):
        """Writes the batch to disk and explicitly clears memory."""
        if not self.batch:
            return
            
        trigger = "Time" if timer_triggered else "BatchSize"
        batch_copy = self.batch.copy() # Shallow copy for the flush
        self.batch.clear() # EXPLICIT LEAK PREVENTION
        self.last_flush_time = time.monotonic()
        
        # Perform disk I/O outside of the lock (though pa write is blocking, it's fast)
        try:
            df = pd.DataFrame(batch_copy)
            table = pa.Table.from_pandas(df, schema=PARQUET_SCHEMA)
            
            if self.writer is None:
                self.writer = pq.ParquetWriter(self.filename, PARQUET_SCHEMA, compression="snappy")
                
            self.writer.write_table(table)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Flushed {len(batch_copy)} rows ({trigger} Trigger). Total rows appended to {self.filename}.")
        except Exception as e:
            print(f"[ERROR] Parquet flush failed: {e}")

    def close(self):
        if self.writer:
            self.writer.close()

# Main WebSocket Streamer

async def stream_kalshi_markets(markets_dict: Dict[str, float], writer: MemorySafeParquetWriter):
    """Connects to Kalshi WebSocket, subscribes to orderbooks, and computes features."""
    
    if not markets_dict:
        print("[WARN] No markets to stream.")
        return
        
    tickers = list(markets_dict.keys())
    
    # Initialize state trackers
    states = {ticker: OrderBookState(ticker, exp_ts) for ticker, exp_ts in markets_dict.items()}
    
    headers = get_auth_headers("GET", "/trade-api/ws/v2")
    
    reconnect_delay = 1.0
    
    while True:
        try:
            print(f"[WS] Connecting to {KALSHI_WS_URL} ...")
            # aiohttp handles headers cleanly for websockets too, or we can use websockets lib
            async with websockets.connect(KALSHI_WS_URL, additional_headers=headers, ping_interval=20, ping_timeout=10, ssl=ssl_context) as ws:
                print(f"[WS] Connected! Subscribing to {len(tickers)} markets...")
                
                sub_msg = {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": tickers
                    }
                }
                await ws.send(json.dumps(sub_msg))
                reconnect_delay = 1.0 # Reset backoff on successful connect
                
                async for raw_msg in ws:
                    msg = json.loads(raw_msg)
                    
                    if msg.get("type") in ["orderbook_snapshot", "orderbook_delta"]:
                        payload = msg.get("msg", {})
                        ticker = payload.get("market_ticker")
                        
                        if ticker in states:
                            yes_bids = payload.get("yes", [])
                            no_bids = payload.get("no", [])
                            
                            # Apply updates and check if top of book changed
                            changed = states[ticker].apply_update(yes_bids, no_bids)
                            
                            if changed:
                                feature_row = states[ticker].compute_features()
                                if feature_row:
                                    await writer.add_row(feature_row)
                                    
        except (websockets.ConnectionClosed, Exception) as e:
            print(f"[WS ERROR] Connection lost: {e}. Reconnecting in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60.0) # Exponential backoff max 60s

# Entry Point

async def main():
    print("=" * 60)
    print(" Kalshi Recorder — Prediction Market Data Harvester")
    print("=" * 60)
    
    writer = MemorySafeParquetWriter(OUTPUT_FILE)
    
    # Start background time-based flush trigger
    timer_task = asyncio.create_task(writer.background_timer_flush())
    
    # Discover markets
    markets_dict = await discover_crypto_markets()
    
    # Graceful shutdown handler
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    
    def signal_handler():
        print("\n[INFO] Shutdown signal received. Flushing remaining data...")
        shutdown_event.set()
        
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Stream task
    stream_task = asyncio.create_task(stream_kalshi_markets(markets_dict, writer))
    
    # Wait for shutdown signal
    await shutdown_event.wait()
    
    # Cleanup
    stream_task.cancel()
    timer_task.cancel()
    await writer.flush(timer_triggered=True)
    writer.close()
    print("[INFO] Shutdown complete. Data saved.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
