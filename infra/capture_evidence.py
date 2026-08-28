#!/usr/bin/env python3
"""Capture the runtime evidence the incident change requests carry as input.

An incident change request that states its defect only in prose asks the agent
to take the author's word for it, and the incident-to-intent step the protocol
is about never happens. A real one arrives with what was observed: the requests
that were made, what came back, how long it took, and what the service logged.

This script reproduces each incident against the running pinned stack and
writes what it saw under `bench/evidence/<change request>/`. That evidence is
*input*: every arm renders it, the agent reads it, and none of it names a hidden
check or an invariant. This script writes it, never a human hand, so it cannot
drift from what the pinned application actually does.

    make stack-start
    uv run python infra/capture_evidence.py [--change-request CR-105 ...]

One capture (CR-117) stops the visits service on purpose and starts it again
afterwards, because the behaviour under evidence is what the gateway does when
that service is gone.
"""

import argparse
import contextlib
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import infra.stack as stack  # noqa: E402
from pipelines.common import locks, toolchain  # noqa: E402

EVIDENCE = locks.REPO_ROOT / "bench" / "evidence"

#: Long enough for service discovery to propagate, which health does not cover.
DISCOVERY_SECONDS = 60

GATEWAY = "http://localhost:8080"
CUSTOMERS = "http://localhost:8081"
VISITS = "http://localhost:8082"


class StackUnavailable(RuntimeError):
    """The pinned stack is not answering, so nothing can be observed."""


# --- observing --------------------------------------------------------------


def call(method: str, url: str, body: str | None = None, timeout: float = 30.0) -> dict:
    """Make one request and record everything about what happened."""
    data = body.encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, payload = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read().decode()
    except urllib.error.URLError as error:
        status, payload = 0, f"the request did not complete: {error.reason}"
    return {
        "method": method,
        "url": url,
        "request_body": body,
        "status": status,
        "body": payload,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        "request_line_bytes": len(f"{method} {url} HTTP/1.1"),
    }


def shorten(url: str, keep: int = 8) -> str:
    """A long identifier list, shown as its first few and a count.

    The evidence is read by an agent with a token budget, and a thousand
    comma-separated integers say nothing that "a thousand of them" does not.
    """
    head, separator, query = url.partition("?petId=")
    identifiers = query.split(",") if separator else []
    if len(identifiers) <= keep:
        return url
    shown = ",".join(identifiers[:keep])
    return f"{head}?petId={shown},... [{len(identifiers)} identifiers in all]"


def transcript(observations: list[dict]) -> str:
    """The observations as something a person reads."""
    lines = []
    for observed in observations:
        lines.append(f"$ {observed['method']} {shorten(observed['url'])}")
        if observed["request_body"]:
            lines.append(f"  body: {observed['request_body']}")
        lines.append(
            f"  -> {observed['status']} in {observed['elapsed_ms']} ms"
            f"  (request line {observed['request_line_bytes']} bytes)"
        )
        body = observed["body"]
        shown = body if len(body) <= 600 else body[:600] + f"... [{len(body)} bytes total]"
        lines.append(f"  {shown}")
        lines.append("")
    return "\n".join(lines)


def log_excerpt(service: str, lines: int, matching: str | None = None) -> str:
    """The tail of one service's log, optionally only the lines that matter."""
    log = stack.runtime_directory() / f"{service}.log"
    if not log.exists():
        return f"(no log for {service})"
    content = log.read_text().splitlines()
    if matching:
        content = [line for line in content if matching in line]
    return "\n".join(content[-lines:])


def write(change_request: str, name: str, content: str) -> str:
    """Write one evidence artifact and report its path from the repository root."""
    directory = EVIDENCE / change_request
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(content.rstrip("\n") + "\n")
    return str(path.relative_to(locks.REPO_ROOT))


def record(change_request: str, artifacts: list[str], how: list[str], note: str) -> None:
    """What was captured, from what, and how to capture it again."""
    _, banner = toolchain.check()
    payload = {
        "change_request": change_request,
        "captured_on": time.strftime("%Y-%m-%d"),
        "pin_commit": locks.target()["target"]["commit"],
        "java_version": banner.splitlines()[0],
        "services": [service.name for service in stack.services()],
        "reproduced_by": how,
        "note": note,
        "artifacts": artifacts,
    }
    directory = EVIDENCE / change_request
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "capture.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


