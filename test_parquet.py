import pandas as pd
import requests

df = pd.read_parquet("nice_data.parquet")
tickers = df["ticker"].unique()
print("Tickers in nice_data.parquet:", tickers)

# Try fetching one from Gamma API
if len(tickers) > 0:
    slug = tickers[0]
    print(f"Fetching market by slug {slug}...")
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    resp = requests.get(url)
    if resp.status_code == 200:
        print("Response:", resp.json())
    else:
        print("Status Code:", resp.status_code)
