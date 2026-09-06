"""扫描显式提供的 NAS 主机端口。"""
import concurrent.futures
import os
import socket


host = os.environ.get("NAS_HOST")
if not host:
    raise SystemExit("Set NAS_HOST before running this script")


def check_port(port: int):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.3)
        return port if connection.connect_ex((host, port)) == 0 else None


with concurrent.futures.ThreadPoolExecutor(max_workers=200) as executor:
    open_ports = [port for port in executor.map(check_port, range(1, 10000)) if port]
print(open_ports)