# --- the stack --------------------------------------------------------------


def require_stack(urls: list[str]) -> None:
    for url in urls:
        healthy, detail = stack.probe(url)
        if not healthy:
            raise StackUnavailable(f"{url} is not answering: {detail[:200]}")


def wait_until(check, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(2.0)
    return False


def stop_one(name: str) -> None:
    """Stop a single service, leaving the rest of the stack up."""
    pid_file = stack.runtime_directory() / f"{name}.pid"
    if not pid_file.exists():
        raise StackUnavailable(f"no pid file for {name}; is the stack running?")
    pid = int(pid_file.read_text().strip())
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    for _ in range(40):
        if not stack.alive(pid):
            break
        time.sleep(0.5)
    if stack.alive(pid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    pid_file.unlink(missing_ok=True)


def seed_a_visit(pet_id: int, description: str) -> dict:
    """Give a pet something to have, so an empty answer means something.

    Idempotent: a pet that already has a visit is left alone, so capturing the
    evidence twice against one stack does not pile visits up in it.
    """
    existing = call("GET", f"{VISITS}/owners/1/pets/{pet_id}/visits")
    if existing["status"] == 200 and existing["body"].strip() not in ("[]", ""):
        return existing
    created = call(
        "POST", f"{VISITS}/owners/1/pets/{pet_id}/visits", json.dumps({"description": description})
    )
    # The evidence says this pet has a visit, so refuse to write evidence unless it
    # actually does: a capture against the wrong state is worse than no capture.
    confirmed = call("GET", f"{VISITS}/owners/1/pets/{pet_id}/visits")
    if confirmed["status"] != 200 or confirmed["body"].strip() in ("[]", ""):
        raise StackUnavailable(
            f"pet {pet_id} still has no visit after one was placed "
            f"(create said {created['status']}, read back {confirmed['status']}: "
            f"{confirmed['body'][:200]})"
        )
    return confirmed


# --- the incidents ----------------------------------------------------------


def capture_105() -> None:
    """CR-105: the batch lookup takes as many pets as anyone cares to name."""
    require_stack([f"{VISITS}/actuator/health"])

    modest = ",".join(str(identifier) for identifier in range(1, 11))
    large = ",".join(str(identifier) for identifier in range(1, 1001))
    call("GET", f"{VISITS}/pets/visits?petId={modest}")  # warm the endpoint first
    observations = [
        call("GET", f"{VISITS}/pets/visits?petId={modest}"),
        call("GET", f"{VISITS}/pets/visits?petId={large}"),
    ]

    artifacts = [
        write(
            "CR-105",
            "batch-lookup.txt",
            "Observed against the pinned stack, visits service on 8082.\n\n"
            "A lookup naming ten pets and a lookup naming a thousand are both\n"
            "accepted. Nothing refuses the second one, and the request line it\n"
            "needs is the size shown below.\n\n" + transcript(observations),
        ),
        write(
            "CR-105",
            "visits-service.log",
            "Tail of the visits service log across both lookups.\n\n"
            + log_excerpt("visits-service", 25),
        ),
    ]
    record(
        "CR-105",
        artifacts,
        [
            "GET /pets/visits?petId=<ten identifiers> against the visits service",
            "GET /pets/visits?petId=<one thousand identifiers> against the visits service",
        ],
        "Both lookups are accepted; the larger one is neither refused nor bounded.",
    )


def capture_114() -> None:
    """CR-114: the same pet named many times is asked for many times."""
    require_stack([f"{VISITS}/actuator/health"])

    once = "7"
    repeated = ",".join(["7"] * 500)
    call("GET", f"{VISITS}/pets/visits?petId={once}")  # warm the endpoint first
    observations = [
        call("GET", f"{VISITS}/pets/visits?petId={once}"),
        call("GET", f"{VISITS}/pets/visits?petId={repeated}"),
        call("GET", f"{VISITS}/pets/visits?petId=7,7,8,8,7"),
    ]

    artifacts = [
        write(
            "CR-114",
            "repeated-identifiers.txt",
            "Observed against the pinned stack, visits service on 8082.\n\n"
            "The same pet named once, named five hundred times, and named in a\n"
            "mixed list. The answers carry the same visits; the work of asking\n"
            "for them does not.\n\n" + transcript(observations),
        ),
        write(
            "CR-114",
            "visits-service.log",
            "Tail of the visits service log across the three lookups.\n\n"
            + log_excerpt("visits-service", 25),
        ),
    ]
    record(
        "CR-114",
        artifacts,
        [
            "GET /pets/visits?petId=7 against the visits service",
            "GET /pets/visits?petId=<the identifier 7, five hundred times>",
            "GET /pets/visits?petId=7,7,8,8,7",
        ],
        "A repeated identifier is carried into the lookup rather than collapsed before it.",
    )


def capture_117() -> None:
    """CR-117: a degraded answer and a true empty answer look alike."""
    require_stack([f"{GATEWAY}/actuator/health", f"{VISITS}/actuator/health"])
    seed_a_visit(1, "annual check-up")

    def gateway_ready() -> bool:
        return call("GET", f"{GATEWAY}/api/gateway/owners/1")["status"] == 200

    if not wait_until(gateway_ready, DISCOVERY_SECONDS):
        raise StackUnavailable(
            "the gateway does not resolve the customers service; service discovery "
            "has not propagated yet"
        )

    call("GET", f"{GATEWAY}/api/gateway/owners/1")  # warm the endpoint first
    healthy = [
        call("GET", f"{GATEWAY}/api/gateway/owners/1"),
        call("GET", f"{GATEWAY}/api/gateway/owners/2"),
    ]

    stop_one("visits-service")
    try:
        degraded = [call("GET", f"{GATEWAY}/api/gateway/owners/1")]
        fallback_log = log_excerpt("api-gateway", 12, matching="visits-service")
    finally:
        stack.start(only=["visits-service"])
        wait_until(gateway_ready, DISCOVERY_SECONDS)

    artifacts = [
        write(
            "CR-117",
            "healthy.txt",
            "Observed against the pinned stack, gateway on 8080, everything up.\n\n"
            "Owner 1 has a visit. Owner 2 has a pet and no visits at all.\n\n"
            + transcript(healthy),
        ),
        write(
            "CR-117",
            "visits-service-down.txt",
            "Observed against the pinned stack with the visits service stopped.\n\n"
            "The same request for owner 1, whose pet does have a visit. The answer\n"
            "is 200 and the visits are empty --- the same answer, field for field,\n"
            "that owner 2 gets when the visits really are empty. Nothing in the\n"
            "response says which of the two happened.\n\n" + transcript(degraded),
        ),
        write(
            "CR-117",
            "api-gateway.log",
            "Gateway log lines naming the visits service while it was stopped.\n\n"
            + (fallback_log or "(the gateway logged nothing naming the visits service)"),
        ),
    ]
    record(
        "CR-117",
        artifacts,
        [
            "GET /api/gateway/owners/1 and /owners/2 with the whole stack up",
            "stop the visits service, leaving the rest of the stack running",
            "GET /api/gateway/owners/1 again",
            "start the visits service",
        ],
        "The degraded answer and the true empty answer are identical to a caller.",
    )


CAPTURES = {"CR-105": capture_105, "CR-114": capture_114, "CR-117": capture_117}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change-request", action="append", help="repeatable; default all")
    arguments = parser.parse_args(argv)

    wanted = arguments.change_request or sorted(CAPTURES)
    unknown = [identifier for identifier in wanted if identifier not in CAPTURES]
    if unknown:
        print(f"no evidence capture for {', '.join(unknown)}", file=sys.stderr)
        return 2

    for identifier in wanted:
        print(f"capturing {identifier}", flush=True)
        try:
            CAPTURES[identifier]()
        except StackUnavailable as error:
            print(f"  cannot capture: {error}", file=sys.stderr)
            print("  start the stack first: make stack-start", file=sys.stderr)
            return 1
        print(f"  written to bench/evidence/{identifier}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
