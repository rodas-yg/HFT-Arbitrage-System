import json
import urllib.request

slug = "btc-updown-5m-1785129900"
url = f"https://gamma-api.polymarket.com/events?slug={slug}"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        if len(data) > 0:
            for m in data[0].get("markets", []):
                print(f"Market ID: {m.get('id')}, Closed: {m.get('closed')}, Resolution: {m.get('resolution')}")
                print(f"Tokens: {m.get('outcomePrices')}")
        else:
            print("No data found for slug.")
except Exception as e:
    print(f"Error: {e}")
