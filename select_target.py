import asyncio
import aiohttp
import ssl
import certifi
import json
import time

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com/events?tag_slug=crypto&active=true&closed=false&limit=100"
ssl_context = ssl.create_default_context(cafile=certifi.where())

async def get_soonest_poly_market():
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    found_markets = []
    
    async with aiohttp.ClientSession(connector=connector) as session:
        offset = 0
        limit_per_request = 100
        
        while True:
            url = f"{POLYMARKET_GAMMA_API}&offset={offset}"
            try:
                async with session.get(url) as resp:
                    if resp.status != 200: break
                    events = await resp.json()
                    if not isinstance(events, list) or len(events) == 0: break
                    
                    for event in events:
                        for m in event.get("markets", []):
                            title = f"{m.get('question','')} {m.get('title','')}".lower()
                            if "bitcoin" in title or "btc" in title:
                                if not any(x in title for x in ["gta", "elon", "election"]):
                                    clob_raw = m.get("clobTokenIds")
                                    if clob_raw and clob_raw != "[]":
                                        clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                                        end_date = m.get("endDate")
                                        if end_date:
                                            try:
                                                dt = time.mktime(time.strptime(end_date.replace("Z", "GMT"), "%Y-%m-%dT%H:%M:%S%Z"))
                                                sec_to_exp = dt - time.time()
                                                if sec_to_exp > 0:
                                                    found_markets.append((m.get('question', m.get('title')), clob_ids[0], dt, sec_to_exp))
                                            except ValueError:
                                                pass
                    
                    offset += len(events)
                    if len(events) < limit_per_request: break
            except Exception as e:
                break
            await asyncio.sleep(0.1)
                                        
    found_markets.sort(key=lambda x: x[3])
    
    if not found_markets:
        print("No active BTC markets found.")
        return None
        
    target = found_markets[0]
    print(f"Locked onto: {target[0]} (expires in {target[3]:.1f}s)")
    return {"token_id": target[1], "expiry": target[2]}

async def main():
    target = await get_soonest_poly_market()
    if target:
        with open(".target_market.json", "w") as f:
            json.dump(target, f)

if __name__ == "__main__":
    asyncio.run(main())
