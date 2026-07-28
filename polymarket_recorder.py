#!/usr/bin/env python3
"""
polymarket_recorder.py — ML Training Data Collector for Polymarket Crypto Prediction Markets
Multi-Horizon Concurrent Auto-Chaining Edition (Fully Autonomous + L2 Depth)
"""
import asyncio
import json
import os
import signal
import time
from datetime import datetime, timezone

import ssl
import certifi
import aiohttp
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import websockets
from dotenv import load_dotenv

load_dotenv()

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com/events?tag_slug=crypto&active=true&closed=false&limit=100"
POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

FLUSH_BATCH_SIZE = 10_000
FLUSH_INTERVAL_SECONDS = 60
DATA_DIR = "polymarket_data"

# UPGRADED L2 SCHEMA: Captures Top 3 Levels and Total Market Liquidity
PARQUET_SCHEMA = pa.schema([
    ("timestamp_ns", pa.int64()),
    ("ticker", pa.string()),
    ("best_yes_bid_price", pa.float64()),
    ("best_yes_bid_qty", pa.float64()),
    ("bid_px_2", pa.float64()),
    ("bid_qty_2", pa.float64()),
    ("bid_px_3", pa.float64()),
    ("bid_qty_3", pa.float64()),
    ("best_yes_ask_price", pa.float64()),
    ("best_yes_ask_qty", pa.float64()),
    ("ask_px_2", pa.float64()),
    ("ask_qty_2", pa.float64()),
    ("ask_px_3", pa.float64()),
    ("ask_qty_3", pa.float64()),
    ("total_bid_vol", pa.float64()),
    ("total_ask_vol", pa.float64()),
    ("midprice", pa.float64()),
    ("microprice", pa.float64()),
    ("obi", pa.float64()),
    ("spread", pa.float64()),
    ("time_to_expiry_seconds", pa.float64()),
])

ssl_context = ssl.create_default_context(cafile=certifi.where())

async def get_target_btc_markets() -> dict:
    """
    Autonomously scans the Polymarket API and selects the top 120 short/medium term markets.
    Requires ZERO human input.
    """
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    headers = {"User-Agent": "Mozilla/5.0"}
    
    found_markets = []
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        print("\n[Discovery] Querying Polymarket API for active crypto markets...")
        
        offset = 0
        limit_per_request = 100
        
        while True:
            url = f"{POLYMARKET_GAMMA_API}&offset={offset}"
            
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        print(f"[!] API Warning: HTTP {resp.status} at offset {offset}. Gracefully ending scan.")
                        break
                        
                    events = await resp.json()
                    if not isinstance(events, list) or len(events) == 0:
                        break
                        
                    for event in events:
                        markets = event.get("markets", [])
                        for m in markets:
                            try:
                                q = str(m.get("question") or "")
                                g = str(m.get("groupItemTitle") or "")
                                d = str(m.get("description") or "")
                                t = str(m.get("title") or "")
                                slug = str(m.get("slug") or "")
                                
                                title = f"{q} {g} {d} {t} {slug}".lower()
                                
                                if "bitcoin" in title or "btc" in title:
                                    # Purity Filter
                                    exclude = ["gta", "elon", "tweet", "election", "movie", "ceo", "pop", "taylor", "reserve", "china"]
                                    if not any(x in title for x in exclude):
                                        
                                        clob_raw = m.get("clobTokenIds")
                                        if not clob_raw or clob_raw == "[]":
                                            continue
                                            
                                        if isinstance(clob_raw, str):
                                            try:
                                                clob_ids = json.loads(clob_raw)
                                            except json.JSONDecodeError:
                                                continue
                                        elif isinstance(clob_raw, list):
                                            clob_ids = clob_raw
                                        else:
                                            continue
                                            
                                        end_date = m.get("endDate")
                                        ticker = m.get("slug", "btc_market")
                                        
                                        if clob_ids and end_date:
                                            dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                                            current_time = datetime.now(timezone.utc)
                                            seconds_to_expiry = (dt - current_time).total_seconds()
                                            
                                            if seconds_to_expiry > 0:
                                                display_title = (q + " " + g).strip()
                                                if not display_title: display_title = ticker
                                                
                                                # VIP Pass for 5-minute micro-contracts
                                                if "up or down" in title:
                                                    found_markets.append((display_title, clob_ids[0], ticker, dt.timestamp(), 1.0))
                                                else:
                                                    found_markets.append((display_title, clob_ids[0], ticker, dt.timestamp(), seconds_to_expiry))
                            except Exception as inner_e:
                                continue
                                
                    offset += len(events)
                    if len(events) < limit_per_request:
                        break
                        
            except Exception as e:
                print(f"[Discovery] Network error: {e}")
                break
                
            await asyncio.sleep(0.2)
            
    print(f"[Discovery] Total Pure BTC Markets Found: {len(found_markets)}")

    if not found_markets:
        return {}
        
    # Sort by the artificially adjusted expiration (VIP micro-contracts jump to Index 0)
    found_markets.sort(key=lambda x: x[4])
    
    # AUTONOMOUS SELECTION: Grab the top 120 markets for a massive "bulky" dataset
    top_markets = found_markets[:120]
    
    active_tokens = {}
    print(f"[Discovery] Autonomously locked onto Top {len(top_markets)} multi-horizon markets:")
    
    for idx, (title, token_id, ticker, expiry, _) in enumerate(top_markets):
        active_tokens[token_id] = {"ticker": ticker, "expiry": expiry}
        
    print("[Discovery] Market grid initialized. Routing to WebSockets...")
    return active_tokens

