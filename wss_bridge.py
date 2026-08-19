import asyncio
import websockets
import json
import subprocess
import re
import sys
import threading
import ssl
import time
import os
import signal
from datetime import datetime, timezone
import glob
import aiohttp
import certifi

clients = set()
latest_telemetry = {
    "type": "telemetry",
    "probUp": 50.0,
    "probDown": 50.0,
    "obi": 0.0,
    "momentum": 0.0
}
live_markets = []  # list of dicts with question, token_id, expiry, time_to_expiry

# Engine state
engine_process = None
engine_thread = None
loop = None
selected_market = None  # tracks what the user picked

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com/events?tag_slug=crypto&active=true&closed=false&limit=100"
ssl_context = ssl.create_default_context(cafile=certifi.where())


# ── Market Discovery ─────────────────────────────────────────────────────────
# Mirrors get_top_poly_market() from ingester/ml_predictor.py exactly

async def fetch_markets_async():
    """Paginate through Polymarket Gamma API and filter for Bitcoin/BTC markets.
    Returns list sorted by nearest expiry, exactly like ml_predictor.py."""
    global live_markets
    found = []
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    async with aiohttp.ClientSession(connector=connector) as session:
        print("[discovery] Querying Polymarket API for active crypto markets...")
        offset = 0

        while True:
            url = f"{POLYMARKET_GAMMA_API}&offset={offset}"
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        break
                    events = await resp.json()
                    if not isinstance(events, list) or len(events) == 0:
                        break

                    for event in events:
                        for m in event.get("markets", []):
                            title = f"{m.get('question', '')} {m.get('title', '')}".lower()
                            if "bitcoin" in title or "btc" in title:
                                if not any(x in title for x in ["gta", "elon", "election"]):
                                    clob_raw = m.get("clobTokenIds")
                                    if clob_raw and clob_raw != "[]":
                                        clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                                        end_date = m.get("endDate")
                                        if end_date:
                                            try:
                                                # Parse ISO datetime
                                                clean = end_date.replace("Z", "+00:00")
                                                from datetime import datetime as dt_cls
                                                dt_obj = dt_cls.fromisoformat(clean)
                                                expiry_ts = dt_obj.timestamp()
                                                sec_to_exp = expiry_ts - time.time()
                                                if sec_to_exp > 0:
                                                    found.append({
                                                        "question": m.get("question", m.get("title", "Unknown")),
                                                        "token_id": clob_ids[0],
                                                        "expiry": expiry_ts,
                                                        "time_to_expiry": sec_to_exp,
                                                    })
                                            except (ValueError, IndexError):
                                                pass

                    offset += len(events)
                    if len(events) < 100:
                        break
            except Exception as e:
                print(f"[discovery] Error during pagination: {e}")
                break
            await asyncio.sleep(0.1)

    # Sort by nearest expiry first, exactly like ml_predictor.py
    found.sort(key=lambda x: x["time_to_expiry"])
    live_markets = found[:100]
    print(f"[discovery] Found {len(live_markets)} active BTC markets")
    return live_markets


def format_time_remaining(seconds):
    """Format seconds into human-readable string."""
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    elif seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    else:
        return f"{seconds / 86400:.1f}d"


# ── Engine Management ────────────────────────────────────────────────────────

