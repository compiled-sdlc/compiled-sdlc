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
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.common import locks, toolchain  # noqa: E402  - path setup precedes the import


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


def maven_wrapper_version(checkout: Path) -> str:
    """The Maven the pin's own wrapper fetches."""
    properties = checkout / ".mvn" / "wrapper" / "maven-wrapper.properties"
    if not properties.exists():
        return "unknown"
    for line in properties.read_text().splitlines():
        if line.startswith("distributionUrl"):
            return line.rsplit("/", 1)[-1].removeprefix("apache-maven-").removesuffix("-bin.zip")
    return "unknown"


def verify(checkout: Path, build: dict) -> dict:
    """Build the application, bring the stack up until healthy, then stop it.

    The pin ships a container build and a compose file; containers are not
    available here, so the application is built as plain jars and run as
    folder-local processes. What is proved is the same thing the compose path
    proves: the pin builds, and every service the experiment needs starts and
    answers.
    """
    home, banner = toolchain.check()
    print(f"jdk    {banner.splitlines()[0]}")

    print("building")
    build_command = build["build_command"].split()
    built = subprocess.run(build_command, cwd=checkout, env=toolchain.environment(home))
    if built.returncode != 0:
        raise SystemExit("the pin did not build")

    print("starting the stack")
    started = subprocess.run(build["up_command"].split(), cwd=locks.REPO_ROOT)
    if started.returncode != 0:
        raise SystemExit("the stack did not come up")

    probes = []
    for service in build["services"]:
        url = f"http://localhost:{service['port']}{service['health']}"
        answered = probe(url, timeout=15)
        print(f"  {service['name']:18s} {'answered' if answered else 'DID NOT ANSWER'}")
        probes.append({"name": service["name"], "port": service["port"], "healthy": answered})

    print("stopping the stack")
    subprocess.run(build["down_command"].split(), cwd=locks.REPO_ROOT, check=False)

    if not all(entry["healthy"] for entry in probes):
        raise SystemExit("the stack started but not every service answered")

    return {
        "jdk_banner": banner,
        "jdk_major": toolchain.major_version(banner),
        "maven": maven_wrapper_version(checkout),
        "services": probes,
    }


def write_environment_record(details: dict, commit: str) -> Path:
    """Record what the pin was verified on. No machine-specific paths are recorded."""
    path = locks.REPO_ROOT / "bench" / "environment.lock"
    lines = [
        "# What the pinned application was last verified to build and run on.",
        "#",
        "# Written by infra/bench_setup.py after a successful verification. No",
        "# machine-specific path appears here: the JDK is located through the",
        "# untracked dotenv, and only the version it reports is recorded.",
        "",
        "schema_version = 1",
        f'verified_on = "{time.strftime("%Y-%m-%d")}"',
        f'commit = "{commit}"',
        "containers = false",
        "# Containers are prohibited on the experiment machine, so the stack runs as",
        "# folder-local JVM processes started by infra/stack.py.",
        f'runner = "{locks.target()["build"]["up_command"]}"',
        "",
        "[toolchain]",
        f"jdk_major = {details['jdk_major']}",
        f'maven = "{details["maven"]}"',
        'jdk_banner = """',
        details["jdk_banner"],
        '"""',
        "",
        "# Every service the local stack starts, and whether it answered its health",
        "# endpoint at verification. The genai service is excluded: it needs an",
        "# external credential to boot and no change request touches it.",
    ]
    for service in details["services"]:
        lines += [
            "",
            "[[services]]",
            f'name = "{service["name"]}"',
            f"port = {service['port']}",
            f"healthy = {'true' if service['healthy'] else 'false'}",
        ]
    path.write_text("\n".join(lines) + "\n")
    return path


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
    details = verify(checkout, pin["build"])
    record = write_environment_record(details, commit)
    print("\ntarget application builds and starts at the pin")
    print(f"recorded in {record.relative_to(locks.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
