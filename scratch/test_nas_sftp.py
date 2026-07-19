import paramiko
import sys

NAS_IP = "192.168.124.16"
NAS_PORT = 22
NAS_USER = "admin2022"
NAS_PASS = "Admin20221013"

print(f"Attempting SFTP connection to NAS ({NAS_IP}:{NAS_PORT})...")
try:
    transport = paramiko.Transport((NAS_IP, NAS_PORT))
    transport.connect(username=NAS_USER, password=NAS_PASS)
    sftp = paramiko.SFTPClient.from_transport(transport)
    print("SFTP Connection established successfully!")
    
    # 专门检索 NAS 上的 home 个人目录
    target_dirs = ["/home"]
    for d in target_dirs:
        try:
            files = sftp.listdir(d)
            print(f"\nDirectory '{d}' contents:")
            for f in files:
                print(f"  - {f}")
        except Exception as e:
            print(f"Could not list directory '{d}': {e}")
            
    sftp.close()
    transport.close()
except Exception as e:
    print(f"SFTP failed: {e}")
