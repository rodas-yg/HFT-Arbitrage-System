import socket
import struct
import argparse
import time

def main():
    parser = argparse.ArgumentParser(description="Test dual-mode OCaml Strategy Engine via UDP")
    parser.add_argument("--mode", choices=["binance", "arbitrage"], required=True, help="Mode to simulate")
    args = parser.parse_args()

    mode_byte = 0 if args.mode == "binance" else 1

    pack_format = ">Bdddd"

    # Dummy values
    microprice = 64000.5
    imbalance = -0.9       # Binance Imbalance
    ai_up = 0.90           # AI Prediction Up
    ai_down = 0.05         # AI Prediction Down
    poly_ask = 0.40        # Polymarket Ask

    if mode_byte == 0:
        # Binance mode
        payload = struct.pack(pack_format, mode_byte, microprice, imbalance, ai_up, ai_down)
        print(f"Simulating Binance mode:")
        print(f"  Microprice: {microprice}")
        print(f"  Imbalance:  {imbalance}")
        print(f"  AI Up:      {ai_up}")
        print(f"  AI Down:    {ai_down}")
    else:
        # Arbitrage mode
        payload = struct.pack(pack_format, mode_byte, microprice, imbalance, ai_up, poly_ask)
        print(f"Simulating Arbitrage mode:")
        print(f"  Microprice: {microprice}")
        print(f"  Imbalance:  {imbalance}")
        print(f"  AI Up:      {ai_up}")
        print(f"  Poly Ask:   {poly_ask}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    server_address = ('127.0.0.1', 8890)

    print(f"\nSending payload (size {len(payload)} bytes) to {server_address}...")
    start_time = time.perf_counter_ns()
    
    sock.sendto(payload, server_address)

    try:
        response, _ = sock.recvfrom(1)
        latency_ns = time.perf_counter_ns() - start_time
        
        action_byte = response[0]
        action_str = {0: "HOLD", 1: "BUY", 2: "SELL"}.get(action_byte, "UNKNOWN")
        
        print(f"\nReceived Response: {action_str} (0x{action_byte:02x})")
        print(f"Round-trip Latency: {latency_ns:,} ns")
    except socket.timeout:
        print("\nError: Timed out waiting for response from OCaml strategy server.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
