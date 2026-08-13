import socket
import struct
import time

def send_fake_state(mode, microprice, imbalance, ai_up, ai_down, poly_ask):
    # 41 bytes: mode (1B) + 5 * float64 (8B)
    payload = struct.pack(">Bddddd", mode, microprice, imbalance, ai_up, ai_down, poly_ask)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    
    print(f"Sending -> ai_up={ai_up}, ai_down={ai_down}")
    sock.sendto(payload, ("127.0.0.1", 8890))
    
    try:
        response, _ = sock.recvfrom(1)
        action = response[0]
        action_str = {0: "HOLD", 1: "BUY", 2: "SELL"}.get(action, f"UNKNOWN({action})")
        print(f"Received <- {action_str}")
    except socket.timeout:
        print("Received <- TIMEOUT")

print("--- Test 1: Send ai_down=0.9 (Should trigger SELL) ---")
send_fake_state(1, 64000.0, 0.5, 0.1, 0.9, 0.99)

print("\n--- Test 2: Send ai_down=0.9 immediately again (Should be suppressed -> HOLD) ---")
send_fake_state(1, 64000.0, 0.5, 0.1, 0.9, 0.99)

print("\n--- Test 3: Send ai_up=0.9 (Should be suppressed -> HOLD) ---")
send_fake_state(1, 64000.0, 0.5, 0.9, 0.1, 0.99)
