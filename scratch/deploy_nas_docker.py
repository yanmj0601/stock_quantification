import paramiko
import time
import sys

NAS_IP = "192.168.124.16"
NAS_PORT = 22
NAS_USER = "admin2022"
NAS_PASS = "Admin20221013"

print(f"Connecting to NAS ({NAS_IP}:{NAS_PORT}) via SSH...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect(NAS_IP, port=NAS_PORT, username=NAS_USER, password=NAS_PASS, timeout=10)
    print("SSH Connection established successfully!")
except Exception as e:
    print(f"Failed to connect to NAS via SSH: {e}")
    sys.exit(1)

def run_cmd(cmd, sudo=False):
    full_cmd = f"sudo -S {cmd}" if sudo else cmd
    stdin, stdout, stderr = ssh.exec_command(full_cmd)
    if sudo:
        stdin.write(NAS_PASS + "\n")
        stdin.flush()
    # 等待执行完成
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    return exit_status, out, err

# 1. 检查 Docker 是否安装
print("Checking Docker status on NAS...")
status, out, err = run_cmd("docker --version")
if status != 0:
    print(f"Docker is not installed or not accessible on NAS. Error: {err or out}")
    ssh.close()
    sys.exit(1)
print(f"Found Docker: {out.strip()}")

# 2. 清理旧的容器
print("Checking if existing 'evoquant-pg' container exists...")
run_cmd("docker rm -f evoquant-pg", sudo=True)

# 3. 创建持久化数据挂载目录（防呆 fallback）
print("Creating directory for database persistence...")
# 尝试使用群晖标准的 /volume1/docker/postgres
status, out, err = run_cmd("mkdir -p /volume1/docker/postgres", sudo=True)
if status == 0:
    db_volume_path = "/volume1/docker/postgres"
    run_cmd("chmod 777 /volume1/docker/postgres", sudo=True)
else:
    # fallback 使用用户 Home 目录
    print("Could not create directory in /volume1/docker. Falling back to user home directory...")
    run_cmd("mkdir -p ~/postgres_data")
    db_volume_path = "~/postgres_data"

print(f"Using persistence directory: {db_volume_path}")

# 4. 远程拉起 PostgreSQL 容器
docker_cmd = (
    f"docker run --name evoquant-pg "
    f"-e POSTGRES_DB=evoquant "
    f"-e POSTGRES_USER=postgres "
    f"-e POSTGRES_PASSWORD=mysecretpassword "
    f"-p 5432:5432 "
    f"-v {db_volume_path}:/var/lib/postgresql/data "
    f"-d postgres:latest"
)

print("Deploying PostgreSQL Docker container on NAS...")
status, out, err = run_cmd(docker_cmd, sudo=True)
if status != 0:
    print(f"Failed to run PostgreSQL container: {err or out}")
    ssh.close()
    sys.exit(1)

print(f"PostgreSQL container deployed successfully! Container ID: {out.strip()[:12]}")
ssh.close()
print("SSH session closed.")
