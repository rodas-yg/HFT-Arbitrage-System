#!/usr/bin/env python3
"""
retrainer.py — Continuous Learning Shadow Pipeline
==================================================
Nightly Cron Job script that performs incremental transfer learning
on the LeadLag LSTM model using the last 24 hours of recorded data.

Usage:
    # Production (cron):
    0 3 * * * cd /path/to/global-sentiment-router && .venv/bin/python retrainer.py

    # Dry run (validate data loading without modifying weights):
    python retrainer.py --dry-run

Safety:
    - Severely reduced learning rate (1e-5) to prevent catastrophic forgetting
    - Maximum 2 epochs of fine-tuning
    - Atomic file swap via os.replace()
    - Minimum data threshold guard (500 fused rows)
    - Sanity validation before committing new weights
"""

import argparse
import gc
import glob
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import json
import urllib.request
import ssl
import certifi
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


LOG_FILE = "shadow_retrain.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("shadow_retrainer")



class LeadLagLSTM(nn.Module):
    def __init__(self, input_dim=7, hidden_dim=128, num_layers=2, num_classes=3):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim, hidden_size=hidden_dim,
            num_layers=num_layers, batch_first=True, dropout=0.2,
        )
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
        self.lstm = nn.LSTM(
            input_size=input_dim, hidden_size=hidden_dim,
            num_layers=num_layers, batch_first=True, dropout=0.2,
        )
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
    'bin_volume_ratio': 8.933045,
}
STDS = {
    'obi': 0.687926,
    'spread': 0.225927,
    'time_to_expiry_seconds': 6686.185122,
    'bin_obi': 0.483521,
    'bin_microprice_momentum': 0.000063,
    'bin_spread_bps': 0.621056,
    'bin_volume_ratio': 87.711903,
}

FEATURE_COLS = [
    'obi', 'spread', 'time_to_expiry_seconds',
    'bin_obi', 'bin_microprice_momentum', 'bin_spread_bps', 'bin_volume_ratio',
]


FUTURE_WINDOW_ROWS = 10
PRICE_MOVEMENT_THRESHOLD = 0.005  # 0.5%

POLYMARKET_DIR = "polymarket_data/"
BINANCE_DIR = "data/"
MODEL_PATH = "leadlag.pt"
STAGING_PATH = "leadlag_v2.pt"

SEQUENCE_LENGTH = 50
MIN_FUSED_ROWS = 500
MAX_EPOCHS = 2
LEARNING_RATE = 1e-5
BATCH_SIZE = 64



def _get_recent_poly_files(hours: int = 24) -> list[str]:
    """Select polymarket_data/batch_*.parquet files from the last `hours` hours.

    The timestamp is embedded in the filename: batch_{unix_ts}.parquet
    """
    cutoff_ts = time.time() - (hours * 3600)
    pattern = os.path.join(POLYMARKET_DIR, "batch_*.parquet")
    recent = []
    for f in glob.glob(pattern):
        basename = os.path.basename(f)
        match = re.search(r"batch_(\d+)\.parquet", basename)
        if match:
            file_ts = int(match.group(1))
            if file_ts >= cutoff_ts:
                recent.append(f)
    recent.sort()
    return recent


def _get_recent_binance_files(hours: int = 24) -> list[str]:
    """Select data/features_btcusdt_*.parquet files modified in the last `hours` hours."""
    cutoff_ts = time.time() - (hours * 3600)
    pattern = os.path.join(BINANCE_DIR, "features_btcusdt_*.parquet")
    recent = []
    for f in glob.glob(pattern):
        if os.path.getmtime(f) >= cutoff_ts:
            recent.append(f)
    recent.sort()
    return recent


def _load_parquet_files(file_list: list[str], label: str) -> pd.DataFrame | None:
    """Safely load and concatenate a list of parquet files."""
    dfs = []
    for f in file_list:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception:
            log.warning(f"Skipping corrupt {label} file: {os.path.basename(f)}")
    if not dfs:
        return None
    return pd.concat(dfs, ignore_index=True)



