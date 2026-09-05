import socket
import concurrent.futures

def check_target(ip, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        result = s.connect_ex((ip, port))
        s.close()
        if result == 0:
            return (ip, port)
    except Exception:
        pass
    return None

def main():
    print("Scanning subnet 192.168.124.X for NAS services...")
    ips = [f"192.168.124.{i}" for i in range(1, 255) if i != 16]
    ports = [5432, 5000, 5001, 80, 22]
    
    tasks = [(ip, p) for ip in ips for p in ports]
    found = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(check_target, ip, p) for ip, p in tasks]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                found.append(res)
                print(f"  --> FOUND Active Service: IP={res[0]}, Port={res[1]}")

    print("\nScan completed!")
    print("Found active endpoints:", found)

if __name__ == "__main__":
    main()