def run_engine_blocking():
    """Start launch.sh in mode 2 (PREDICTION_MARKET_ARBITRAGE) and stream output."""
    global engine_process
    ml_regex = re.compile(r"P\(down\)=([0-9\.]+)\s+P\(up\)=([0-9\.]+).*poly_obi=([-\.0-9]+)")

    engine_process = subprocess.Popen(
        ["./launch.sh"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid
    )

    # Select mode 2 (PREDICTION_MARKET_ARBITRAGE)
    engine_process.stdin.write("2\n")
    engine_process.stdin.flush()

    for line in iter(engine_process.stdout.readline, ''):
        line = line.strip()
        if not line:
            continue

        print(line, flush=True)

        clean_line = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', line)

        log_type = "info"
        if "HOLD" in clean_line or "-> HOLD" in clean_line or "SUPPRESSED" in clean_line:
            log_type = "warning"
        elif "BUY" in clean_line or "SELL" in clean_line or "EXECUTING" in clean_line or "Executing Trade" in clean_line:
            log_type = "success"

        match = ml_regex.search(clean_line)
        if match:
            p_down = float(match.group(1)) * 100
            p_up = float(match.group(2)) * 100
            obi = float(match.group(3))

            latest_telemetry["probUp"] = p_up
            latest_telemetry["probDown"] = p_down
            latest_telemetry["obi"] = obi
            latest_telemetry["momentum"] = latest_telemetry.get("momentum", 0) * 0.9 + (p_up - p_down) * 0.01

            asyncio.run_coroutine_threadsafe(broadcast(latest_telemetry), loop)

        now = datetime.now()
        timestamp = f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}.{now.microsecond // 1000:03d}"

        log_msg = {
            "type": "log",
            "timestamp": timestamp,
            "message": clean_line,
            "logType": log_type
        }
        asyncio.run_coroutine_threadsafe(broadcast(log_msg), loop)

    engine_process.wait()
    print("[engine] Process exited.")

    # After engine exits (market expired), check for reports
    check_and_send_report()


def check_and_send_report():
    """Look for the latest report file and broadcast it."""
    time.sleep(2)  # allow report.py to finish writing
    reports = glob.glob("reports/paper_trade_*.md")
    if reports:
        latest_report = max(reports, key=os.path.getctime)
        with open(latest_report, "r") as f:
            content = f.read()
        asyncio.run_coroutine_threadsafe(
            broadcast({"type": "report_ready", "markdown": content}),
            loop
        )
        print(f"[bridge] Broadcasted report {latest_report} to frontend")


def stop_engine():
    global engine_process
    if engine_process:
        try:
            os.killpg(os.getpgid(engine_process.pid), signal.SIGTERM)
            engine_process.wait(timeout=5)
        except Exception as e:
            print("[bridge] Error killing engine:", e)
        engine_process = None


def start_engine():
    """Start the engine in a background thread."""
    global engine_thread
    stop_engine()
    engine_thread = threading.Thread(target=run_engine_blocking, daemon=True)
    engine_thread.start()
    print("[bridge] Engine started")


# ── WebSocket Handlers ───────────────────────────────────────────────────────

async def broadcast(message):
    global clients
    if clients:
        dead_clients = set()
        for client in clients.copy():
            try:
                await client.send(json.dumps(message))
            except Exception:
                dead_clients.add(client)
        clients -= dead_clients


async def handler(websocket):
    global clients
    clients.add(websocket)
    try:
        # Send current telemetry
        try:
            await websocket.send(json.dumps(latest_telemetry))
        except Exception:
            return

        # Send the full market list
        if live_markets:
            market_payload = []
            for i, m in enumerate(live_markets):
                market_payload.append({
                    "idx": i,
                    "question": m["question"],
                    "token_id": m["token_id"],
                    "expiry": m["expiry"],
                    "time_to_expiry": m["time_to_expiry"],
                    "time_remaining_str": format_time_remaining(m["time_to_expiry"]),
                })
            try:
                await websocket.send(json.dumps({"type": "markets", "markets": market_payload}))
            except Exception:
                return

        # Send selected market state
        if selected_market:
            try:
                await websocket.send(json.dumps({
                    "type": "market_selected",
                    "question": selected_market["question"],
                    "token_id": selected_market["token_id"],
                    "time_remaining": format_time_remaining(selected_market["time_to_expiry"]),
                }))
            except Exception:
                return

        # Listen for client commands
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "select_market":
                    idx = data.get("idx")
                    if idx is not None and 0 <= idx < len(live_markets):
                        await handle_market_selection(idx)
            except Exception as e:
                print(f"[bridge] Error handling message: {e}")
    except Exception:
        pass
    finally:
        clients.discard(websocket)


async def handle_market_selection(idx):
    """User selected a market from the grid. Write .target_market.json and start the engine."""
    global selected_market
    market = live_markets[idx]
    selected_market = market

    print(f"[bridge] ══════════════════════════════════════════")
    print(f"[bridge] User selected: {market['question']}")
    print(f"[bridge] Token ID:      {market['token_id'][:24]}...")
    print(f"[bridge] Expiry in:     {format_time_remaining(market['time_to_expiry'])}")
    print(f"[bridge] ══════════════════════════════════════════")

    # Write .target_market.json exactly like ml_predictor.py does
    with open(".target_market.json", "w") as f:
        json.dump({"token_id": market["token_id"], "expiry": market["expiry"]}, f)

    # Broadcast selection confirmation to all clients
    await broadcast({
        "type": "market_selected",
        "question": market["question"],
        "token_id": market["token_id"],
        "time_remaining": format_time_remaining(market["time_to_expiry"]),
    })

    # Broadcast engine starting log
    await broadcast({
        "type": "log",
        "timestamp": datetime.now().strftime("%H:%M:%S.000"),
        "message": f"🎯 Locked onto: {market['question']}",
        "logType": "success"
    })
    await broadcast({
        "type": "log",
        "timestamp": datetime.now().strftime("%H:%M:%S.000"),
        "message": f"⏰ Running until expiry ({format_time_remaining(market['time_to_expiry'])}). Engine starting...",
        "logType": "info"
    })

    # Start engine (launch.sh in mode 2, which uses --run-only to read .target_market.json)
    start_engine()


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    global loop
    loop = asyncio.get_running_loop()

    # Step 1: Discover markets (same as ml_predictor.py get_top_poly_market)
    await fetch_markets_async()

    # Step 2: Start WS server and wait for user to pick a market from the UI
    print(f"[bridge] {len(live_markets)} BTC markets ready. Waiting for user selection via frontend...")
    print("Starting WebSocket Server on ws://localhost:8765")
    async with websockets.serve(handler, "localhost", 8765):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
