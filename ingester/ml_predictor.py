import asyncio
import os
import websockets
import json
import struct
import socket
import time
import aiohttp
import ssl
import certifi
import numpy as np
import torch
import torch.nn as nn
from collections import deque
import torch.nn.functional as F

BINANCE_WS_URL = "wss://data-stream.binance.vision/ws/btcusdt@depth5@100ms"
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com/events?tag_slug=crypto&active=true&closed=false&limit=100"
POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

JAVA_AI_IP = "127.0.0.1"
JAVA_AI_PORT = 8889
JAVA_KALSHI_PORT = 8891
PAPER_TRADE_PORT = 8892

MODEL_PATH = 'leadlag.pt'
MODEL_RELOAD_INTERVAL = 60  # seconds

PACK_FORMAT = ">dd"
KALSHI_PACK_FORMAT = ">Qdd" #40 Bytes
ssl_context = ssl.create_default_context(cafile=certifi.where())

class LeadLagLSTM(nn.Module):
    def __init__(self, input_dim=7, hidden_dim=128, num_layers=2, num_classes=3):
        super().__init__()
        self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim, 
                            num_layers=num_layers, batch_first=True, dropout=0.2)
        self.fc1 = nn.Linear(hidden_dim, 32)
        self.relu = nn.ReLU()
        self.classifier = nn.Linear(32, num_classes)

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        final_thought = lstm_out[:, -1, :] 
        x = self.relu(self.fc1(final_thought))
        return self.classifier(x)

class LeadLagLSTMBinary(nn.Module):
    def __init__(self, input_dim=7, hidden_dim=128, num_layers=2, num_classes=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim, 
                            num_layers=num_layers, batch_first=True, dropout=0.2)
        self.fc1 = nn.Linear(hidden_dim, 32)
        self.relu = nn.ReLU()
        self.classifier = nn.Linear(32, num_classes)

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        final_thought = lstm_out[:, -1, :] 
        x = self.relu(self.fc1(final_thought))
        return self.classifier(x)


MEANS = { 
    'obi': -0.008950, 
    'spread': -0.309061, 
    'time_to_expiry_seconds': 1267.371119, 
    'bin_obi': -0.040751,
    'bin_microprice_momentum': 0.000008, 
    'bin_spread_bps': 0.681603, 
    'bin_volume_ratio': 8.933045
}
STDS = {
    'obi': 0.687926, 
    'spread': 0.225927, 
    'time_to_expiry_seconds': 6686.185122, 
    'bin_obi': 0.483521,
    'bin_microprice_momentum': 0.000063, 
    'bin_spread_bps': 0.621056, 
    'bin_volume_ratio': 87.711903
}

def normalize(feature_name, raw_value):
    std = STDS[feature_name] if STDS[feature_name] != 0 else 1e-6
    return (raw_value - MEANS[feature_name]) / std

global_poly_state = {'obi': 0.0, 'spread': 0.0, 'time_to_expiry_seconds': 0.0, 'bid': 0.0, 'ask': 0.0}

# polymarket search

async def get_top_poly_market() -> dict:
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    found_markets = []
    
    async with aiohttp.ClientSession(connector=connector) as session:
        print("\n[Discovery] Querying Polymarket API for active crypto markets...")
        offset = 0
        limit_per_request = 100
        
        while True:
            url = f"{POLYMARKET_GAMMA_API}&offset={offset}"
            try:
                async with session.get(url) as resp:
                    if resp.status != 200: break
                    events = await resp.json()
                    if not isinstance(events, list) or len(events) == 0: break
                    
                    for event in events:
                        for m in event.get("markets", []):
                            title = f"{m.get('question','')} {m.get('title','')}".lower()
                            if "bitcoin" in title or "btc" in title:
                                if not any(x in title for x in ["gta", "elon", "election"]):
                                    clob_raw = m.get("clobTokenIds")
                                    if clob_raw and clob_raw != "[]":
                                        clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                                        end_date = m.get("endDate")
                                        if end_date:
                                            try:
                                                dt = time.mktime(time.strptime(end_date.replace("Z", "GMT"), "%Y-%m-%dT%H:%M:%S%Z"))
                                                sec_to_exp = dt - time.time()
                                                if sec_to_exp > 0:
                                                    found_markets.append((m.get('question', m.get('title')), clob_ids[0], dt, sec_to_exp))
                                            except ValueError:
                                                pass
                    
                    offset += len(events)
                    if len(events) < limit_per_request: break
            except Exception as e:
                break
            await asyncio.sleep(0.1)
                                        
    found_markets.sort(key=lambda x: x[3])
    
    if not found_markets:
        print("No active BTC markets found on Polymarket.")
        import sys
        sys.exit(1)
        
    top_markets = found_markets[:100]
        
    print("\n" + "="*50)
    print(" POLYMARKET BTC BET SELECTOR")
    print("="*50)
    for idx, target in enumerate(top_markets):
        print(f"[{idx}] {target[0]}")
    print("="*50)
    
    while True:
        try:
            choice = input("Enter the index number of the bet to target: ")
            idx = int(choice)
            if 0 <= idx < len(top_markets):
                target = top_markets[idx]
                print(f"\nLocked onto: {target[0]}")
                print("Beginning dual-stream inference loop...\n")
                return {"token_id": target[1], "expiry": target[2]}
            else:
                print("Invalid index. Please try again.")
        except ValueError:
            print("Please enter a valid number.")
        except (KeyboardInterrupt, EOFError):
            import sys
            sys.exit(1)

