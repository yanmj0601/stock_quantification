import socket
import concurrent.futures

def check_port(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        res = s.connect_ex(('192.168.124.14', port))
        s.close()
        if res == 0:
            return port
    except Exception:
        pass
    return None

print("Scanning all open ports on NAS (192.168.124.14)...")
open_ports = []
with concurrent.futures.ThreadPoolExecutor(max_workers=200) as executor:
    futures = [executor.submit(check_port, p) for p in range(1, 10000)]
    for f in concurrent.futures.as_completed(futures):
        p = f.result()
        if p:
            open_ports.append(p)
            print(f"  FOUND Open Port: {p}")

print("\nNAS Open ports list:", sorted(open_ports))
