#!/usr/bin/env python3
import sys
import os
import pyarrow.parquet as pq

def main():
    # Find the most recently created parquet file starting with kalshi_training_data
    files = [f for f in os.listdir('.') if f.startswith('kalshi_training_data_') and f.endswith('.parquet')]
    
    if not files:
        print("Error: No .parquet files found in the current directory.")
        sys.exit(1)
        
    # Sort by creation time to get the latest
    files.sort(key=lambda x: os.path.getctime(x), reverse=True)
    latest_file = files[0]
    
    
    try:
        table = pq.read_table(latest_file)
        
        num_rows = table.num_rows
        print(f"Total Row Count: {num_rows}")
        
        expected_columns = [
            'timestamp_ns', 'ticker', 'best_yes_bid_price', 
            'best_yes_ask_price', 'midprice', 'microprice', 
            'obi', 'spread', 'time_to_expiry_seconds'
        ]
        
        actual_columns = table.schema.names
        
        for col in expected_columns:
            assert col in actual_columns, f" Missing '{col}'"
            print(f"Column '{col}' exists.")
            
        
    except Exception as e:
        sys.exit(1)

if __name__ == "__main__":
    main()
