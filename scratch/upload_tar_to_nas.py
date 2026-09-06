"""把本地 PostgreSQL 镜像压缩包上传到显式配置的 NAS。"""
import os
from pathlib import Path

import paramiko


host = os.environ.get("NAS_HOST")
user = os.environ.get("NAS_USER")
password = os.environ.get("NAS_PASSWORD")
port = int(os.environ.get("NAS_PORT", "22"))
if not all((host, user, password)):
    raise SystemExit("Set NAS_HOST, NAS_USER and NAS_PASSWORD before running this script")

local_path = Path(os.environ.get("POSTGRES_IMAGE_TAR", Path.home() / "Downloads/postgres.tar"))
remote_path = os.environ.get("NAS_REMOTE_TAR", "/home/postgres.tar")
if not local_path.is_file():
    raise SystemExit(f"Image archive does not exist: {local_path}")

transport = paramiko.Transport((host, port))
try:
    transport.connect(username=user, password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        sftp.put(str(local_path), remote_path)
        print(f"Uploaded {local_path.name} to {remote_path}")
    finally:
        sftp.close()
finally:
    transport.close()
