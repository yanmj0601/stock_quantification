"""通过 SSH 向显式配置的 NAS 部署 PostgreSQL 容器。"""
import os
import shlex
import sys

import paramiko


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} before running this script")
    return value


host = required_env("NAS_HOST")
port = int(os.environ.get("NAS_PORT", "22"))
user = required_env("NAS_USER")
password = required_env("NAS_PASSWORD")
postgres_password = required_env("POSTGRES_PASSWORD")
volume = os.environ.get("NAS_POSTGRES_VOLUME", "/volume1/docker/postgres")

ssh = paramiko.SSHClient()
ssh.load_system_host_keys()
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
try:
    ssh.connect(host, port=port, username=user, password=password, timeout=10)
except Exception as exc:
    raise SystemExit(f"SSH connection failed: {exc}") from exc


def run(command: str) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(command)
    del stdin
    status = stdout.channel.recv_exit_status()
    return status, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")


try:
    status, output, error = run("docker --version")
    if status:
        raise SystemExit(f"Docker is unavailable: {error or output}")
    run(f"mkdir -p {shlex.quote(volume)}")
    run("docker rm -f evoquant-pg")
    command = " ".join(
        [
            "docker run --name evoquant-pg",
            "-e POSTGRES_DB=evoquant",
            "-e POSTGRES_USER=evoquant",
            f"-e POSTGRES_PASSWORD={shlex.quote(postgres_password)}",
            "-p 5432:5432",
            f"-v {shlex.quote(volume)}:/var/lib/postgresql/data",
            "-d postgres:16-alpine",
        ]
    )
    status, output, error = run(command)
    if status:
        raise SystemExit(f"PostgreSQL deployment failed: {error or output}")
    print(f"PostgreSQL container started: {output.strip()[:12]}")
finally:
    ssh.close()