async def flush_data_loop(records: list, shutdown_event: asyncio.Event):
    """Background task to force write memory to disk every 60 seconds."""
    while not shutdown_event.is_set():
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        await flush_to_parquet(records)

async def flush_to_parquet(records: list):
    """$O(1)$ Complexity Chunked Writer."""
    if not records:
        return
    df = pd.DataFrame(records)
    records.clear() # Prevent RAM memory leak
    table = pa.Table.from_pandas(df, schema=PARQUET_SCHEMA)
    
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = int(time.time())
    output_file = os.path.join(DATA_DIR, f"batch_{ts}.parquet")
    
    pq.write_table(table, output_file)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Flushed {len(df)} rows to {output_file}")

async def stream_polymarket(shutdown_event: asyncio.Event):
    records = []
    asyncio.create_task(flush_data_loop(records, shutdown_event))

    while not shutdown_event.is_set():
        active_tokens = await get_target_btc_markets()
        
        if not active_tokens:
            print("[ERROR] No valid BTC markets found. Sleeping for 30s...")
            await asyncio.sleep(30)
            continue
        
        token_ids_list = list(active_tokens.keys())
        
        # Structure: books[token_id] = {"bids": {}, "asks": {}}
        books = {tid: {"bids": {}, "asks": {}} for tid in token_ids_list}

        try:
            async with websockets.connect(POLYMARKET_WS_URL, ssl=ssl_context) as ws:
                # Subscribe to all discovered markets simultaneously
                await ws.send(json.dumps({"assets_ids": token_ids_list, "type": "market"}))
                print(f"[Recorder] Subscribed to {len(token_ids_list)} streams. Awaiting ticks...")
                
                async for msg_str in ws:
                    if shutdown_event.is_set():
                        break
                    
                    current_time = time.time()
                    
                    # Check if the CLOSEST market has expired. If so, break and autonomously re-discover!
                    nearest_expiry = min([info["expiry"] for info in active_tokens.values()])
                    if (nearest_expiry - current_time) <= 1.0:
                        print("\n[Recorder] A monitored contract expired! Autonomously re-chaining market list...")
                        await flush_to_parquet(records)
                        break 
                    
                    try:
                        msgs = json.loads(msg_str)
                        if isinstance(msgs, dict): msgs = [msgs]
                        
                        for msg in msgs:
                            asset_id = msg.get("asset_id")
                            if not asset_id or asset_id not in active_tokens:
                                continue
                                
                            market_info = active_tokens[asset_id]
                            bids_book = books[asset_id]["bids"]
                            asks_book = books[asset_id]["asks"]
                            
                            bids = msg.get("bids", [])
                            asks = msg.get("asks", [])
                            
                            for b in bids:
                                p, s = float(b.get("price", 0)), float(b.get("size", 0))
                                if s == 0: bids_book.pop(p, None)
                                else: bids_book[p] = s
                                
                            for a in asks:
                                p, s = float(a.get("price", 0)), float(a.get("size", 0))
                                if s == 0: asks_book.pop(p, None)
                                else: asks_book[p] = s
                                
                            # Sort the books to extract L2 Depth
                            sorted_bids = sorted(bids_book.items(), key=lambda x: x[0], reverse=True)
                            sorted_asks = sorted(asks_book.items(), key=lambda x: x[0])
                            
                            best_bid = sorted_bids[0][0] if sorted_bids else 0.0
                            best_ask = sorted_asks[0][0] if sorted_asks else 0.0
                            
                            if best_bid > 0.0 and best_ask > 0.0:
                                # Extract Level 2 and Level 3 Depth (Pad with 0.0 if empty)
                                bid_px_2 = sorted_bids[1][0] if len(sorted_bids) > 1 else 0.0
                                bid_qty_2 = sorted_bids[1][1] if len(sorted_bids) > 1 else 0.0
                                bid_px_3 = sorted_bids[2][0] if len(sorted_bids) > 2 else 0.0
                                bid_qty_3 = sorted_bids[2][1] if len(sorted_bids) > 2 else 0.0
                                
                                ask_px_2 = sorted_asks[1][0] if len(sorted_asks) > 1 else 0.0
                                ask_qty_2 = sorted_asks[1][1] if len(sorted_asks) > 1 else 0.0
                                ask_px_3 = sorted_asks[2][0] if len(sorted_asks) > 2 else 0.0
                                ask_qty_3 = sorted_asks[2][1] if len(sorted_asks) > 2 else 0.0
                                
                                # Calculate Total Order Book Liquidity
                                total_bid_vol = sum(size for price, size in sorted_bids)
                                total_ask_vol = sum(size for price, size in sorted_asks)

                                spread = best_ask - best_bid
                                midprice = (best_bid + best_ask) / 2
                                bid_qty = bids_book[best_bid]
                                ask_qty = asks_book[best_ask]
                                
                                obi = (bid_qty - ask_qty) / (bid_qty + ask_qty) if (bid_qty + ask_qty) > 0 else 0
                                microprice = (best_bid * ask_qty + best_ask * bid_qty) / (bid_qty + ask_qty) if (bid_qty + ask_qty) > 0 else midprice
                                time_to_expiry = market_info["expiry"] - time.time()
                                
                                records.append({
                                    "timestamp_ns": time.time_ns(),
                                    "ticker": market_info["ticker"],
                                    "best_yes_bid_price": best_bid,
                                    "best_yes_bid_qty": bid_qty,
                                    "bid_px_2": bid_px_2,
                                    "bid_qty_2": bid_qty_2,
                                    "bid_px_3": bid_px_3,
                                    "bid_qty_3": bid_qty_3,
                                    "best_yes_ask_price": best_ask,
                                    "best_yes_ask_qty": ask_qty,
                                    "ask_px_2": ask_px_2,
                                    "ask_qty_2": ask_qty_2,
                                    "ask_px_3": ask_px_3,
                                    "ask_qty_3": ask_qty_3,
                                    "total_bid_vol": total_bid_vol,
                                    "total_ask_vol": total_ask_vol,
                                    "midprice": midprice,
                                    "microprice": microprice,
                                    "obi": obi,
                                    "spread": spread,
                                    "time_to_expiry_seconds": time_to_expiry
                                })
                                
                                if len(records) >= FLUSH_BATCH_SIZE:
                                    await flush_to_parquet(records)
                    except Exception as e:
                        pass
        except Exception as exc:
            print(f"[Recorder] Connection dropped: {exc}. Reconnecting...")
            await asyncio.sleep(2)
            
    await flush_to_parquet(records)

def main():
    print("=" * 60)
    print(" Polymarket Autonomous Night Ingester")
    print("=" * 60)
    shutdown = asyncio.Event()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)
    try:
        loop.run_until_complete(stream_polymarket(shutdown))
    except KeyboardInterrupt:
        shutdown.set()
        loop.run_until_complete(asyncio.sleep(0.5))
    finally:
        loop.close()

if __name__ == "__main__":
    main()