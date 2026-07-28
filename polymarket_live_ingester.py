#!/usr/bin/env python3
"""
polymarket_live_ingester.py — Live UDP streaming for Polymarket Lead-Lag Arbitrage
"""

import asyncio
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
from dotenv import load_dotenv

load_dotenv()

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=1000"
POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

JAVA_UDP_HOST = "127.0.0.1"
JAVA_UDP_PORT = 8891
UDP_PACKET_FMT = ">Qdd"

ssl_context = ssl.create_default_context(cafile=certifi.where())

async def get_target_btc_market() -> str:
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    headers = {"User-Agent": "Mozilla/5.0"}
    
    found_markets = []
    
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        print("\n[Discovery] Querying Polymarket Events API for active crypto markets...")
        
        offset = 0
        limit = 100
        
        while offset <= 5000:
            url = f"https://gamma-api.polymarket.com/events?tag_slug=crypto&active=true&closed=false&limit={limit}&offset={offset}"
            
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
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
                                            
                                            if clob_ids and end_date:
                                                dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                                                current_time = datetime.now(timezone.utc)
                                                seconds_to_expiry = (dt - current_time).total_seconds()
                                                
                                                if seconds_to_expiry > 0:
                                                    display_title = (q + " " + g).strip()
                                                    
                                                    if "up or down" in title:
                                                        found_markets.append((display_title, clob_ids[0], dt.timestamp(), 1.0))
                                                    else:
                                                        found_markets.append((display_title, clob_ids[0], dt.timestamp(), seconds_to_expiry))
                                except Exception as inner_e:
                                    continue
                    else:
                        print(f"[!] API Warning: Received HTTP {resp.status} at offset {offset}.")
                        break
            except Exception as e:
                print(f"[Discovery] Network error: {e}")
                break
                
            offset += limit
            await asyncio.sleep(0.1)

    if not found_markets:
        print("[ERROR] No active BTC market found on Polymarket.")
        return ""
        
    found_markets.sort(key=lambda x: x[3])
        
    print("\n[Discovery] Found the following active BTC markets:")
    for idx, (t, _, dt_ts, _) in enumerate(found_markets):
        hrs_left = (dt_ts - time.time()) / 3600
        print(f"  [{idx}] [Exp in {hrs_left:.1f} hrs] {t}")
        
    loop = asyncio.get_event_loop()
    while True:
        try:
            choice_str = await loop.run_in_executor(None, input, "\nSelect a market by number: ")
            choice = int(choice_str)
            if 0 <= choice < len(found_markets):
                return found_markets[choice][1]
        except (ValueError, EOFError):
            pass
        print("Invalid choice, try again.")

async def stream_polymarket(shutdown_event: asyncio.Event):
    target_token = await get_target_btc_market()
    if not target_token:
        print("[ERROR] No active BTC market found on Polymarket.")
        return

    print(f"[Polymarket] Subscribing to token ID: {target_token}")
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while not shutdown_event.is_set():
        try:
            async with websockets.connect(POLYMARKET_WS_URL, ssl=ssl_context) as ws:
                sub_msg = {
                    "assets_ids": [target_token],
                    "type": "market"
                }
                await ws.send(json.dumps(sub_msg))
                
                bids_book = {}
                asks_book = {}
                
                async for msg_str in ws:
                    if shutdown_event.is_set():
                        break
                    
                    try:
                        msgs = json.loads(msg_str)
                        if isinstance(msgs, dict):
                            msgs = [msgs]
                            
                        for msg in msgs:
                            bids = msg.get("bids", [])
                            asks = msg.get("asks", [])
                            
                            for b in bids:
                                price = float(b.get("price", 0))
                                size = float(b.get("size", 0))
                                if size == 0:
                                    bids_book.pop(price, None)
                                else:
                                    bids_book[price] = size
                            
                            for a in asks:
                                price = float(a.get("price", 0))
                                size = float(a.get("size", 0))
                                if size == 0:
                                    asks_book.pop(price, None)
                                else:
                                    asks_book[price] = size
                            
                            best_bid = max(bids_book.keys()) if bids_book else 0.0
                            best_ask = min(asks_book.keys()) if asks_book else 0.0
                            
                            if best_bid > 0.0 or best_ask > 0.0:
                                timestamp_ns = time.time_ns()
                                payload = struct.pack(UDP_PACKET_FMT, timestamp_ns, best_bid, best_ask)
                                udp_sock.sendto(payload, (JAVA_UDP_HOST, JAVA_UDP_PORT))
                    except Exception as e:
                        pass
        except Exception as exc:
            print(f"[Polymarket] Connection error: {exc}. Reconnecting...")
            await asyncio.sleep(2)

def main():
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
