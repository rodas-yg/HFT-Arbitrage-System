#!/usr/bin/env python3
"""
report.py — Post-Market Paper Trading Evaluator
================================================
An asyncio daemon that evaluates the AI's real-time predictions
against actual market outcomes, generating a performance report.

Architecture:
    ml_predictor.py  ──UDP(8892)──▶  report.py
                                          │
                                          ├── Logs high-confidence signals as hypothetical trades
                                          ├── Spawns asyncio.sleep(time_to_expiry) per market
                                          └── Queries Polymarket Gamma API for final resolution
                                               │
                                               └── Generates markdown report with PnL, Win Rate,
                                                   Slippage, and Confusion Matrix

Usage:
    python report.py

    The script reads .target_market.json for the active market's token_id
    and expiry. It listens on UDP port 8892 for dual-broadcast packets
    from the refactored ml_predictor.py.
"""

import asyncio
import json
import os
import ssl
import struct
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import aiohttp
import certifi

# ── Configuration ────────────────────────────────────────────────────────────

UDP_LISTEN_PORT = 8892
CONFIDENCE_THRESHOLD = 0.60
PACK_FORMAT = ">dd"  # prob_down, prob_up — big-endian to match ml_predictor.py
PACK_SIZE = struct.calcsize(PACK_FORMAT)

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
TARGET_MARKET_FILE = ".target_market.json"
REPORTS_DIR = "reports"

ssl_context = ssl.create_default_context(cafile=certifi.where())


# ── Trade Ledger ─────────────────────────────────────────────────────────────

class TradeLedger:
    """Stores hypothetical trade entries triggered by high-confidence AI signals."""

    def __init__(self):
        self.trades: list[dict] = []
        self.resolved_trades: list[dict] = []
        self._lock = asyncio.Lock()

    async def log_trade(self, timestamp: float, direction: str,
                        entry_price: float, confidence: float,
                        token_id: str, time_to_expiry: float):
        """Record a hypothetical trade entry."""
        async with self._lock:
            trade = {
                "timestamp": timestamp,
                "datetime": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
                "direction": direction,  # "UP" or "DOWN"
                "entry_price": entry_price,
                "confidence": confidence,
                "token_id": token_id,
                "time_to_expiry": time_to_expiry,
                "resolution": None,
                "resolution_price": None,
                "pnl": None,
            }
            self.trades.append(trade)
            print(
                f"[ledger] 📝 Trade #{len(self.trades)}: {direction} @ "
                f"${entry_price:.4f} (conf={confidence:.4f}, "
                f"expiry={time_to_expiry:.0f}s)"
            )
            return trade

    async def resolve_trade(self, trade: dict, resolution: str,
                            resolution_price: float):
        """Mark a trade as resolved with the actual outcome."""
        async with self._lock:
            trade["resolution"] = resolution
            trade["resolution_price"] = resolution_price

            # PnL calculation:
            # If we predicted UP and bought YES tokens at entry_price,
            #   resolution YES=1.0 → PnL = 1.0 - entry_price
            #   resolution NO=0.0  → PnL = 0.0 - entry_price
            # If we predicted DOWN and bought NO tokens at (1 - entry_price),
            #   resolution NO=1.0  → PnL = 1.0 - (1 - entry_price) = entry_price
            #   resolution YES=1.0 → PnL = 0.0 - (1 - entry_price)
            if trade["direction"] == "UP":
                trade["pnl"] = resolution_price - trade["entry_price"]
            else:  # DOWN
                trade["pnl"] = (1.0 - resolution_price) - (1.0 - trade["entry_price"])

            self.resolved_trades.append(trade)
            status = "✅ WIN" if trade["pnl"] > 0 else "❌ LOSS"
            print(
                f"[ledger] {status} Trade resolved: {trade['direction']} "
                f"entry=${trade['entry_price']:.4f} → "
                f"resolution=${resolution_price:.4f} "
                f"PnL={trade['pnl']:+.4f}"
            )


# ── Polymarket Price Fetcher ─────────────────────────────────────────────────

