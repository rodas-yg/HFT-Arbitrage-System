#!/usr/bin/env python3
"""
market_recorder.py — ML Training Data Collector for the Global Sentiment Router

Connects to a configurable market data source (Binance by default), computes
order-book microstructure features in real-time, and writes them to compressed
Parquet files for LSTM/Transformer training.

Features recorded per tick:
  Raw:    timestamp_ns, bid_px, bid_qty, ask_px, ask_qty
  Derived: midprice, microprice, obi, spread_bps, volume_ratio,
           microprice_return_1, microprice_return_5, microprice_return_10,
           obi_ema_5, microprice_momentum
  Meta:   source

Forward-looking labels (5s, 30s direction/return) are computed offline by
normalize.py since they require future data not available at recording time.

Usage:
    python market_recorder.py                          # Binance BTC/USDT
    SYMBOL=ethusdt python market_recorder.py            # Binance ETH/USDT
    python market_recorder.py --duration 3600           # Record for 1 hour
"""

import asyncio
import signal
import time
import sys
import os
import ssl
import math
import json
import argparse
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone
from collections.abc import AsyncGenerator
from typing import NamedTuple

import certifi
import websockets
import pyarrow as pa
import pyarrow.parquet as pq
import orjson


#  Data Source Abstraction


class Tick(NamedTuple):
    """A single top-of-book snapshot from any exchange."""
    timestamp_ns: int
    bid_px: float
    bid_qty: float
    ask_px: float
    ask_qty: float


