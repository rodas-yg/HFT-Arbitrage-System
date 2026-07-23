#!/usr/bin/env python3
"""
normalize.py — Post-collection normalization & label generation

Reads a raw Parquet file produced by market_recorder.py and outputs:
  1. A normalized Parquet file with z-scored features + forward labels
  2. A normalization_params.json sidecar with mean/std for each feature

Forward labels computed:
  - label_5s_direction:  +1 (up >0.01%), -1 (down >0.01%), 0 (flat)
  - label_30s_direction: same for 30-second horizon
  - label_5s_return:     raw percentage return over 5 seconds (regression target)

Usage:
    python python-ingester/normalize.py data/features_btcusdt_*.parquet
    python python-ingester/normalize.py data/features_btcusdt_*.parquet --threshold 0.0005
"""

import argparse
import json
import os
import sys

import numpy as np
import pyarrow.parquet as pq
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════════

# Features to z-score normalize (obi is already ∈ [-1,1], skip it)
FEATURES_TO_NORMALIZE = [
    "microprice",
    "midprice",
    "spread_bps",
    "volume_ratio",
    "microprice_return_1",
    "microprice_return_5",
    "microprice_return_10",
    "obi_ema_5",
    "microprice_momentum",
]

# Features to log-transform before z-scoring (right-skewed distributions)
FEATURES_TO_LOG = [
    "volume_ratio",
]

# Direction label threshold (0.01% = 1 basis point)
DEFAULT_DIRECTION_THRESHOLD = 0.0001

# Time horizons for forward labels (in seconds)
LABEL_HORIZONS = {
    "5s": 5.0,
    "30s": 30.0,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Forward Label Computation
# ═══════════════════════════════════════════════════════════════════════════════

def compute_forward_labels(df: pd.DataFrame,
                           threshold: float = DEFAULT_DIRECTION_THRESHOLD
                           ) -> pd.DataFrame:
    """Add forward-looking label columns based on future microprice.

    For each row at time t, finds the microprice at time t+horizon and computes:
      - direction: +1 if return > threshold, -1 if < -threshold, 0 otherwise
      - return: raw percentage return

    Uses timestamp_ns for precise time-based lookback rather than tick-count,
    since tick arrival rate varies.
    """
    timestamps = df["timestamp_ns"].values
    microprices = df["microprice"].values
    n = len(df)

    for label_name, horizon_s in LABEL_HORIZONS.items():
        horizon_ns = int(horizon_s * 1e9)
        directions = np.zeros(n, dtype=np.int8)
        returns = np.full(n, np.nan, dtype=np.float64)

        # For each row, binary search for the row at t + horizon
        future_timestamps = timestamps + horizon_ns

        for i in range(n):
            # Find the index of the first timestamp >= t + horizon
            target_ts = future_timestamps[i]
            j = np.searchsorted(timestamps, target_ts, side="left")

            if j >= n:
                # Not enough future data — leave as NaN
                continue

            future_price = microprices[j]
            current_price = microprices[i]

            if current_price == 0.0:
                continue

            ret = (future_price - current_price) / current_price
            returns[i] = ret

            if ret > threshold:
                directions[i] = 1
            elif ret < -threshold:
                directions[i] = -1
            # else: stays 0 (flat)

        df[f"label_{label_name}_direction"] = directions
        df[f"label_{label_name}_return"] = returns

    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  Z-Score Normalization
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_features(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Z-score normalize selected feature columns.

    Returns:
        - The dataframe with normalized feature columns (suffixed _norm)
        - A dict of {feature: {mean, std, log_transformed}} for inference
    """
    params = {}

    for col in FEATURES_TO_NORMALIZE:
        if col not in df.columns:
            print(f"  [warn] skipping missing column: {col}")
            continue

        values = df[col].values.astype(np.float64).copy()
        log_transformed = col in FEATURES_TO_LOG

        # Log-transform if needed (handle zeros and negatives)
        if log_transformed:
            # volume_ratio is always >= 0; add epsilon for log(0)
            values = np.log1p(np.maximum(values, 0.0))

        mean = float(np.nanmean(values))
        std = float(np.nanstd(values))

        if std == 0.0:
            std = 1.0  # Avoid division by zero for constant features

        normalized = (values - mean) / std

        df[f"{col}_norm"] = normalized
        params[col] = {
            "mean": mean,
            "std": std,
            "log_transformed": log_transformed,
        }

    return df, params


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Normalize market recorder data and generate forward labels"
    )
    parser.add_argument(
        "input_file", type=str,
        help="Path to raw Parquet file from market_recorder.py"
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_DIRECTION_THRESHOLD,
        help=f"Direction label threshold (default: {DEFAULT_DIRECTION_THRESHOLD})"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output path for normalized Parquet (default: input_normalized.parquet)"
    )
    args = parser.parse_args()

    # Resolve paths
    input_path = args.input_file
    if args.output:
        output_path = args.output
    else:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_normalized{ext}"

    params_path = os.path.join(
        os.path.dirname(output_path) or ".",
        "normalization_params.json"
    )

    # Read input
    print(f"[normalize] reading {input_path}")
    table = pq.read_table(input_path)
    df = table.to_pandas()
    print(f"[normalize] loaded {len(df):,} rows × {len(df.columns)} columns")

    # Compute forward labels
    print(f"[normalize] computing forward labels (threshold={args.threshold})")
    df = compute_forward_labels(df, threshold=args.threshold)

    # Count label distribution
    for label_name in LABEL_HORIZONS:
        col = f"label_{label_name}_direction"
        if col in df.columns:
            counts = df[col].value_counts().to_dict()
            total = len(df[df[col].notna()])
            print(f"  {col}: +1={counts.get(1, 0):,}  0={counts.get(0, 0):,}  -1={counts.get(-1, 0):,}  NaN={df[col].isna().sum():,}")

    # Normalize features
    print("[normalize] z-score normalizing features")
    df, norm_params = normalize_features(df)

    for col, p in norm_params.items():
        log_str = " (log1p)" if p["log_transformed"] else ""
        print(f"  {col}{log_str}: μ={p['mean']:.6f}, σ={p['std']:.6f}")

    # Drop rows where labels are NaN (end of dataset with no future data)
    rows_before = len(df)
    label_cols = [f"label_{name}_return" for name in LABEL_HORIZONS]
    existing_label_cols = [c for c in label_cols if c in df.columns]
    if existing_label_cols:
        df = df.dropna(subset=existing_label_cols)
    rows_after = len(df)
    print(f"[normalize] dropped {rows_before - rows_after:,} rows with NaN labels "
          f"({rows_after:,} remaining)")

    # Write normalized Parquet
    print(f"[normalize] writing {output_path}")
    df.to_parquet(output_path, engine="pyarrow", compression="snappy", index=False)

    # Write normalization params
    print(f"[normalize] writing {params_path}")
    with open(params_path, "w") as f:
        json.dump({
            "features": norm_params,
            "label_threshold": args.threshold,
            "label_horizons_s": LABEL_HORIZONS,
            "source_file": os.path.basename(input_path),
            "num_rows": rows_after,
        }, f, indent=2)

    print(f"[normalize] done — {rows_after:,} rows normalized")


if __name__ == "__main__":
    main()
