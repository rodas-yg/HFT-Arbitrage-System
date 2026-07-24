#!/usr/bin/env python3
"""
ml.py — Real-time LSTM inference for the Global Sentiment Router

Connects to the Binance WebSocket depth feed, computes the same
order-book microstructure features used during training (see
market_recorder.py + normalize.py), runs the HFT-LSTM model on a
sliding 50-tick window, and sends the resulting [prob_down, prob_up]
to the Java execution engine via UDP on port 8889.

Wire Protocol (Python → Java):
  16 bytes = 2 × float64 big-endian
  [prob_down:8B | prob_up:8B]

Usage:
    python ingester/ml.py
    SYMBOL=ethusdt python ingester/ml.py
"""

import asyncio
import signal
import ssl
import struct
import sys
import os
import time
from collections import deque
from socket import socket, AF_INET, SOCK_DGRAM

import certifi
import websockets
import orjson
import torch
import torch.nn as nn
import torch.nn.functional as F



class HftLstm(nn.Module):
    """2-layer LSTM classifier: 6 features → 3 classes (Down / Flat / Up)."""

    def __init__(self, input_dim: int = 6, hidden_dim: int = 64,
                 num_layers: int = 2, num_classes: int = 3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
        )
        self.classifier = nn.Linear(hidden_dim, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)
        return self.classifier(lstm_out[:, -1, :])


# Feature Computation (mirrors market_recorder.py pure functions)

def compute_microprice(bid_px: float, bid_qty: float,
                       ask_px: float, ask_qty: float) -> float:
    """Volume-weighted mid — shifts toward the heavier side.
    Identical to Java OBI.java computation."""
    total_qty = bid_qty + ask_qty
    if total_qty == 0.0:
        return (bid_px + ask_px) * 0.5
    return ((bid_qty * ask_px) + (ask_qty * bid_px)) / total_qty


def compute_obi(bid_qty: float, ask_qty: float) -> float:
    """Order Book Imbalance ∈ [-1, 1].
    Positive = bullish (more buyers), Negative = bearish (more sellers).
    Identical to Java OBI.java computation."""
    total = bid_qty + ask_qty
    if total == 0.0:
        return 0.0
    return (bid_qty - ask_qty) / total


def compute_spread_bps(bid_px: float, ask_px: float,
                       midprice: float) -> float:
    """Spread in basis points (1 bps = 0.01%).
    More normalized than raw spread — comparable across price levels."""
    if midprice == 0.0:
        return 0.0
    return ((ask_px - bid_px) / midprice) * 10_000.0


def compute_return(current: float, history: deque, lookback: int) -> float:
    """Percentage return vs N ticks ago. 0.0 if history is not deep enough."""
    if len(history) < lookback:
        return 0.0
    old = history[-lookback]
    if old == 0.0:
        return 0.0
    return (current - old) / old


def compute_ema(current: float, prev_ema: float, alpha: float) -> float:
    """Exponential Moving Average: alpha * current + (1-alpha) * previous"""
    return alpha * current + (1.0 - alpha) * prev_ema


def compute_microprice_momentum(current: float, history: deque,
                                window: int = 10) -> float:
    """Percentage change vs microprice N ticks ago."""
    if len(history) < window:
        return 0.0
    old = history[-window]
    if old == 0.0:
        return 0.0
    return (current - old) / old


# Z-Score Normalization (parameters from training)

FEATURE_NAMES = [
    "obi", "spread_bps", "obi_ema_5",
    "microprice_return_1", "microprice_return_5", "microprice_momentum",
]

MEANS = {
    "obi":                  -0.025322,
    "spread_bps":            0.004096,
    "obi_ema_5":            -0.025320,
    "microprice_return_1":   0.000000,
    "microprice_return_5":   0.000000,
    "microprice_momentum":   0.000001,
}

STDS = {
    "obi":                   0.743131,
    "spread_bps":            0.037814,
    "obi_ema_5":             0.740615,
    "microprice_return_1":   0.000018,
    "microprice_return_5":   0.000041,
    "microprice_momentum":   0.000059,
}


def z_score(feature: str, value: float) -> float:
    """Z-score normalize a single feature using training-set statistics."""
    return (value - MEANS[feature]) / STDS[feature]



MODEL_PATH = os.path.join(os.path.dirname(__file__), "tuff_prediction.pt")
SEQUENCE_LENGTH = 50          # LSTM trained on 50-tick windows
MOMENTUM_WINDOW = 10
EMA_ALPHA_5 = 2.0 / (5 + 1)  # α for 5-tick EMA ≈ 0.333