async def stream_polymarket(target_market):
    while True:
        try:
            async with websockets.connect(POLYMARKET_WS_URL, ssl=ssl_context) as ws:
                await ws.send(json.dumps({"assets_ids": [target_market["token_id"]], "type": "market"}))
                async for msg_str in ws:
                    msg = json.loads(msg_str)
                    if isinstance(msg, list): msg = msg[0]
                    bids = msg.get("bids", [])
                    asks = msg.get("asks", [])
                    if bids and asks:
                        best_bid = float(bids[0].get("price", 0))
                        best_bid_qty = float(bids[0].get("size", 0))
                        best_ask = float(asks[0].get("price", 0))
                        best_ask_qty = float(asks[0].get("size", 0))
                        total_vol = best_bid_qty + best_ask_qty
                        if total_vol > 0:
                            global_poly_state['obi'] = (best_bid_qty - best_ask_qty) / total_vol
                            global_poly_state['spread'] = best_ask - best_bid
                            global_poly_state['time_to_expiry_seconds'] = target_market['expiry'] - time.time()
                            global_poly_state['bid'] = best_bid
                            global_poly_state['ask'] = best_ask
        except Exception as e:
            await asyncio.sleep(2)

# ==========================================
# 5. HOT-SWAP MODEL RELOADER
# ==========================================
async def model_hot_reloader(model, device):
    """Background task: polls leadlag.pt mtime every 60s and atomically
    swaps weights into the live model without blocking inference."""
    last_mtime = 0.0
    try:
        last_mtime = os.path.getmtime(MODEL_PATH)
    except OSError:
        pass

    print(f"[hot-swap] Watching '{MODEL_PATH}' for weight updates (interval={MODEL_RELOAD_INTERVAL}s)")

    while True:
        await asyncio.sleep(MODEL_RELOAD_INTERVAL)
        try:
            current_mtime = os.path.getmtime(MODEL_PATH)
            if current_mtime != last_mtime:
                print(f"[hot-swap] Detected new weights (mtime changed). Loading...")

                # Load into a temporary CPU model to avoid disrupting GPU memory
                new_state_dict = torch.load(MODEL_PATH, map_location='cpu', weights_only=True)

                # Move weights to the live device
                new_state_dict = {k: v.to(device) for k, v in new_state_dict.items()}

                # Atomic pointer swap — sub-millisecond, never blocks inference
                model.load_state_dict(new_state_dict)
                model.eval()

                last_mtime = current_mtime
                print(f"[hot-swap] ✅ Live model updated successfully at {time.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[hot-swap] ⚠️  Reload failed (original weights preserved): {e}")


