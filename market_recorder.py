#!/usr/bin/env python3
"""
market_recorder.py — Real-time Binance top-of-book feature recorder.
Connects via WebSocket, computes domain-agnostic features per tick,
and streams batches to a .parquet file for offline LSTM training.
"""

import asyncio
import signal
import time
import sys
import os
from collections import deque
from datetime import datetime, timezone

import websockets
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import orjson


# ──────────────────────────────────────────────────────
#  Config
# ──────────────────────────────────────────────────────
SYMBOL = os.getenv("SYMBOL", "btcusdt")
WS_URL = f"wss://stream.binance.com:9443/ws/{SYMBOL}@bookTicker"
BATCH_FLUSH_SIZE = 10_000
FLUSH_INTERVAL_S = 300  # 5 minutes
MOMENTUM_WINDOW = 10
OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    f"features_{SYMBOL}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.parquet",
)

PARQUET_SCHEMA = pa.schema([
    ("timestamp_ns", pa.int64()),
    ("midprice", pa.float64()),
    ("microprice", pa.float64()),
    ("obi", pa.float64()),
    ("spread_width", pa.float64()),
    ("microprice_momentum", pa.float64()),
    ("implied_probability", pa.float64()),
])


# ──────────────────────────────────────────────────────
#  Feature computation — pure functions, no allocations
# ──────────────────────────────────────────────────────

def compute_midprice(bid_px: float, ask_px: float) -> float:
    """arithmetic mid"""
    return (bid_px + ask_px) * 0.5


def compute_microprice(bid_px: float, bid_qty: float,
                       ask_px: float, ask_qty: float) -> float:
    """volume-weighted mid — shifts toward the heavier side"""
    total_qty = bid_qty + ask_qty
    if total_qty == 0.0:
        return (bid_px + ask_px) * 0.5
    return ((bid_qty * ask_px) + (ask_qty * bid_px)) / total_qty


def compute_obi(bid_qty: float, ask_qty: float) -> float:
    """order book imbalance, clamped to [-1, 1]"""
    total = bid_qty + ask_qty
    if total == 0.0:
        return 0.0
    return max(-1.0, min(1.0, (bid_qty - ask_qty) / total))


def compute_spread_width(bid_px: float, ask_px: float,
                         midprice: float) -> float:
    """relative spread as fraction of mid"""
    if midprice == 0.0:
        return 0.0
    return (ask_px - bid_px) / midprice


def compute_microprice_momentum(current: float,
                                history: deque) -> float:
    """pct change vs. microprice 10 ticks ago; 0.0 if buffer not full"""
    if len(history) < MOMENTUM_WINDOW:
        return 0.0
    old = history[0]
    if old == 0.0:
        return 0.0
    return (current - old) / old


# ──────────────────────────────────────────────────────
#  Parquet writer — appends row-groups without re-reading
# ──────────────────────────────────────────────────────

class ParquetFlusher:
    """handles incremental parquet writes so we never hold more than one batch in RAM"""

    def __init__(self, path: str, schema: pa.Schema):
        self._path = path
        self._schema = schema
        self._writer: pq.ParquetWriter | None = None

    def flush(self, batch: list[dict]) -> int:
        """convert batch to a table and append as a new row-group"""
        if not batch:
            return 0

        table = pa.Table.from_pylist(batch, schema=self._schema)

        if self._writer is None:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            self._writer = pq.ParquetWriter(
                self._path,
                self._schema,
                compression="snappy",
            )

        self._writer.write_table(table)
        n = len(batch)
        return n

    def close(self):
        """finalize the parquet footer"""
        if self._writer is not None:
            self._writer.close()
            self._writer = None


# ──────────────────────────────────────────────────────
#  Core loop
# ──────────────────────────────────────────────────────

async def record(shutdown_event: asyncio.Event):
    """main ws consumer — reconnects on drop, flushes on interval or batch size"""

    flusher = ParquetFlusher(OUTPUT_FILE, PARQUET_SCHEMA)
    batch: list[dict] = []
    microprice_history: deque[float] = deque(maxlen=MOMENTUM_WINDOW)
    total_ticks = 0
    last_flush_time = time.monotonic()

    print(f"[recorder] target file : {OUTPUT_FILE}")
    print(f"[recorder] symbol      : {SYMBOL}")
    print(f"[recorder] flush every : {BATCH_FLUSH_SIZE} ticks or {FLUSH_INTERVAL_S}s")

    try:
        while not shutdown_event.is_set():
            try:
                async with websockets.connect(
                    WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**20,
                ) as ws:
                    print(f"[recorder] connected to {WS_URL}")

                    async for raw_msg in ws:
                        if shutdown_event.is_set():
                            break

                        # -- parse tick
                        msg = orjson.loads(raw_msg)

                        bid_px = float(msg["b"])
                        bid_qty = float(msg["B"])
                        ask_px = float(msg["a"])
                        ask_qty = float(msg["A"])

                        # -- compute features
                        mid = compute_midprice(bid_px, ask_px)
                        micro = compute_microprice(bid_px, bid_qty,
                                                   ask_px, ask_qty)
                        obi = compute_obi(bid_qty, ask_qty)
                        spread = compute_spread_width(bid_px, ask_px, mid)
                        momentum = compute_microprice_momentum(
                            micro, microprice_history
                        )

                        microprice_history.append(micro)

                        batch.append({
                            "timestamp_ns": time.time_ns(),
                            "midprice": mid,
                            "microprice": micro,
                            "obi": obi,
                            "spread_width": spread,
                            "microprice_momentum": momentum,
                            "implied_probability": 0.5,
                        })

                        total_ticks += 1

                        # -- flush check
                        now = time.monotonic()
                        if (len(batch) >= BATCH_FLUSH_SIZE
                                or (now - last_flush_time) >= FLUSH_INTERVAL_S):
                            n = flusher.flush(batch)
                            batch.clear()
                            last_flush_time = now
                            print(
                                f"[recorder] flushed {n:,} rows  |  "
                                f"total: {total_ticks:,}  |  "
                                f"mid: {mid:.2f}"
                            )

            except (websockets.ConnectionClosed,
                    websockets.InvalidStatusCode,
                    ConnectionError,
                    OSError) as exc:
                print(f"[recorder] connection lost ({exc}), reconnecting in 3s…")
                await asyncio.sleep(3)

    finally:
        # drain whatever is left in the buffer
        if batch:
            n = flusher.flush(batch)
            batch.clear()
            print(f"[recorder] final flush: {n:,} rows")

        flusher.close()
        print(f"[recorder] done — {total_ticks:,} total ticks → {OUTPUT_FILE}")


# ──────────────────────────────────────────────────────
#  Entry point with graceful shutdown
# ──────────────────────────────────────────────────────

def main():
    shutdown = asyncio.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)

    try:
        loop.run_until_complete(record(shutdown))
    except KeyboardInterrupt:
        shutdown.set()
        loop.run_until_complete(asyncio.sleep(0.5))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
