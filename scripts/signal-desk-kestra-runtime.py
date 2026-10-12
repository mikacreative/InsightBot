#!/usr/bin/env python3
"""Manage an isolated, persistent, loopback-only Kestra proof-of-concept runtime.

No Docker, system Java, global installation, or existing Signal Desk state is
used. Downloads are pinned to published OSS artifacts and checked before use.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile


REPO = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = REPO / ".cache/signal-desk-kestra-poc/runtime"
# 2.0.3's mandatory gRPC controller binds every interface with no host setting.
# Pin the maintained 1.3 line for this entirely loopback-only prototype.
KESTRA_VERSION = "1.3.42"
JDK_VERSION = "21.0.12.1+1"
JDK_URL = (
    "https://github.com/adoptium/temurin21-binaries/releases/download/"
    "jdk-21.0.12.1%2B1/OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.12.1_1.tar.gz"
)
JDK_SHA256 = "3623232f33a9c3baadf304480b2535f9a3cba8a58d42ecbb438ba267315d9998"
KESTRA_URL = (
    "https://repo.maven.apache.org/maven2/io/kestra/kestra/"
    f"{KESTRA_VERSION}/kestra-{KESTRA_VERSION}-exec.zip"
)
# Maven Central publishes SHA-1/MD5 for this artifact, rather than SHA-256.
KESTRA_SHA1 = "f2122bd1f22b4ddea34b6157460e81aa0959789a"
API_PORT = 18978
MANAGEMENT_PORT = 18979


def private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def digest(path: Path, algorithm: str) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def download(url: str, path: Path, algorithm: str, expected: str) -> None:
    if path.is_file() and digest(path, algorithm) == expected:
        return
    temporary = path.with_suffix(path.suffix + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    request = urllib.request.Request(url, headers={"User-Agent": "SignalDesk-local-poc"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            with temporary.open("wb") as target:
                while block := response.read(1024 * 1024):
                    target.write(block)
        if digest(temporary, algorithm) != expected:
            raise RuntimeError(f"Checksum mismatch: {path.name}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(runtime: Path) -> tuple[Path, Path]:
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        raise RuntimeError("This pinned portable JDK is for macOS arm64.")
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime.chmod(0o700)
    for name in ("downloads", "jdk", "kestra", "plugins", f"data-{KESTRA_VERSION}", f"storage-{KESTRA_VERSION}", "tmp", "java-home"):
        directory = runtime / name
        directory.mkdir(exist_ok=True, mode=0o700)
    jdk_archive = runtime / "downloads/temurin21.0.12.1.tar.gz"
    kestra_archive = runtime / f"downloads/kestra-{KESTRA_VERSION}-exec.zip"
    download(JDK_URL, jdk_archive, "sha256", JDK_SHA256)
    download(KESTRA_URL, kestra_archive, "sha1", KESTRA_SHA1)
    java = runtime / "jdk/jdk-21.0.12.1+1/Contents/Home/bin/java"
    if not java.is_file():
        with tarfile.open(jdk_archive, "r:gz") as archive:
            archive.extractall(runtime / "jdk", filter="data")
    kestra = runtime / f"kestra/kestra-{KESTRA_VERSION}"
    if not kestra.is_file():
        with zipfile.ZipFile(kestra_archive) as archive:
            if archive.namelist() != [f"kestra-{KESTRA_VERSION}"]:
                raise RuntimeError("Unexpected Kestra archive layout")
            archive.extractall(runtime / "kestra")
    if not java.is_file() or not kestra.is_file():
        raise RuntimeError("Portable runtime extraction did not produce expected executables")
    java.chmod(0o755)
    kestra.chmod(0o755)
    return java, kestra


def credentials(runtime: Path) -> dict:
    path = runtime / "api-auth.json"
    if path.is_file():
        value = json.loads(path.read_text(encoding="utf-8"))
        if not all(isinstance(value.get(key), str) and value[key] for key in ("username", "password", "encryption_key")):
            raise RuntimeError("Invalid POC credentials file")
        path.chmod(0o600)
        return value
    value = {
        "username": "signal-desk-poc@localhost",
        "password": secrets.token_urlsafe(32),
        "encryption_key": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
    }
    private_json(path, value)
    return value


def write_configuration(runtime: Path, auth: dict) -> Path:
    config = {
        "micronaut": {
            "server": {"host": "127.0.0.1", "port": API_PORT, "netty": {"access-logger": {"enabled": False}}},
        },
        "endpoints": {
            "all": {
                "port": MANAGEMENT_PORT,
                "bind-host": "127.0.0.1",
                "basic-auth": {"username": auth["username"], "password": "${SIGNAL_DESK_POC_KESTRA_PASSWORD}"},
            },
        },
        "datasources": {
            "h2": {
                "url": f"jdbc:h2:file:{runtime / f'data-{KESTRA_VERSION}/database'};TIME ZONE=UTC;DB_CLOSE_DELAY=-1;DB_CLOSE_ON_EXIT=FALSE;LOCK_TIMEOUT=30000",
                "username": "sa", "password": "", "driver-class-name": "org.h2.Driver",
                "maximum-pool-size": 8, "minimum-idle": 2,
            },
        },
        "kestra": {
            "url": f"http://127.0.0.1:{API_PORT}",
            "allocated-cpu-cores": 2,
            "repository": {"type": "h2"}, "queue": {"type": "h2"},
            "storage": {"type": "local", "local": {"base-path": str(runtime / f"storage-{KESTRA_VERSION}")}},
            "plugins": {"path": str(runtime / "plugins"), "auto-install": {"enabled": False}},
            "tutorial-flows": {"enabled": False},
            "anonymous-usage-report": {"enabled": False},
            "ui-anonymous-usage-report": {"enabled": False},
            "encryption": {"secret-key": "${SIGNAL_DESK_POC_KESTRA_ENCRYPTION_KEY}"},
            "server": {
                "basic-auth": {"username": auth["username"], "password": "${SIGNAL_DESK_POC_KESTRA_PASSWORD}"},
                "termination-grace-period": "PT10S",
            },
            "tasks": {"tmp-dir": {"path": str(runtime / "tmp")}},
        },
        # Micronaut refreshes Logback after loading application configuration;
        # carry the explicit location there as well as in JVM startup options.
        "logback": {"configurationFile": str(runtime / "logback.xml")},
        "logger": {"config": str(runtime / "logback.xml"), "levels": {"root": "WARN", "io.kestra": "INFO"}},
    }
    path = runtime / "application.yaml"
    private_json(path, config)  # JSON is a YAML subset; no PyYAML dependency needed.
    logback = runtime / "logback.xml"
    logback.write_text(
        '<configuration><appender name="FILE" class="ch.qos.logback.core.rolling.RollingFileAppender">'
        f'<file>{html.escape(str(runtime / "kestra.log"))}</file>'
        '<rollingPolicy class="ch.qos.logback.core.rolling.SizeAndTimeBasedRollingPolicy">'
        f'<fileNamePattern>{html.escape(str(runtime / "kestra.%d{yyyy-MM-dd}.%i.log.gz"))}</fileNamePattern>'
        '<maxFileSize>4MB</maxFileSize><maxHistory>3</maxHistory><totalSizeCap>12MB</totalSizeCap>'
        '</rollingPolicy><encoder><pattern>%date %-5level %logger{40} - %msg%n</pattern></encoder>'
        '</appender><root level="INFO"><appender-ref ref="FILE"/></root></configuration>',
        encoding="utf-8",
    )
    logback.chmod(0o600)
    return path


def process_id(runtime: Path) -> int | None:
    path = runtime / "runtime.pid"
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False)
    if result.returncode or str(runtime / f"kestra/kestra-{KESTRA_VERSION}") not in result.stdout:
        return None  # Never signal an unrelated process after PID reuse.
    return pid


def healthy(runtime: Path) -> bool:
    try:
        auth = json.loads((runtime / "api-auth.json").read_text(encoding="utf-8"))
        header = "Basic " + base64.b64encode((auth["username"] + ":" + auth["password"]).encode()).decode("ascii")
        request = urllib.request.Request(f"http://127.0.0.1:{API_PORT}/api/v1/configs", headers={"Authorization": header})
        with urllib.request.urlopen(request, timeout=2) as response:
            if json.load(response).get("version") != KESTRA_VERSION:
                return False
        request = urllib.request.Request(f"http://127.0.0.1:{MANAGEMENT_PORT}/health", headers={"Authorization": header})
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.load(response).get("status") == "UP"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return False


def status(runtime: Path) -> dict:
    pid = process_id(runtime)
    return {
        "running": pid is not None, "healthy": bool(pid and healthy(runtime)), "pid": pid,
        "version": KESTRA_VERSION, "jdk_version": JDK_VERSION,
        "base_url": f"http://127.0.0.1:{API_PORT}",
        "management_url": f"http://127.0.0.1:{MANAGEMENT_PORT}",
        "runtime": str(runtime), "api_auth_file": str(runtime / "api-auth.json"),
    }


def check_ports() -> None:
    for port in (API_PORT, MANAGEMENT_PORT):
        with socket.socket() as connection:
            # A graceful restart can leave TIME_WAIT sockets after the listener
            # closes; this still refuses a live service occupying the port.
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                connection.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"localhost:{port} is already occupied; no existing service was stopped") from exc


def start(runtime: Path, timeout: float) -> dict:
    if process_id(runtime):
        return status(runtime)
    check_ports()
    java, kestra = prepare(runtime)
    auth = credentials(runtime)
    config = write_configuration(runtime, auth)
    # Do not inherit provider secrets or unrelated Kestra/Java configuration.
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "USER", "LOGNAME") if key in os.environ}
    environment.update({
        "SIGNAL_DESK_POC_KESTRA_PASSWORD": auth["password"],
        "SIGNAL_DESK_POC_KESTRA_ENCRYPTION_KEY": auth["encryption_key"],
    })
    command = [
        str(java), "-Xms128m", "-Xmx768m", "-XX:ActiveProcessorCount=2", "-XX:MaxDirectMemorySize=128m",
        "-Duser.timezone=UTC", f"-Duser.home={runtime / 'java-home'}", f"-Djava.io.tmpdir={runtime / 'tmp'}",
        f"-Dlogback.configurationFile={runtime / 'logback.xml'}", "-jar", str(kestra),
        "server", "standalone", "--config", str(config), "--worker-thread", "2", "--no-tutorials",
    ]
    output = runtime / "launcher.log"
    with output.open("w", encoding="utf-8") as stream:
        output.chmod(0o600)
        process = subprocess.Popen(command, cwd=runtime, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    (runtime / "runtime.pid").write_text(str(process.pid) + "\n", encoding="utf-8")
    (runtime / "runtime.pid").chmod(0o600)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Kestra exited with status {process.returncode}; inspect {output} and {runtime / 'kestra.log'}")
        if healthy(runtime):
            return status(runtime)
        time.sleep(0.5)
    raise RuntimeError(f"Kestra readiness timed out; inspect {runtime / 'kestra.log'}; runtime PID is {process.pid}")


def stop(runtime: Path, timeout: float = 25) -> dict:
    pid = process_id(runtime)
    if pid:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while process_id(runtime) and time.monotonic() < deadline:
            time.sleep(0.2)
        if process_id(runtime):
            raise RuntimeError("Kestra did not stop gracefully; no force kill was performed")
    (runtime / "runtime.pid").unlink(missing_ok=True)
    return status(runtime)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "start", "stop", "restart", "status"))
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    try:
        if args.action == "prepare":
            prepare(runtime)
            credentials(runtime)
            result = status(runtime)
        elif args.action == "start":
            result = start(runtime, args.timeout)
        elif args.action == "stop":
            result = stop(runtime)
        elif args.action == "restart":
            stop(runtime)
            result = start(runtime, args.timeout)
        else:
            result = status(runtime)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
        print(f"Runtime error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
