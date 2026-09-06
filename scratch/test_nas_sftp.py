"""使用环境变量提供的凭据验证 SFTP 访问。"""
import os

import paramiko


host = os.environ.get("NAS_HOST")
user = os.environ.get("NAS_USER")
password = os.environ.get("NAS_PASSWORD")
port = int(os.environ.get("NAS_PORT", "22"))
if not all((host, user, password)):
    raise SystemExit("Set NAS_HOST, NAS_USER and NAS_PASSWORD before running this script")

transport = paramiko.Transport((host, port))
try:
    transport.connect(username=user, password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        for name in sftp.listdir(os.environ.get("NAS_REMOTE_DIR", "/home")):
            print(name)
    finally:
        sftp.close()
finally:
    transport.close()