def fetch_market_resolution(ticker):
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    url = f"https://gamma-api.polymarket.com/events?slug={ticker}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            data = json.loads(response.read().decode())
            if len(data) > 0:
                for m in data[0].get("markets", []):
                    resolution = m.get("resolution")
                    if resolution and resolution.lower() in ("yes", "1"):
                        return 1
                    elif resolution and resolution.lower() in ("no", "0"):
                        return 0
                    outcome = m.get("outcomePrices")
                    if outcome:
                        prices = json.loads(outcome) if isinstance(outcome, str) else outcome
                        if prices and float(prices[0]) == 1.0:
                            return 1
                        elif prices and float(prices[0]) == 0.0:
                            return 0
            return None
    except Exception as e:
        log.warning(f"Failed to fetch resolution for {ticker}: {e}")
        return None

def load_and_fuse_data(is_binary=False) -> pd.DataFrame | None:
    """Replicate fusion.py logic on the last 24 hours of data.

    Returns fused DataFrame with target labels, or None on failure.
    """
    # ── Polymarket data ──
    poly_files = _get_recent_poly_files(24)
    log.info(f"Found {len(poly_files)} Polymarket chunks from last 24h")
    if not poly_files:
        log.error("No recent Polymarket data found. Aborting.")
        return None

    df_poly = _load_parquet_files(poly_files, "Polymarket")
    if df_poly is None or df_poly.empty:
        log.error("All Polymarket chunks were corrupt or empty. Aborting.")
        return None

    binance_files = _get_recent_binance_files(24)
    log.info(f"Found {len(binance_files)} Binance chunks from last 24h")
    if not binance_files:
        log.error("No recent Binance data found. Aborting.")
        return None

    df_binance = _load_parquet_files(binance_files, "Binance")
    if df_binance is None or df_binance.empty:
        log.error("All Binance chunks were corrupt or empty. Aborting.")
        return None

    # ── Sort by timestamp ──
    df_poly = df_poly.sort_values("timestamp_ns").reset_index(drop=True)
    df_binance = df_binance.sort_values("timestamp_ns").reset_index(drop=True)

    rename_map = {col: f"bin_{col}" for col in df_binance.columns if col != "timestamp_ns"}
    df_binance = df_binance.rename(columns=rename_map)

    df_fused = pd.merge_asof(
        left=df_poly,
        right=df_binance,
        on="timestamp_ns",
        direction="backward",
    )

    # Drop rows without Binance match
    if 'bin_midprice' in df_fused.columns:
        df_fused = df_fused.dropna(subset=['bin_midprice'])

    log.info(f"Fusion complete: {len(df_fused)} rows")

    # RAM lives matter
    del df_binance, df_poly
    gc.collect()

    if is_binary:
        tickers = df_fused['ticker'].unique()
        log.info(f"Fetching resolutions for {len(tickers)} markets...")
        resolution_map = {}
        for t in tickers:
            res = fetch_market_resolution(t)
            if res is not None:
                resolution_map[t] = res
            time.sleep(0.1)
        
        df_fused['target_label'] = df_fused['ticker'].map(resolution_map)
        df_fused = df_fused.dropna(subset=['target_label'])
        if len(df_fused) == 0:
            log.error("No resolved markets found. Aborting.")
            return None
        df_fused['target_label'] = df_fused['target_label'].astype(int)
    else:
        df_fused['future_poly_midprice'] = df_fused.groupby('ticker')['midprice'].shift(-FUTURE_WINDOW_ROWS)
        df_fused['poly_future_return'] = (
            (df_fused['future_poly_midprice'] - df_fused['midprice']) / df_fused['midprice']
        )
        def classify_target(ret):
            if pd.isna(ret): return np.nan
            if ret >= PRICE_MOVEMENT_THRESHOLD: return 2.0   
            elif ret <= -PRICE_MOVEMENT_THRESHOLD: return 0.0   
            else: return 1.0   
        df_fused['target_label'] = df_fused['poly_future_return'].apply(classify_target)
        df_fused = df_fused.dropna(subset=['target_label'])
        df_fused['target_label'] = df_fused['target_label'].astype(int)

    return df_fused



