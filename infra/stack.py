#!/usr/bin/env python3
"""Run the target application as folder-local JVM processes.

Containers are not available on the experiment machine, so this replaces the
pin's compose file. It starts each service from its built jar in the order the
compose file expressed with health conditions — configuration first, then
discovery, then the domain services, then the gateway — waiting for each to
report healthy before launching the next. Ports are pinned on the command line
rather than taken from the shared configuration, which assigns random ones.

Nothing here needs a daemon, a registry or administrative rights. Pid files,
logs and the record of what was started live under an untracked directory.

    python infra/stack.py start [--only NAME ...]
    python infra/stack.py status
    python infra/stack.py logs NAME [--lines N]
    python infra/stack.py stop
"""

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.common import locks, toolchain  # noqa: E402

RECORD_NAME = "stack.json"
POLL_SECONDS = 2.0


@dataclass(frozen=True)
class Service:
    """One service of the local stack."""

    name: str
    module: str
    port: int
    health: str
    wait_seconds: int

    @property
    def health_url(self) -> str:
        return f"http://localhost:{self.port}{self.health}"

    def jar(self, checkout: Path, version: str) -> Path:
        directory = locks.module_path(self.module)
        return checkout / directory / "target" / f"{directory}-{version}.jar"


def services() -> list[Service]:
    return [Service(**entry) for entry in locks.target()["build"]["services"]]


def runtime_directory() -> Path:
    return locks.REPO_ROOT / locks.target()["build"]["runtime_directory"]


def probe(url: str) -> tuple[bool, str]:
    """Whether a service answers, and what it said."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read(400).decode("utf-8", "replace")
            return response.status < 400, body
    except urllib.error.HTTPError as error:
        return False, f"http {error.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return False, str(error)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def read_record(directory: Path) -> dict:
    path = directory / RECORD_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def write_record(directory: Path, record: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RECORD_NAME).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def launch(service: Service, checkout: Path, version: str, directory: Path, home: Path) -> int:
    """Start one service and return its process id."""
    jar = service.jar(checkout, version)
    if not jar.exists():
        raise SystemExit(f"{service.name}: no jar at {jar}; build the application first")
    log = directory / f"{service.name}.log"
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        str(home / "bin" / "java"),
        "-jar",
        str(jar),
        f"--server.port={service.port}",
    ]
    with log.open("w") as sink:
        process = subprocess.Popen(
            command,
            cwd=checkout,
            env=toolchain.environment(home),
            stdout=sink,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (directory / f"{service.name}.pid").write_text(str(process.pid))
    return process.pid


def wait_for(service: Service, pid: int, directory: Path) -> bool:
    """Wait until the service reports healthy, it dies, or its patience runs out."""
    deadline = time.monotonic() + service.wait_seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return False
        healthy, _ = probe(service.health_url)
        if healthy:
            return True
        time.sleep(POLL_SECONDS)
    return False


def start(only: list[str] | None = None) -> int:
    """Start the stack from the pinned checkout.

    NOTE: this boots the PIN, not a run's workspace. There is no parameter for
    a workspace and `checkout` below is always `bench/target`, so a stack
    started here is the unmodified application. Any acceptance check that
    exercised it over the wire would be verifying the pin and reporting the
    result as the agent's — a verified success nobody earned.

    Nothing in the change-request set declares `needs_stack: true`, and the
    schema's `live_stack_incident` difficulty is deliberately unused, for this
    reason. What closing the gap would take is written down in
    bench/VERIFICATION.md. Do not point a live-stack check at this function
    until it is closed.

    Health is also not readiness: the services report healthy before the
    gateway can resolve them through the registry, so a caller that needs the
    gateway must wait for it to answer, not merely for it to be up.
    """
    home, banner = toolchain.check()
    pin = locks.target()
    checkout = locks.target_checkout()
    version = pin["build"]["version"]
    directory = runtime_directory()
    wanted = services()
    if only:
        wanted = [service for service in wanted if service.name in set(only)]
        if not wanted:
            raise SystemExit(f"no such service: {', '.join(only)}")

    print(f"jdk    {banner.splitlines()[0]}")
    print(f"pin    {pin['target']['commit'][:12]}")
    started: list[dict] = []
    for service in wanted:
        healthy, _ = probe(service.health_url)
        if healthy:
            print(f"ok     {service.name} already answering on {service.port}")
            started.append({"name": service.name, "port": service.port, "pid": None})
            continue
        pid = launch(service, checkout, version, directory, home)
        print(f"start  {service.name} on {service.port} (pid {pid})", end="", flush=True)
        if not wait_for(service, pid, directory):
            print(" — did not become healthy")
            print(f"       see {directory / f'{service.name}.log'}")
            write_record(
                directory,
                {
                    "started": started,
                    "failed": service.name,
                    "java_version": banner,
                    "commit": pin["target"]["commit"],
                },
            )
            stop()
            return 1
        print(" — healthy")
        started.append({"name": service.name, "port": service.port, "pid": pid})

    write_record(
        directory,
        {
            "started": started,
            "failed": None,
            "java_version": banner,
            "commit": pin["target"]["commit"],
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    print(f"\n{len(started)} service(s) up")
    return 0


def stop() -> int:
    directory = runtime_directory()
    stopped = 0
    for pid_file in sorted(directory.glob("*.pid")) if directory.exists() else []:
        name = pid_file.stem
        try:
            pid = int(pid_file.read_text().strip())
        except ValueError:
            pid_file.unlink(missing_ok=True)
            continue
        if alive(pid):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            for _ in range(30):
                if not alive(pid):
                    break
                time.sleep(0.5)
            if alive(pid):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
            print(f"stopped {name} (pid {pid})")
            stopped += 1
        pid_file.unlink(missing_ok=True)
    record = read_record(directory)
    if record:
        record["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["started"] = []
        write_record(directory, record)
    if stopped == 0:
        print("nothing to stop")
    return 0


def status() -> int:
    directory = runtime_directory()
    everything_up = True
    for service in services():
        pid_file = directory / f"{service.name}.pid"
        pid = int(pid_file.read_text().strip()) if pid_file.exists() else None
        running = pid is not None and alive(pid)
        healthy, detail = probe(service.health_url)
        state = "healthy" if healthy else ("running" if running else "down")
        everything_up = everything_up and healthy
        note = "" if healthy else f"  {detail[:60]}"
        print(f"{state:8s} {service.name:18s} port {service.port}  pid {pid or '-'}{note}")
    return 0 if everything_up else 1


def logs(name: str, lines: int) -> int:
    log = runtime_directory() / f"{name}.log"
    if not log.exists():
        print(f"no log for {name} at {log}")
        return 1
    content = log.read_text().splitlines()
    print("\n".join(content[-lines:]))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    starter = subparsers.add_parser("start", help="start the stack, health-gated, in order")
    starter.add_argument("--only", nargs="+", help="start just these services")
    subparsers.add_parser("stop", help="stop everything the runner started")
    subparsers.add_parser("status", help="report on each service")
    tail = subparsers.add_parser("logs", help="print the tail of one service's log")
    tail.add_argument("name")
    tail.add_argument("--lines", type=int, default=40)
    arguments = parser.parse_args(argv)

    if arguments.command == "start":
        return start(arguments.only)
    if arguments.command == "stop":
        return stop()
    if arguments.command == "status":
        return status()
    return logs(arguments.name, arguments.lines)


if __name__ == "__main__":
    raise SystemExit(main())
