#!/usr/bin/env python3
"""Fetch and verify the pinned target application.

Clones the application named in bench/target.lock at its exact commit into an
untracked checkout, then — unless told not to — proves the checkout is usable by
building it and bringing the stack up until every container reports healthy.

    python infra/bench_setup.py                 fetch, check out, build, start, stop
    python infra/bench_setup.py --no-verify     fetch and check out only
    python infra/bench_setup.py --status        report what is on disk
"""

import argparse
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.common import locks  # noqa: E402  - path setup must precede the import


def run(
    command: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(command)}")
    return subprocess.run(command, cwd=cwd, check=check, text=True)


def capture(command: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip()


def require(tool: str, reason: str) -> None:
    if shutil.which(tool) is None:
        raise SystemExit(f"{tool} is not installed; it is required to {reason}")


def java_major_version() -> int | None:
    """The major version of the java on PATH, or None if there is none."""
    if shutil.which("java") is None:
        return None
    result = subprocess.run(["java", "-version"], capture_output=True, text=True)
    for token in (result.stderr + result.stdout).split('"'):
        head = token.split(".")[0].strip()
        if head.isdigit():
            return int(head)
    return None


def clone(repository: str, checkout: Path) -> None:
    if (checkout / ".git").exists():
        print(f"checkout present at {checkout}")
        return
    checkout.parent.mkdir(parents=True, exist_ok=True)
    print(f"cloning {repository}")
    run(["git", "clone", "--no-checkout", repository, str(checkout)])


def checkout_pin(checkout: Path, commit: str) -> None:
    if capture(["git", "cat-file", "-t", commit], cwd=checkout) != "commit":
        run(["git", "fetch", "--all", "--tags"], cwd=checkout)
    run(["git", "checkout", "--detach", "--force", commit], cwd=checkout)
    run(["git", "clean", "-xdf"], cwd=checkout)
    head = capture(["git", "rev-parse", "HEAD"], cwd=checkout)
    if head != commit:
        raise SystemExit(f"checkout is at {head}, expected the pin {commit}")
    print(f"checked out {head}")


def probe(url: str, timeout: int) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status < 500
    except urllib.error.HTTPError as error:
        return error.code < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def verify(checkout: Path, build: dict) -> None:
    """Build the application and bring the stack up until healthy, then stop it."""
    require("docker", "build the application images and run the stack")
    java = java_major_version()
    required = int(build["java_version"])
    if java is None or java < required:
        found = "no java on PATH" if java is None else f"java {java}"
        raise SystemExit(f"the pin needs java {required} or newer to build; found {found}")

    print("building")
    run(build["build_command"].split(), cwd=checkout)
    print("starting the stack")
    run(build["up_command"].split(), cwd=checkout)
    try:
        timeout = int(build["health_timeout_seconds"])
        for url in build["health_urls"]:
            if not probe(url, timeout=min(timeout, 30)):
                raise SystemExit(f"the stack started but {url} did not answer")
            print(f"  {url} answered")
    finally:
        print("stopping the stack")
        run(build["down_command"].split(), cwd=checkout, check=False)


def status(checkout: Path, commit: str) -> int:
    if not (checkout / ".git").exists():
        print(f"no checkout at {checkout}; run make bench-setup")
        return 1
    head = capture(["git", "rev-parse", "HEAD"], cwd=checkout)
    dirty = capture(["git", "status", "--porcelain"], cwd=checkout)
    print(f"checkout {checkout}")
    print(f"  head {head}")
    print(f"  pin  {commit}")
    print(f"  {'matches the pin' if head == commit else 'DOES NOT match the pin'}")
    if dirty:
        print("  working tree is dirty")
    return 0 if head == commit and not dirty else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-verify", action="store_true", help="skip the build and start check")
    parser.add_argument("--status", action="store_true", help="report on the checkout and exit")
    args = parser.parse_args(argv)

    pin = locks.target()
    checkout = locks.target_checkout()
    commit = pin["target"]["commit"]

    if args.status:
        return status(checkout, commit)

    require("git", "fetch the target application")
    clone(pin["target"]["repository"], checkout)
    checkout_pin(checkout, commit)
    if args.no_verify:
        print("skipping the build and start check")
        return 0
    verify(checkout, pin["build"])
    print("target application builds and starts at the pin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