def _compute_binance_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute bin_obi, bin_spread_bps, bin_volume_ratio, bin_microprice_momentum
    from raw Binance columns if they don't already exist in the fused frame.
    """
    # bin_obi
    if 'bin_obi' not in df.columns:
        if 'bin_bid_qty' in df.columns and 'bin_ask_qty' in df.columns:
            total = df['bin_bid_qty'] + df['bin_ask_qty']
            df['bin_obi'] = (df['bin_bid_qty'] - df['bin_ask_qty']) / total.replace(0, np.nan)
            df['bin_obi'] = df['bin_obi'].fillna(0.0)
        else:
            df['bin_obi'] = 0.0

    # bin_spread_bps
    if 'bin_spread_bps' not in df.columns:
        if 'bin_bid_px' in df.columns and 'bin_ask_px' in df.columns and 'bin_midprice' in df.columns:
            mid = df['bin_midprice'].replace(0, np.nan)
            df['bin_spread_bps'] = ((df['bin_ask_px'] - df['bin_bid_px']) / mid) * 10000
            df['bin_spread_bps'] = df['bin_spread_bps'].fillna(0.0)
        else:
            df['bin_spread_bps'] = 0.0

    # bin_volume_ratio
    if 'bin_volume_ratio' not in df.columns:
        if 'bin_bid_qty' in df.columns and 'bin_ask_qty' in df.columns:
            df['bin_volume_ratio'] = df['bin_bid_qty'] / df['bin_ask_qty'].replace(0, np.nan)
            df['bin_volume_ratio'] = df['bin_volume_ratio'].fillna(1.0)
        else:
            df['bin_volume_ratio'] = 1.0

    # bin_microprice_momentum
    if 'bin_microprice_momentum' not in df.columns:
        if 'bin_microprice' in df.columns:
            df['bin_microprice_momentum'] = df['bin_microprice'].pct_change(periods=10).fillna(0.0)
        else:
            df['bin_microprice_momentum'] = 0.0

    return df


def normalize_features(df: pd.DataFrame) -> pd.DataFrame:
    """Z-score normalize the 7 feature columns using the hardcoded MEANS/STDS."""
    for col in FEATURE_COLS:
        if col in df.columns:
            std = STDS[col] if STDS[col] != 0 else 1e-6
            df[col] = (df[col] - MEANS[col]) / std
        else:
            log.warning(f"Feature '{col}' missing from fused data, filling with 0.0")
            df[col] = 0.0
    return df


def build_sequences(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Roll the fused data into sliding windows of SEQUENCE_LENGTH, grouped by ticker.

    Returns (X, y) where X has shape (N, 50, 7) and y has shape (N,).
    """
    all_X, all_y = [], []

    for ticker, group in df.groupby('ticker'):
        group = group.sort_values('timestamp_ns').reset_index(drop=True)
        features = group[FEATURE_COLS].values
        labels = group['target_label'].values

        for i in range(len(group) - SEQUENCE_LENGTH):
            seq = features[i: i + SEQUENCE_LENGTH]
            label = labels[i + SEQUENCE_LENGTH - 1]  # label at end of window
            all_X.append(seq)
            all_y.append(label)

    if not all_X:
        return np.array([]), np.array([])

    return np.array(all_X, dtype=np.float32), np.array(all_y, dtype=np.int64)



