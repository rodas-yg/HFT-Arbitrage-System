import pandas as pd
import numpy as np
import glob
import os
import gc

BINANCE_DIR = "data/"          
POLYMARKET_DIR = "polymarket_data/"
OUTPUT_FILE = "master_training_dataset.parquet"
# How far into the future the AI needs to predict

FUTURE_WINDOW_ROWS = 10 
PRICE_MOVEMENT_THRESHOLD = 0.005 # 0.5% price movement required to classify as a Spike/Crash

def load_and_fuse_data():

    binance_files = glob.glob(os.path.join(BINANCE_DIR, "*.parquet"))
    if not binance_files:
        return
        
    binance_dfs = []
    for f in binance_files:
        try:
            df = pd.read_parquet(f)
            binance_dfs.append(df)
        except Exception as e:
            # THIS PREVENTS THE SCRIPT FROM CRASHING ON A BAD FILE
            print(f"skipping corrupt file.")
            
    if not binance_dfs:
        return
        
    df_binance = pd.concat(binance_dfs, ignore_index=True)
    df_binance = df_binance.sort_values("timestamp_ns").reset_index(drop=True)
    poly_files = glob.glob(os.path.join(POLYMARKET_DIR, "*.parquet"))
    if not poly_files:
        return
        
    poly_dfs = []
    for f in poly_files:
        try:
            df = pd.read_parquet(f)
            poly_dfs.append(df)
        except Exception as e:
            # Isolate and discard the specific 60-second chunk that was corrupted
            print(f"    [!] Warning: Skipping corrupted Polymarket chunk: {os.path.basename(f)}")
            
    if not poly_dfs:
        print("[!] ERROR: All Polymarket chunks were corrupted. Cannot proceed.")
        return
        
    df_poly = pd.concat(poly_dfs, ignore_index=True)
    df_poly = df_poly.sort_values("timestamp_ns").reset_index(drop=True)

    rename_map = {col: f"bin_{col}" for col in df_binance.columns if col != "timestamp_ns"}
    df_binance = df_binance.rename(columns=rename_map)

    
    df_fused = pd.merge_asof(
        left=df_poly,
        right=df_binance,
        on="timestamp_ns",
        direction="backward"
    )
    
    df_fused = df_fused.dropna(subset=['bin_midprice'])
    print(f"Fusion Complete")

    # Free up RAM
    del df_binance
    del df_poly
    gc.collect()

    
    df_fused['future_poly_midprice'] = df_fused.groupby('ticker')['midprice'].shift(-FUTURE_WINDOW_ROWS)
    df_fused['poly_future_return'] = (df_fused['future_poly_midprice'] - df_fused['midprice']) / df_fused['midprice']

    def classify_target(ret):
        if pd.isna(ret): return np.nan
        if ret >= PRICE_MOVEMENT_THRESHOLD: return 2.0  # UP (Spike)
        elif ret <= -PRICE_MOVEMENT_THRESHOLD: return 0.0 # DOWN (Crash)
        else: return 1.0 # FLAT (Noise)

    df_fused['target_label'] = df_fused['poly_future_return'].apply(classify_target)
    
    df_fused = df_fused.dropna(subset=['target_label'])
    df_fused['target_label'] = df_fused['target_label'].astype(int)


    df_fused.to_parquet(OUTPUT_FILE, compression='snappy')
    print("done")

if __name__ == "__main__":
    load_and_fuse_data()