class DataSource(ABC):
    """Abstract base class for market data sources.

    To add a new exchange (Coinbase, Kraken, etc.), subclass this and
    implement the stream() method. OBI computation is exchange-agnostic.
    """
    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for the source (e.g., 'binance', 'coinbase')."""
        ...

    @property
    @abstractmethod
    def symbol(self) -> str:
        """Trading pair symbol (e.g., 'btcusdt')."""
        ...

    @abstractmethod
    def stream(self) -> AsyncGenerator[Tick, None]:
        """Yield Tick objects from the exchange's WebSocket feed.

        Must handle reconnection internally. Should yield ticks indefinitely
        until the connection is closed.
        """
        ...


class BinanceSource(DataSource):
    """Binance bookTicker WebSocket feed.

    Uses the individual symbol bookTicker stream which fires on every
    best bid/ask update (~10-50 ticks/second for BTC/USDT).
    """

    def __init__(self, symbol: str = "btcusdt"):
        self._symbol = symbol.lower()
        self._url = f"wss://data-stream.binance.vision/ws/{self._symbol}@bookTicker"

    @property
    def name(self) -> str:
        return "binance"

    @property
    def symbol(self) -> str:
        return self._symbol

    async def stream(self) -> AsyncGenerator[Tick, None]:
        """Connect to Binance and yield Tick objects.

        Auto-reconnects on connection drops with a 3-second backoff.
        """
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        while True:
            try:
                async with websockets.connect(
                    self._url,
                    ssl=ssl_context,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**20,
                ) as ws:
                    print(f"[recorder] connected to {self._url}")

                    async for raw_msg in ws:
                        msg = orjson.loads(raw_msg)
                        yield Tick(
                            timestamp_ns=time.time_ns(),
                            bid_px=float(msg["b"]),
                            bid_qty=float(msg["B"]),
                            ask_px=float(msg["a"]),
                            ask_qty=float(msg["A"]),
                        )

            except (websockets.ConnectionClosed,
                    websockets.exceptions.InvalidStatus,
                    ConnectionError,
                    OSError) as exc:
                print(f"[recorder] connection lost ({exc}), reconnecting in 3s…")
                await asyncio.sleep(3)


# 
#  Feature Computation (pure functions — no side effects)
# 

def compute_midprice(bid_px: float, ask_px: float) -> float:
    """Arithmetic midpoint: (bid + ask) / 2"""
    return (bid_px + ask_px) * 0.5


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


def compute_volume_ratio(bid_qty: float, ask_qty: float) -> float:
    """Raw volume ratio: bid_qty / ask_qty.
    > 1 = buy pressure, < 1 = sell pressure.
    Log-transformed during normalization for symmetry."""
    if ask_qty == 0.0:
        return 0.0
    return bid_qty / ask_qty


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


#  Parquet Writer — incremental append with row-groups


PARQUET_SCHEMA = pa.schema([
    # Raw order book data
    ("timestamp_ns",         pa.int64()),
    ("bid_px",               pa.float64()),
    ("bid_qty",              pa.float64()),
    ("ask_px",               pa.float64()),
    ("ask_qty",              pa.float64()),
    # Derived features
    ("midprice",             pa.float64()),
    ("microprice",           pa.float64()),
    ("obi",                  pa.float64()),
    ("spread_bps",           pa.float64()),
    ("volume_ratio",         pa.float64()),
    ("microprice_return_1",  pa.float64()),
    ("microprice_return_5",  pa.float64()),
    ("microprice_return_10", pa.float64()),
    ("obi_ema_5",            pa.float64()),
    ("microprice_momentum",  pa.float64()),
    # Metadata
    ("source",               pa.string()),
])


class ParquetFlusher:
    """Incremental Parquet writer — appends row-groups without re-reading.

    Each flush writes a new row-group to the file. The file is finalized
    (footer written) when close() is called.
    """

    def __init__(self, path: str, schema: pa.Schema):
        self._path = path
        self._schema = schema
        self._writer: pq.ParquetWriter | None = None

    def flush(self, batch: list[dict]) -> int:
        """Convert batch to a PyArrow table and append as a new row-group."""
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
        return len(batch)

    def close(self):
        """Finalize the Parquet footer and close the file."""
        if self._writer is not None:
            self._writer.close()
            self._writer = None


# 

BATCH_FLUSH_SIZE = 10_000
FLUSH_INTERVAL_S = 300       # 5 minutes
MOMENTUM_WINDOW = 10
EMA_ALPHA_5 = 2.0 / (5 + 1)  # α for 5-tick EMA = 0.333


async def record(source: DataSource,
                 shutdown_event: asyncio.Event,
                 output_dir: str = "data",
                 max_duration_s: float | None = None):
    """Main recording loop — collects ticks, computes features, writes Parquet.

    Args:
        source:          DataSource to stream ticks from
        shutdown_event:  Set this to gracefully stop recording
        output_dir:      Directory for output Parquet files
        max_duration_s:  Optional max recording duration in seconds
    """
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(
        output_dir,
        f"features_{source.symbol}_{timestamp_str}.parquet",
    )

    flusher = ParquetFlusher(output_file, PARQUET_SCHEMA)
    batch: list[dict] = []
    microprice_history: deque[float] = deque(maxlen=max(MOMENTUM_WINDOW, 10) + 1)
    obi_ema = 0.0
    total_ticks = 0
    last_flush_time = time.monotonic()
    start_time = time.monotonic()

    print("=" * 60)
    print(" Market Recorder — ML Training Data Collector")
    print(f" Source     : {source.name}")
    print(f" Symbol     : {source.symbol}")
    print(f" Output     : {output_file}")
    print(f" Flush every: {BATCH_FLUSH_SIZE:,} ticks or {FLUSH_INTERVAL_S}s")
    if max_duration_s:
        print(f" Duration   : {max_duration_s:.0f}s")
    print(f" Schema     : {len(PARQUET_SCHEMA)} columns")
    print("=" * 60)

    try:
        # pyrefly: ignore [not-iterable]
        async for tick in source.stream():
            if shutdown_event.is_set():
                break

            # Check duration limit
            if max_duration_s and (time.monotonic() - start_time) >= max_duration_s:
                print(f"[recorder] duration limit reached ({max_duration_s:.0f}s)")
                break

            #Compute features 
            mid = compute_midprice(tick.bid_px, tick.ask_px)
            micro = compute_microprice(tick.bid_px, tick.bid_qty,
                                       tick.ask_px, tick.ask_qty)
            obi = compute_obi(tick.bid_qty, tick.ask_qty)
            spread = compute_spread_bps(tick.bid_px, tick.ask_px, mid)
            vol_ratio = compute_volume_ratio(tick.bid_qty, tick.ask_qty)

            # Returns (backward-looking)
            ret_1 = compute_return(micro, microprice_history, 1)
            ret_5 = compute_return(micro, microprice_history, 5)
            ret_10 = compute_return(micro, microprice_history, 10)
            momentum = compute_microprice_momentum(micro, microprice_history,
                                                   MOMENTUM_WINDOW)

            obi_ema = compute_ema(obi, obi_ema, EMA_ALPHA_5)

            # Update history ring
            microprice_history.append(micro)

            #Append to batch 
            batch.append({
                "timestamp_ns":         tick.timestamp_ns,
                "bid_px":               tick.bid_px,
                "bid_qty":              tick.bid_qty,
                "ask_px":               tick.ask_px,
                "ask_qty":              tick.ask_qty,
                "midprice":             mid,
                "microprice":           micro,
                "obi":                  obi,
                "spread_bps":           spread,
                "volume_ratio":         vol_ratio,
                "microprice_return_1":  ret_1,
                "microprice_return_5":  ret_5,
                "microprice_return_10": ret_10,
                "obi_ema_5":            obi_ema,
                "microprice_momentum":  momentum,
                "source":               source.name,
            })

            total_ticks += 1

            # ── Flush check 
            now = time.monotonic()
            if (len(batch) >= BATCH_FLUSH_SIZE
                    or (now - last_flush_time) >= FLUSH_INTERVAL_S):
                n = flusher.flush(batch)
                batch.clear()
                last_flush_time = now
                elapsed = now - start_time
                rate = total_ticks / elapsed if elapsed > 0 else 0
                print(
                    f"[recorder] flushed {n:,} rows  |  "
                    f"total: {total_ticks:,}  |  "
                    f"rate: {rate:.1f} ticks/s  |  "
                    f"mid: ${mid:,.2f}  |  "
                    f"obi: {obi:+.3f}"
                )

    finally:
        # Drain remaining buffer
        if batch:
            n = flusher.flush(batch)
            batch.clear()
            print(f"[recorder] final flush: {n:,} rows")

        flusher.close()
        elapsed = time.monotonic() - start_time
        print(f"[recorder] done — {total_ticks:,} ticks in {elapsed:.1f}s → {output_file}")


#

def main():
    parser = argparse.ArgumentParser(
        description="Market Recorder — ML Training Data Collector"
    )
    parser.add_argument(
        "--symbol", type=str,
        default=os.getenv("SYMBOL", "btcusdt"),
        help="Trading pair symbol (default: btcusdt)"
    )
    parser.add_argument(
        "--source", type=str, default="binance",
        choices=["binance"],
        help="Data source (default: binance)"
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="Max recording duration in seconds (default: unlimited)"
    )
    parser.add_argument(
        "--output-dir", type=str, default="data",
        help="Output directory for Parquet files (default: data/)"
    )
    args = parser.parse_args()

    if args.source == "binance": #may change
        source = BinanceSource(symbol=args.symbol)
    else:
        print(f"Unknown source: {args.source}")
        sys.exit(1)

    shutdown = asyncio.Event()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)

    try:
        loop.run_until_complete(
            record(source, shutdown, args.output_dir, args.duration)
        )
    except KeyboardInterrupt:
        shutdown.set()
        loop.run_until_complete(asyncio.sleep(0.5))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