async def fetch_current_midprice(token_id: str) -> float | None:
    """Fetch the current midprice for a token from Polymarket's Gamma API.

    Returns the midprice as a float, or None on failure.
    """
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            # Query by token_id through the markets endpoint
            url = f"{POLYMARKET_GAMMA_API}/markets?clob_token_ids={token_id}&limit=1"
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"[price] Warning: Gamma API returned HTTP {resp.status}")
                    return None
                markets = await resp.json()
                if isinstance(markets, list) and len(markets) > 0:
                    market = markets[0]
                    best_bid = float(market.get("bestBid", 0))
                    best_ask = float(market.get("bestAsk", 0))
                    if best_bid > 0 and best_ask > 0:
                        return (best_bid + best_ask) / 2.0
                    # Fallback to outcomePrices
                    outcome_prices = market.get("outcomePrices")
                    if outcome_prices:
                        prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                        if prices:
                            return float(prices[0])
    except Exception as e:
        print(f"[price] Error fetching midprice: {e}")
    return None


async def fetch_market_resolution(token_id: str) -> tuple[str, float]:
    """Query Polymarket Gamma API for the final resolution of a market.

    Returns (resolution_status, resolution_price) where:
        resolution_price is 1.0 if YES resolved, 0.0 if NO resolved.
    """
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            url = f"{POLYMARKET_GAMMA_API}/markets?clob_token_ids={token_id}&limit=1"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "UNKNOWN", 0.5

                markets = await resp.json()
                if isinstance(markets, list) and len(markets) > 0:
                    market = markets[0]

                    # Check resolution status
                    closed = market.get("closed", False)
                    resolved = market.get("resolved", False)
                    resolution = market.get("resolution", "")

                    if resolved or closed:
                        # Determine outcome price
                        outcome_prices = market.get("outcomePrices")
                        if outcome_prices:
                            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                            yes_price = float(prices[0]) if prices else 0.5
                            return resolution or "RESOLVED", yes_price

                        # Fallback: infer from resolution field
                        if resolution and resolution.lower() in ("yes", "1"):
                            return "YES", 1.0
                        elif resolution and resolution.lower() in ("no", "0"):
                            return "NO", 0.0

                    return "PENDING", 0.5

    except Exception as e:
        print(f"[resolution] Error querying resolution: {e}")

    return "ERROR", 0.5


# ── UDP Protocol ─────────────────────────────────────────────────────────────

class ProbabilityReceiver(asyncio.DatagramProtocol):
    """Receives (prob_down, prob_up) UDP packets from ml_predictor.py."""

    def __init__(self, ledger: TradeLedger, token_id: str,
                 expiry_ts: float, loop: asyncio.AbstractEventLoop):
        self.ledger = ledger
        self.token_id = token_id
        self.expiry_ts = expiry_ts
        self.loop = loop
        self.tick_count = 0

    def connection_made(self, transport):
        self.transport = transport
        print(f"[udp] Listening on port {UDP_LISTEN_PORT} for AI probability broadcasts")

    def datagram_received(self, data: bytes, addr: tuple):
        if len(data) < PACK_SIZE:
            return

        prob_down, prob_up = struct.unpack(PACK_FORMAT, data[:PACK_SIZE])
        self.tick_count += 1
        time_to_expiry = self.expiry_ts - time.time()

        if time_to_expiry <= 0:
            return  # Market already expired

        # Log periodically
        if self.tick_count % 500 == 0:
            print(
                f"[udp] tick {self.tick_count:,} | "
                f"P(down)={prob_down:.4f} P(up)={prob_up:.4f} | "
                f"expiry={time_to_expiry:.0f}s"
            )

        # Check for high-confidence signal
        if prob_up > CONFIDENCE_THRESHOLD:
            asyncio.ensure_future(
                self._process_signal("UP", prob_up, time_to_expiry),
                loop=self.loop,
            )
        elif prob_down > CONFIDENCE_THRESHOLD:
            asyncio.ensure_future(
                self._process_signal("DOWN", prob_down, time_to_expiry),
                loop=self.loop,
            )

    async def _process_signal(self, direction: str, confidence: float,
                              time_to_expiry: float):
        """Log a trade and fetch the current entry price."""
        entry_price = await fetch_current_midprice(self.token_id)
        if entry_price is None:
            entry_price = 0.5  # Fallback if API is unavailable
            print("[signal] Warning: Could not fetch live price, using 0.5 as fallback")

        await self.ledger.log_trade(
            timestamp=time.time(),
            direction=direction,
            entry_price=entry_price,
            confidence=confidence,
            token_id=self.token_id,
            time_to_expiry=time_to_expiry,
        )

    def error_received(self, exc):
        print(f"[udp] Error: {exc}")


