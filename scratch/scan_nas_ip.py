"""扫描显式提供的 /24 子网中的常见 NAS 服务端口。"""
import concurrent.futures
import os
import socket


def check_target(ip: str, port: int):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.4)
        return (ip, port) if connection.connect_ex((ip, port)) == 0 else None


subnet = os.environ.get("NAS_SUBNET")
if not subnet:
    raise SystemExit("Set NAS_SUBNET to the first three IPv4 octets, for example 192.0.2")
targets = [(f"{subnet}.{host}", port) for host in range(1, 255) for port in (5432, 5000, 5001, 80, 22)]
with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
    found = [result for result in executor.map(lambda target: check_target(*target), targets) if result]
print(found)