def compute_class_weights(labels: np.ndarray, is_binary=False) -> torch.Tensor:
    """Inverse-frequency class weighting to handle FLAT-class imbalance."""
    classes, counts = np.unique(labels, return_counts=True)
    total = len(labels)
    num_classes = 2 if is_binary else 3
    weights = np.ones(num_classes, dtype=np.float32)
    for cls, cnt in zip(classes, counts):
        if cnt > 0 and int(cls) < num_classes:
            weights[int(cls)] = total / (len(classes) * cnt)
    return torch.tensor(weights)


def validate_model_sanity(model: nn.Module, device: torch.device,
                          X_sample: torch.Tensor) -> bool:
    """Verify the retrained model produces valid softmax outputs."""
    model.eval()
    with torch.no_grad():
        logits = model(X_sample.to(device))
        probs = torch.softmax(logits, dim=1)

        # Check for NaN/Inf
        if torch.isnan(probs).any() or torch.isinf(probs).any():
            log.error("SANITY FAIL: Model produces NaN/Inf outputs!")
            return False

        # Check probabilities sum to ~1
        sums = probs.sum(dim=1)
        if not torch.allclose(sums, torch.ones_like(sums), atol=1e-3):
            log.error("SANITY FAIL: Softmax outputs don't sum to 1!")
            return False

        # Check model isn't degenerate (predicting single class for everything)
        pred_classes = probs.argmax(dim=1)
        unique_preds = pred_classes.unique()
        if len(unique_preds) == 1 and len(X_sample) >= 20:
            log.warning(
                f"SANITY WARNING: Model predicts only class {unique_preds[0].item()} "
                f"for all {len(X_sample)} validation samples. Proceeding with caution."
            )

    return True


def train(model: nn.Module, device: torch.device,
          X: np.ndarray, y: np.ndarray, is_binary: bool = False) -> dict:
    """Fine-tune the model for MAX_EPOCHS with safe hyperparameters.

    Returns a dict of training metrics.
    """
    # Train/validation split (90/10)
    n = len(X)
    split_idx = int(n * 0.9)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    # Build DataLoader
    train_dataset = TensorDataset(
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.long),
    )
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)

    # Class-weighted loss
    class_weights = compute_class_weights(y_train, is_binary=is_binary).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)

    log.info(f"Training: {len(X_train)} samples, {len(X_val)} val samples, "
             f"lr={LEARNING_RATE}, epochs={MAX_EPOCHS}, batch={BATCH_SIZE}")
    log.info(f"Class weights: {class_weights.cpu().tolist()}")

    metrics = {"epochs": [], "val_loss": None, "val_accuracy": None}

    model.train()
    for epoch in range(MAX_EPOCHS):
        total_loss = 0.0
        correct = 0
        total = 0

        for batch_X, batch_y in train_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            logits = model(batch_X)
            loss = criterion(logits, batch_y)
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * batch_X.size(0)
            preds = logits.argmax(dim=1)
            correct += (preds == batch_y).sum().item()
            total += batch_X.size(0)

        epoch_loss = total_loss / total if total > 0 else 0
        epoch_acc = correct / total if total > 0 else 0
        metrics["epochs"].append({"epoch": epoch + 1, "loss": epoch_loss, "accuracy": epoch_acc})
        log.info(f"  Epoch {epoch + 1}/{MAX_EPOCHS} — loss: {epoch_loss:.6f}, acc: {epoch_acc:.4f}")

    # Validation pass
    if len(X_val) > 0:
        model.eval()
        with torch.no_grad():
            val_X_t = torch.tensor(X_val, dtype=torch.float32).to(device)
            val_y_t = torch.tensor(y_val, dtype=torch.long).to(device)
            val_logits = model(val_X_t)
            val_loss = criterion(val_logits, val_y_t).item()
            val_preds = val_logits.argmax(dim=1)
            val_acc = (val_preds == val_y_t).float().mean().item()

        metrics["val_loss"] = val_loss
        metrics["val_accuracy"] = val_acc
        log.info(f"  Validation — loss: {val_loss:.6f}, acc: {val_acc:.4f}")

    return metrics



