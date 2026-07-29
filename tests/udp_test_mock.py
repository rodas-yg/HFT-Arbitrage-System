#!/usr/bin/env python3
import socket
import struct
import time
import os

SOCKET_PATH = "/tmp/gsr_strategy.sock"

def main():
    if not os.path.exists(SOCKET_PATH):
        return

    microprice = 65000.0
    imbalance = -0.99
    ai_confidence = 0.95
    kalshi_ask = 0.40
    
    payload = struct.pack(">dddd", microprice, imbalance, ai_confidence, kalshi_ask)

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(SOCKET_PATH)
        print("Connected!")
        
        client.sendall(payload)
        
        response = client.recv(1)
        if response:
            action = int.from_bytes(response, byteorder='big')
            action_map = {0: "HOLD", 1: "BUY", 2: "SELL"}
            print(f"OCaml Evaluated Action Response: {action_map.get(action, 'UNKNOWN')} (0x{response.hex()})")
        else:
            print("No response from OCaml engine.")
            
    except Exception as e:
        print(f"Connection failed: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    main()