# ── Expiry Watcher ───────────────────────────────────────────────────────────

async def expiry_watcher(ledger: TradeLedger, token_id: str,
                         expiry_ts: float):
    """Wait until market expiry, then resolve all trades and generate report."""
    time_to_expiry = expiry_ts - time.time()

    if time_to_expiry > 0:
        print(f"[watcher] ⏰ Market expires in {time_to_expiry:.0f}s "
              f"({time_to_expiry/3600:.1f}h). Waiting...")
        await asyncio.sleep(time_to_expiry)

    # Add a grace period for settlement
    print("[watcher] Market expiry reached. Waiting 60s for settlement...")
    await asyncio.sleep(60)

    # Query resolution
    print("[watcher] Querying Polymarket for final resolution...")
    resolution_status, resolution_price = await fetch_market_resolution(token_id)
    print(f"[watcher] Resolution: {resolution_status} (YES price = {resolution_price})")

    # Resolve all trades
    for trade in ledger.trades:
        if trade["resolution"] is None:
            await ledger.resolve_trade(trade, resolution_status, resolution_price)

    # Generate report
    await generate_report(ledger, token_id, resolution_status, resolution_price)


# ── Report Generation ────────────────────────────────────────────────────────

async def generate_report(ledger: TradeLedger, token_id: str,
                          resolution_status: str, resolution_price: float):
    """Generate a clean markdown report with PnL, Win Rate, Slippage, and Confusion Matrix."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORTS_DIR, f"paper_trade_{timestamp_str}.md")

    resolved = [t for t in ledger.trades if t["pnl"] is not None]

    if not resolved:
        report = _generate_empty_report(token_id, resolution_status)
    else:
        report = _generate_full_report(
            resolved, token_id, resolution_status, resolution_price,
        )

    with open(report_path, "w") as f:
        f.write(report)

    print(f"\n[report] 📊 Report saved to: {report_path}")
    print(f"[report] Total trades: {len(resolved)}")


def _generate_empty_report(token_id: str, resolution_status: str) -> str:
    """Generate a report when no trades were made."""
    return f"""# Paper Trade Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## Summary

| Metric | Value |
|--------|-------|
| Token ID | `{token_id[:16]}...` |
| Market Resolution | {resolution_status} |
| Total Trades | 0 |

> No high-confidence signals (>{CONFIDENCE_THRESHOLD}) were detected during this session.
> The AI's confidence remained below the threshold for the entire market duration.
"""


def _generate_full_report(trades: list[dict], token_id: str,
                          resolution_status: str,
                          resolution_price: float) -> str:
    """Generate the full performance report."""

    # ── Metrics ──
    total_pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    # Average slippage: mean |confidence - resolution_price|
    slippages = []
    for t in trades:
        if t["direction"] == "UP":
            expected = t["confidence"]
            actual = t["resolution_price"]
        else:
            expected = t["confidence"]
            actual = 1.0 - t["resolution_price"]
        slippages.append(abs(expected - actual))
    avg_slippage = sum(slippages) / len(slippages) if slippages else 0

    # ── Confusion Matrix ──
    # Actual outcome: UP if resolution_price >= 0.5, DOWN otherwise
    actual_up = resolution_price >= 0.5

    # Predicted UP / Actual UP (True Positive)
    tp = sum(1 for t in trades if t["direction"] == "UP" and actual_up)
    # Predicted UP / Actual DOWN (False Positive)
    fp = sum(1 for t in trades if t["direction"] == "UP" and not actual_up)
    # Predicted DOWN / Actual DOWN (True Negative)
    tn = sum(1 for t in trades if t["direction"] == "DOWN" and not actual_up)
    # Predicted DOWN / Actual UP (False Negative)
    fn = sum(1 for t in trades if t["direction"] == "DOWN" and actual_up)

    # ── Trade Log ──
    trade_rows = ""
    for i, t in enumerate(trades[:50], 1):  # Cap at 50 rows for readability
        trade_rows += (
            f"| {i} | {t['datetime'][:19]} | {t['direction']} | "
            f"${t['entry_price']:.4f} | {t['confidence']:.4f} | "
            f"{t['pnl']:+.4f} |\n"
        )

    up_trades = sum(1 for t in trades if t["direction"] == "UP")
    down_trades = sum(1 for t in trades if t["direction"] == "DOWN")

    report = f"""# Paper Trade Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## Market Summary