# ==========================================
# 6. BINANCE STREAMING & LIVE INFERENCE
# ==========================================
async def live_inference_loop(model, device):
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sequence_memory = deque(maxlen=50)
    bin_microprice_hist = deque(maxlen=10)
    tick_count = 0

    async with websockets.connect(BINANCE_WS_URL, ssl=ssl_context) as ws:
        while True:
            try:
                raw_message = await ws.recv()
                data = json.loads(raw_message)
                bid_px, bid_qty = float(data['bids'][0][0]), float(data['bids'][0][1])
                ask_px, ask_qty = float(data['asks'][0][0]), float(data['asks'][0][1])
                total_vol = bid_qty + ask_qty
                if total_vol == 0: continue

                midprice = (bid_px + ask_px) / 2.0
                microprice = ((bid_qty * ask_px) + (ask_qty * bid_px)) / total_vol
                bin_obi = (bid_qty - ask_qty) / total_vol
                bin_spread_bps = (ask_px - bid_px) / midprice * 10000
                bin_volume_ratio = bid_qty / ask_qty if ask_qty > 0 else 1.0
                
                bin_microprice_hist.append(microprice)
                bin_mom_10 = (microprice - bin_microprice_hist[0]) / bin_microprice_hist[0] if len(bin_microprice_hist) == 10 else 0.0

                norm_features = [
                    normalize('obi', global_poly_state['obi']),
                    normalize('spread', global_poly_state['spread']),
                    normalize('time_to_expiry_seconds', global_poly_state['time_to_expiry_seconds']),
                    normalize('bin_obi', bin_obi),
                    normalize('bin_microprice_momentum', bin_mom_10),
                    normalize('bin_spread_bps', bin_spread_bps),
                    normalize('bin_volume_ratio', bin_volume_ratio)
                ]
                
                sequence_memory.append(norm_features)
                
                if len(sequence_memory) == 50:
                    x_tensor = torch.tensor([list(sequence_memory)], dtype=torch.float32).to(device)
                    with torch.no_grad():
                        raw_logits = model(x_tensor)
                        probabilities = torch.softmax(raw_logits, dim=1)
                        if probabilities.shape[1] == 2:
                            prob_down = probabilities[0][0].item()
                            prob_up = probabilities[0][1].item()
                        else:
                            prob_down = probabilities[0][0].item()
                            prob_up = probabilities[0][2].item()
                    
                    # Dual-broadcast: Java AI engine + Paper Trade Reporter
                    payload = struct.pack(PACK_FORMAT, prob_down, prob_up)
                    udp_socket.sendto(payload, (JAVA_AI_IP, JAVA_AI_PORT))
                    udp_socket.sendto(payload, (JAVA_AI_IP, PAPER_TRADE_PORT))

                    # Send the Kalshi/Polymarket ask data to Java's KALSHI_PORT (8891)
                    # Java MathEngine expects >Qdd (timestamp, bid, ask)
                    kalshi_payload = struct.pack(KALSHI_PACK_FORMAT, int(time.time() * 1000), global_poly_state['bid'], global_poly_state['ask'])
                    udp_socket.sendto(kalshi_payload, (JAVA_AI_IP, JAVA_KALSHI_PORT))

                    tick_count += 1
                    if tick_count % 100 == 0:
                        print(
                            f"[ml] tick {tick_count:,}  |  "
                            f"P(down)={prob_down:.4f}  P(up)={prob_up:.4f}  |  "
                            f"bin_microprice=${microprice:,.2f}  poly_obi={global_poly_state['obi']:+.3f}"
                        )
                else:
                    tick_count += 1
                    if tick_count % 100 == 0:
                        print(f"[ml] tick {tick_count:,}  |  warming up ({len(sequence_memory)}/50)")

            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                pass

import sys

def _init_model(is_binary=False):
    """Initialize model and device — shared by inference loop and hot-reloader."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_path = "leadlag_binary.pt" if is_binary else MODEL_PATH
    model = LeadLagLSTMBinary().to(device) if is_binary else LeadLagLSTM().to(device)
    try:
        model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
        print(f"[ml] Model loaded from '{model_path}' on {device}")
    except FileNotFoundError:
        print(f"[ml] Warning: '{model_path}' not found. Starting with random weights.")
    model.eval()
    return model, device


async def main():
    if "--prompt-only" in sys.argv:
        target = await get_top_poly_market()
        with open(".target_market.json", "w") as f:
            json.dump(target, f)
        return

    is_binary = "--binary" in sys.argv
    # Initialize shared model and device
    model, device = _init_model(is_binary=is_binary)

    if "--run-only" in sys.argv:
        with open(".target_market.json", "r") as f:
            target_market = json.load(f)
        await asyncio.gather(
            stream_polymarket(target_market),
            live_inference_loop(model, device),
            model_hot_reloader(model, device),
        )
        return

    target_market = await get_top_poly_market()
    await asyncio.gather(
        stream_polymarket(target_market),
        live_inference_loop(model, device),
        model_hot_reloader(model, device),
    )

if __name__ == "__main__":
    asyncio.run(main())
