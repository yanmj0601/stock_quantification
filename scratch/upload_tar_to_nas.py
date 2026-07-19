import os
import sys
import paramiko

NAS_IP = "192.168.124.16"
NAS_PORT = 22
NAS_USER = "admin2022"
NAS_PASS = "Admin20221013"

# 查找 Mac 本地下载目录中的 postgres.tar
home_dir = os.path.expanduser("~")
possible_paths = [
    os.path.join(home_dir, "Downloads", "postgres.tar"),
    os.path.join(home_dir, "Downloads", "postgres-latest.tar"),
    "postgres.tar"
]

local_path = None
for path in possible_paths:
    if os.path.exists(path):
        local_path = path
        break

if not local_path:
    print("Error: Could not find 'postgres.tar' in your Mac's Downloads folder.")
    print("Please download it from https://repoflow.com/ first and save it as 'postgres.tar' in your Downloads directory.")
    sys.exit(1)

print(f"Found local image tar: {local_path} ({os.path.getsize(local_path) / 1024 / 1024:.1f} MB)")
print(f"Connecting to NAS ({NAS_IP}) via SFTP...")

try:
    transport = paramiko.Transport((NAS_IP, NAS_PORT))
    transport.connect(username=NAS_USER, password=NAS_PASS)
    sftp = paramiko.SFTPClient.from_transport(transport)
    print("SFTP Connection established successfully!")
    
    remote_path = "/home/postgres.tar"
    print(f"Uploading to NAS: {remote_path}...")
    
    # 带有进度百分比的上传回调
    last_printed = 0
    def progress_callback(transferred, total):
        global last_printed
        percent = int(transferred / total * 100)
        if percent % 5 == 0 and percent != last_printed:
            print(f"  Uploading: {percent}% ({transferred/1024/1024:.1f}MB / {total/1024/1024:.1f}MB)")
            last_printed = percent
            
    sftp.put(local_path, remote_path, callback=progress_callback)
    print("\nFile upload completed successfully!")
    
    sftp.close()
    transport.close()
    print("SFTP Connection closed safely.")
    
except Exception as e:
    print(f"\nUpload failed: {e}")
    sys.exit(1)