| Metric | Value |
|--------|-------|
| Token ID | `{token_id[:16]}...` |
| Market Resolution | **{resolution_status}** |
| Resolution Price (YES) | {resolution_price:.4f} |
| Confidence Threshold | {CONFIDENCE_THRESHOLD} |

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| **Total Theoretical PnL** | **{total_pnl:+.4f}** |
| **Win Rate** | **{win_rate:.1f}%** ({len(wins)}W / {len(losses)}L) |
| **Average Slippage** | {avg_slippage:.4f} |
| Total Trades | {len(trades)} |
| UP Signals | {up_trades} |
| DOWN Signals | {down_trades} |

---

## Confusion Matrix

Actual market outcome: **{"UP (YES resolved)" if actual_up else "DOWN (NO resolved)"}**

|  | Actual UP | Actual DOWN |
|--|-----------|-------------|
| **Predicted UP** | {tp} (TP) | {fp} (FP) |
| **Predicted DOWN** | {fn} (FN) | {tn} (TN) |

"""

    # Precision / Recall if applicable
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    report += f"""| Metric | Value |
|--------|-------|
| Precision (UP) | {precision:.4f} |
| Recall (UP) | {recall:.4f} |
| F1 Score | {f1:.4f} |

---

## Trade Log (first {min(50, len(trades))} entries)

| # | Timestamp | Direction | Entry Price | Confidence | PnL |
|---|-----------|-----------|-------------|------------|-----|
{trade_rows}
---

*Report generated by report.py*
*Threshold: >{CONFIDENCE_THRESHOLD} | UDP Port: {UDP_LISTEN_PORT}*
"""

    return report


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print(" Paper Trade Reporter — Post-Market Evaluator Daemon")
    print("=" * 60)

    # Load target market info
    if not os.path.exists(TARGET_MARKET_FILE):
        print(f"[FATAL] {TARGET_MARKET_FILE} not found.")
        print("  Run ml_predictor.py --prompt-only first to select a market.")
        sys.exit(1)

    with open(TARGET_MARKET_FILE, "r") as f:
        target = json.load(f)

    token_id = target["token_id"]
    expiry_ts = target["expiry"]
    time_to_expiry = expiry_ts - time.time()

    print(f"  Token ID       : {token_id[:24]}...")
    print(f"  Expiry         : {datetime.fromtimestamp(expiry_ts, tz=timezone.utc).isoformat()}")
    print(f"  Time to expiry : {time_to_expiry:.0f}s ({time_to_expiry/3600:.1f}h)")
    print(f"  UDP Port       : {UDP_LISTEN_PORT}")
    print(f"  Threshold      : {CONFIDENCE_THRESHOLD}")
    print("=" * 60)

    if time_to_expiry <= 0:
        print("[FATAL] Market has already expired. Nothing to track.")
        sys.exit(1)

    ledger = TradeLedger()
    loop = asyncio.get_running_loop()

    # Start UDP listener
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: ProbabilityReceiver(ledger, token_id, expiry_ts, loop),
        local_addr=("0.0.0.0", UDP_LISTEN_PORT),
    )

    try:
        # Run the expiry watcher — this blocks until market closes + settlement
        await expiry_watcher(ledger, token_id, expiry_ts)
    except asyncio.CancelledError:
        print("\n[reporter] Cancelled. Generating partial report...")
        resolution_status, resolution_price = await fetch_market_resolution(token_id)
        for trade in ledger.trades:
            if trade["resolution"] is None:
                await ledger.resolve_trade(trade, resolution_status, resolution_price)
        await generate_report(ledger, token_id, resolution_status, resolution_price)
    finally:
        transport.close()
        print("[reporter] Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[reporter] Interrupted by user.")