def main():
    parser = argparse.ArgumentParser(description="Shadow Retrainer — Nightly Transfer Learning")
    parser.add_argument("--binary", action="store_true", help="Train binary resolution model")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate data loading and fusion without modifying weights")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info(" Shadow Retrainer — Continuous Learning Pipeline")
    log.info(f" Timestamp : {datetime.now(timezone.utc).isoformat()}")
    log.info(f" Dry Run   : {args.dry_run}")
    log.info("=" * 60)

    try:
        log.info("[1/5] Loading and fusing last 24h of data...")
        df_fused = load_and_fuse_data(is_binary=args.binary)

        if df_fused is None or len(df_fused) < MIN_FUSED_ROWS:
            row_count = len(df_fused) if df_fused is not None else 0
            log.error(
                f"Insufficient data: {row_count} rows (minimum: {MIN_FUSED_ROWS}). "
                f"Aborting to protect model quality."
            )
            sys.exit(1)

        log.info(f"  Fused dataset: {len(df_fused)} rows, "
                 f"{df_fused['ticker'].nunique()} unique tickers")

        log.info("[2/5] Computing derived features and normalizing...")
        df_fused = _compute_binance_derived_features(df_fused)
        df_fused = normalize_features(df_fused)

        log.info("[3/5] Building sliding window sequences...")
        X, y = build_sequences(df_fused)

        # Free the DataFrame
        del df_fused
        gc.collect()

        if len(X) == 0:
            log.error("No valid sequences could be built. Aborting.")
            sys.exit(1)

        log.info(f"  Sequences: {X.shape[0]} samples, shape={X.shape}")
        unique, counts = np.unique(y, return_counts=True)
        for cls, cnt in zip(unique, counts):
            label_name = {0: "DOWN", 1: "FLAT", 2: "UP"}.get(cls, "?")
            log.info(f"    Class {cls} ({label_name}): {cnt} ({cnt/len(y)*100:.1f}%)")

        if args.dry_run:
            log.info("[DRY RUN] Data validated successfully. Exiting without training.")
            return

        log.info("[4/5] Loading existing model and starting transfer learning...")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        log.info(f"  Device: {device}")

        model = LeadLagLSTMBinary().to(device) if args.binary else LeadLagLSTM().to(device)

        model_path = "leadlag_binary.pt" if args.binary else MODEL_PATH
        if os.path.exists(model_path):
            model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
            log.info(f"  Loaded existing weights from '{model_path}'")
        else:
            if not args.binary:
                log.error(f"Model file '{MODEL_PATH}' not found. Aborting.")
                sys.exit(1)
            else:
                log.info(f"  '{model_path}' not found. Starting with random weights for binary model.")

        metrics = train(model, device, X, y, is_binary=args.binary)

        log.info("[5/5] Validating and exporting retrained model...")

        sanity_sample = torch.tensor(X[:min(50, len(X))], dtype=torch.float32)
        if not validate_model_sanity(model, device, sanity_sample):
            log.error("Model failed sanity check. Original weights preserved.")
            sys.exit(1)

        torch.save(model.state_dict(), STAGING_PATH)
        log.info(f"  Saved staged weights to '{STAGING_PATH}'")

        os.replace(STAGING_PATH, model_path)
        log.info(f"  Atomically replaced '{model_path}' with retrained weights")

        log.info("=" * 60)
        log.info(" Shadow Retrain Complete")
        log.info(f"  Samples trained on : {X.shape[0]}")
        log.info(f"  Final train loss   : {metrics['epochs'][-1]['loss']:.6f}")
        log.info(f"  Final train acc    : {metrics['epochs'][-1]['accuracy']:.4f}")
        if metrics['val_loss'] is not None:
            log.info(f"  Validation loss    : {metrics['val_loss']:.6f}")
            log.info(f"  Validation acc     : {metrics['val_accuracy']:.4f}")
        log.info("=" * 60)

    except Exception:
        log.error(f"Shadow retrain FAILED with exception:\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