# IPC: send [prob_down, prob_up] to Java execution engine
AI_DEST = ("127.0.0.1", 8889)
AI_PACKET_FMT = ">dd"        # 2 × float64 big-endian = 16 bytes


# Inference Loop

async def run_ai(shutdown_event: asyncio.Event):
    """Main inference loop — load model, stream data, predict, send to Java."""

    print(f" loading model from {MODEL_PATH}")
    if not os.path.isfile(MODEL_PATH):
        print(f"[ml] ERROR: model file not found: {MODEL_PATH}")
        sys.exit(1)

    model = HftLstm()
    model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu", weights_only=True))
    model.eval()
    print("[ml] model loaded — inference mode")

    # UDP socket for sending to Java 
    udp_sock = socket(AF_INET, SOCK_DGRAM)

    sequence: deque[list[float]] = deque(maxlen=SEQUENCE_LENGTH)
    microprice_history: deque[float] = deque(maxlen=max(MOMENTUM_WINDOW, 10) + 1)
    obi_ema = 0.0
    tick_count = 0
    prob_down = 0.0
    prob_up = 0.0

    # WebSocket connection
    symbol = os.getenv("SYMBOL", "btcusdt").lower()
    url = f"wss://data-stream.binance.vision/ws/{symbol}@depth5@100ms"
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    while not shutdown_event.is_set():
        try:
            async with websockets.connect(
                url,
                ssl=ssl_context,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=2**20,
            ) as ws:
                print(f"[ml] connected to {url}")

                async for raw_msg in ws:
                    if shutdown_event.is_set():
                        break

                    msg = orjson.loads(raw_msg)
                    bid_px = float(msg["bids"][0][0])
                    bid_qty = float(msg["bids"][0][1])
                    ask_px = float(msg["asks"][0][0])
                    ask_qty = float(msg["asks"][0][1])

                    total_vol = bid_qty + ask_qty
                    if total_vol == 0.0:
                        continue

                    # Compute features (same as market_recorder.py)
                    mid = (bid_px + ask_px) * 0.5
                    micro = compute_microprice(bid_px, bid_qty, ask_px, ask_qty)
                    obi = compute_obi(bid_qty, ask_qty)
                    spread = compute_spread_bps(bid_px, ask_px, mid)
                    obi_ema = compute_ema(obi, obi_ema, EMA_ALPHA_5)

                    ret_1 = compute_return(micro, microprice_history, 1)
                    ret_5 = compute_return(micro, microprice_history, 5)
                    momentum = compute_microprice_momentum(
                        micro, microprice_history, MOMENTUM_WINDOW,
                    )

                    microprice_history.append(micro)

                    # Z-score normalize 
                    features = [
                        z_score("obi", obi),
                        z_score("spread_bps", spread),
                        z_score("obi_ema_5", obi_ema),
                        z_score("microprice_return_1", ret_1),
                        z_score("microprice_return_5", ret_5),
                        z_score("microprice_momentum", momentum),
                    ]
                    sequence.append(features)

                    if len(sequence) == SEQUENCE_LENGTH:
                        with torch.no_grad():
                            tensor = torch.tensor(
                                [list(sequence)], dtype=torch.float32,
                            )
                            logits = model(tensor)
                            probs = F.softmax(logits, dim=1)

                            # Class 0 = Down, Class 1 = Flat, Class 2 = Up
                            prob_down = probs[0][0].item()
                            prob_up = probs[0][2].item()

                            payload = struct.pack(AI_PACKET_FMT, prob_down, prob_up)
                            udp_sock.sendto(payload, AI_DEST)

                    tick_count += 1
                    if tick_count % 500 == 0:
                        if len(sequence) == SEQUENCE_LENGTH:
                            print(
                                f"[ml] tick {tick_count:,}  |  "
                                f"P(down)={prob_down:.4f}  P(up)={prob_up:.4f}  |  "
                                f"microprice=${micro:,.2f}  obi={obi:+.3f}"
                            )
                        else:
                            print(
                                f"[ml] tick {tick_count:,}  |  "
                                f"warming up ({len(sequence)}/{SEQUENCE_LENGTH})"
                            )

        except (websockets.ConnectionClosed,
                websockets.exceptions.InvalidStatus,
                ConnectionError,
                OSError) as exc:
            print(f"[ml] connection lost ({exc}), reconnecting in 3s…")
            await asyncio.sleep(3)


def main():
    shutdown = asyncio.Event()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)

    try:
        loop.run_until_complete(run_ai(shutdown))
    except KeyboardInterrupt:
        shutdown.set()
        loop.run_until_complete(asyncio.sleep(0.5))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
