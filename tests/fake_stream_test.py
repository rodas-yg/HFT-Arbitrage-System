#!/usr/bin/env python3
import socket
import struct
import time
import math

JAVA_MARKET_PORT = 8888
JAVA_AI_PORT = 8889
JAVA_KALSHI_PORT = 8891
JAVA_IP = "127.0.0.1"

# Packet Formats matching Java Receiver
# Market: >Qdddd (timestamp_ns, bid_px, bid_qty, ask_px, ask_qty)
MARKET_FMT = ">Qdddd"
# AI: >dd (prob_down, prob_up)
AI_FMT = ">dd"
# Kalshi/Polymarket: >Qdd (timestamp_ms, bid, ask)
KALSHI_FMT = ">Qdd"

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print("==================================================")
    print(" FAKE DATA STREAM TEST INJECTOR")
    print("==================================================")
    print(f"Injecting into {JAVA_IP} ports {JAVA_MARKET_PORT}, {JAVA_AI_PORT}, {JAVA_KALSHI_PORT}...")
    
    tick = 0
    while True:
        try:
            # 1. Simulate Market Data (Sine wave around 65000)
            timestamp_ns = time.time_ns()
            base_price = 65000 + math.sin(tick * 0.1) * 100
            bid_px = base_price - 1.0
            ask_px = base_price + 1.0
            bid_qty = 1.0 + math.sin(tick * 0.2) * 0.5  # fluctuate qty
            ask_qty = 1.0 + math.cos(tick * 0.2) * 0.5
            
            market_payload = struct.pack(MARKET_FMT, timestamp_ns, bid_px, bid_qty, ask_px, ask_qty)
            sock.sendto(market_payload, (JAVA_IP, JAVA_MARKET_PORT))
            
            # 2. Simulate AI Predictions (Spike prob_up every 50 ticks to trigger BUY)
            prob_up = 0.9 if (tick % 100) < 10 else 0.1
            prob_down = 0.9 if (tick % 100) >= 50 and (tick % 100) < 60 else 0.1
            
            ai_payload = struct.pack(AI_FMT, prob_down, prob_up)
            sock.sendto(ai_payload, (JAVA_IP, JAVA_AI_PORT))
            
            # 3. Simulate Polymarket Ask Price (Keep < 0.50 so Arbitrage strategy can BUY)
            poly_ask = 0.40 + math.sin(tick * 0.05) * 0.05
            poly_bid = poly_ask - 0.05
            timestamp_ms = int(time.time() * 1000)
            
            kalshi_payload = struct.pack(KALSHI_FMT, timestamp_ms, poly_bid, poly_ask)
            sock.sendto(kalshi_payload, (JAVA_IP, JAVA_KALSHI_PORT))
            
            if tick % 50 == 0:
                print(f"[FakeStream] Sent Tick {tick}: Microprice ~{base_price:.2f} | AI P(UP)={prob_up:.2f} | PolyAsk={poly_ask:.2f}")
                
            tick += 1
            time.sleep(0.01) # 100 ticks per second
            
        except KeyboardInterrupt:
            print("\nShutting down Fake Stream.")
            break
            
if __name__ == "__main__":
    main()
