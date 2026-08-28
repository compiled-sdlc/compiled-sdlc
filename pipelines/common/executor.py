"""Headless invocation of the pinned executor.

One call runs one agent, in one workspace, under one budget, and returns what it
spent. The full event stream is captured to the cell's directory as it arrives,
so a run that is killed still leaves evidence behind.

Three budgets apply. The cost ceiling is passed to the executor, which enforces
it itself. The turn cap and the wall clock are enforced here, by watching the
stream and killing the process group when either is reached. A budget stop is
recorded as `budget_exhausted`, which is a decision of the harness; an API
failure is recorded as `aborted` with the class of failure, which is a fault of
the apparatus; neither is an agent failure, and the metrics never treat them as
one.

The credential is read from the untracked dotenv, passed to the executor process
in its environment, and never written into the workspace. Anything the executor
writes to the transcript or to standard error is scrubbed of it first: the agent
has a shell, so the guarantee has to hold over what the agent does, not only
over what the harness does.
"""

import json
import os
import re
import select
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from pipelines.common import locks
from pipelines.common.telemetry import Usage

REDACTION = "[redacted]"
POLL_SECONDS = 0.5
KILL_GRACE_SECONDS = 10

# Ordered: the first pattern that matches the executor's own error text names the
# failure. Both the wire status and the wording are matched, because an executor
# may report either.
API_ERROR_SIGNALS: tuple[tuple[str, str], ...] = (
    (r"\b402\b|credit balance|insufficient (credit|funds|balance)|billing", "credit_exhausted"),
    (r"\b429\b|rate[ _-]?limit|too many requests", "rate_limit"),
    (r"\b529\b|overloaded", "overloaded"),
    (r"\b401\b|\b403\b|invalid .{0,20}key|unauthorized|authentication", "auth"),
    (r"\b5\d\d\b|econnreset|enotfound|etimedout|socket hang up|fetch failed|network", "network"),
)


class ExecutorUnavailable(RuntimeError):
    """The pinned executor or its credential is not usable on this machine."""


@dataclass
class Budget:
    """The three ceilings every cell runs under, identical across arms."""

    max_turns: int
    wall_clock_seconds: float
    max_cost_usd: float

    @classmethod
    def pinned(cls) -> "Budget":
        budget = locks.executor()["budget"]
        return cls(
            max_turns=int(budget["max_turns"]),
            wall_clock_seconds=float(budget["wall_clock_seconds"]),
            max_cost_usd=float(budget["max_cost_usd"]),
        )


@dataclass
class Execution:
    """What one invocation spent and how it ended."""

    status: str
    error_class: str | None = None
    error_detail: str = ""
    usage: Usage = field(default_factory=Usage)
    turns: int = 0
    tool_calls: dict = field(default_factory=lambda: {"total": 0, "by_name": {}})
    retries: int = 0
    permission_denials: int = 0
    wall_time_seconds: float = 0.0
    api_time_seconds: float = 0.0
    executor_reported_cost_usd: float | None = None
    response: dict = field(default_factory=dict)
    per_model_usage: dict = field(default_factory=dict)
    exit_code: int | None = None


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse a dotenv file. Values are not logged, only passed on."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def credential(dotenv: Path | None = None) -> tuple[str, str]:
    """The credential variable's name and value, from the dotenv or the environment."""
    settings = locks.executor()["credentials"]
    variable = settings["variable"]
    path = dotenv if dotenv is not None else locks.REPO_ROOT / settings["dotenv"]
    value = read_dotenv(path).get(variable) or os.environ.get(variable, "")
    if not value:
        raise ExecutorUnavailable(
            f"no credential: set it in {path.name} at the repository root, or in the environment"
        )
    return variable, value


def redact(text: str, secrets: list[str]) -> str:
    """Remove credentials from anything about to be written to disk."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTION)
    return text


def build_command(prompt: str, model: str, budget: Budget, invocation: dict) -> list[str]:
    """The exact argument list, built from the pinned invocation profile."""
    command = [
        locks.executor()["cli"]["binary"],
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        invocation["output_format"],
        "--permission-mode",
        invocation["permission_mode"],
        "--max-budget-usd",
        f"{budget.max_cost_usd:g}",
        "--setting-sources",
        invocation.get("setting_sources", ""),
    ]
    tools = invocation.get("tools")
    if tools:
        command += ["--tools", ",".join(tools)]
    command += list(invocation.get("extra_flags", []))
    return command


def classify_error(text: str) -> str | None:
    """The class of API failure the executor reported, if it reported one."""
    lowered = text.lower()
    for pattern, name in API_ERROR_SIGNALS:
        if re.search(pattern, lowered):
            return name
    return None


class StreamState:
    """Running totals taken from the event stream as it arrives."""

    def __init__(self) -> None:
        self.turn_ids: set[str] = set()
        self.tool_calls: dict[str, int] = {}
        self.retries = 0
        self.permission_denials = 0
        self.usage = Usage()
        self.result: dict | None = None
        self.model_usage: dict[str, dict] = {}
        self.per_model: dict[str, Usage] = {}
        self.session_id: str | None = None
        self.errors: list[str] = []

    @property
    def turns(self) -> int:
        return len(self.turn_ids)

    def observe(self, event: dict) -> None:
        kind = event.get("type")
        if event.get("session_id") and not self.session_id:
            self.session_id = event["session_id"]
        if kind == "assistant":
            message = event.get("message") or {}
            identifier = message.get("id")
            self.turn_ids.add(identifier or f"turn-{len(self.turn_ids) + 1}")
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "unknown")
                    self.tool_calls[name] = self.tool_calls.get(name, 0) + 1
        elif kind == "system":
            subtype = str(event.get("subtype", ""))
            if "retry" in subtype or "retrying" in subtype:
                self.retries += 1
            if event.get("api_error_status"):
                self.errors.append(str(event["api_error_status"]))
        elif kind == "result":
            self.result = event

    def finish(self) -> None:
        """Fold the terminal event into the totals.

        The per-model breakdown is the authority for what was spent, not the
        top-level usage block: the executor makes calls that never surface as
        turns in the stream, and the top-level output count omits them. The two
        agree on the cache figures and disagree on the rest, and only the
        breakdown reproduces the cost the executor reports for itself.

        The lifetime split of the cache-creation tokens and the reasoning-token
        count exist only in the top-level block, so they are taken from there
        and scaled to nothing: they are a breakdown of the totals, not an
        addition to them.
        """
        result = self.result or {}
        usage = result.get("usage") or {}
        details = usage.get("output_tokens_details") or {}
        creation = usage.get("cache_creation") or {}
        iterations = usage.get("iterations") or []
        self.model_usage = {
            model: spent
            for model, spent in (result.get("modelUsage") or {}).items()
            if isinstance(spent, dict)
        }

        creation_total = sum(
            int(spent.get("cacheCreationInputTokens", 0) or 0)
            for spent in self.model_usage.values()
        )
        long_lived = int(creation.get("ephemeral_1h_input_tokens", 0) or 0)

        def per_model_usage(spent: dict) -> Usage:
            """One model's share. The cache lifetime split is reported for the
            cell as a whole, so it is distributed in proportion to each model's
            share of the cache creation; when nothing was written to the longer
            cache, which is the usual case, the distribution is exact."""
            created = int(spent.get("cacheCreationInputTokens", 0) or 0)
            share = (created / creation_total) if creation_total else 0.0
            hour = min(round(long_lived * share), created)
            return Usage(
                input_tokens=int(spent.get("inputTokens", 0) or 0),
                output_tokens=int(spent.get("outputTokens", 0) or 0),
                cache_creation_input_tokens=created,
                cache_read_input_tokens=int(spent.get("cacheReadInputTokens", 0) or 0),
                cache_creation_5m_tokens=created - hour,
                cache_creation_1h_tokens=hour,
            )

        self.per_model = {
            model: per_model_usage(spent) for model, spent in self.model_usage.items()
        }

        def summed(field: str, fallback: str) -> int:
            if self.model_usage:
                return sum(int(spent.get(field, 0) or 0) for spent in self.model_usage.values())
            return int(usage.get(fallback, 0) or 0)

        cache_creation = summed("cacheCreationInputTokens", "cache_creation_input_tokens")
        split_5m = int(creation.get("ephemeral_5m_input_tokens", 0) or 0)
        split_1h = int(creation.get("ephemeral_1h_input_tokens", 0) or 0)
        if split_5m + split_1h > cache_creation:
            split_5m, split_1h = cache_creation, 0
        self.usage = Usage(
            input_tokens=summed("inputTokens", "input_tokens"),
            output_tokens=summed("outputTokens", "output_tokens"),
            reasoning_tokens=int(details.get("thinking_tokens", 0) or 0),
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=summed("cacheReadInputTokens", "cache_read_input_tokens"),
            cache_creation_5m_tokens=split_5m,
            cache_creation_1h_tokens=split_1h,
            api_calls=len(iterations),
        )
        if result.get("api_error_status"):
            self.errors.append(str(result["api_error_status"]))
        if isinstance(result.get("result"), str) and result.get("is_error"):
            self.errors.append(result["result"])
        self.permission_denials = len(result.get("permission_denials") or [])


def _terminate(process: subprocess.Popen) -> None:
    """Stop the executor and everything it started."""
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.wait(timeout=KILL_GRACE_SECONDS)


def execute(
    prompt: str,
    workspace: Path,
    cell_directory: Path,
    *,
    model: str | None = None,
    budget: Budget | None = None,
    home: Path | None = None,
    dotenv: Path | None = None,
    command: list[str] | None = None,
) -> Execution:
    """Run one agent in one workspace and return what it spent.

    `command` overrides the built argument list; it exists so the harness itself
    can be tested against a stand-in executor without spending anything.
    """
    settings = locks.executor()
    model = model or settings["model"]["id"]
    budget = budget or Budget.pinned()
    variable, secret = credential(dotenv)

    if command is None:
        command = build_command(prompt, model, budget, settings["invocation"])
        if shutil.which(command[0]) is None:
            raise ExecutorUnavailable(f"the pinned executor {command[0]!r} is not on PATH")

    cell_directory.mkdir(parents=True, exist_ok=True)
    transcript = cell_directory / "transcript.jsonl"
    stderr_path = cell_directory / "stderr.txt"
    home = home or cell_directory / "home"
    home.mkdir(parents=True, exist_ok=True)

    # A deliberately small environment: the credential, a home of its own so no
    # host configuration leaks in, and the little else a shell needs.
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "TERM": "dumb",
        "CI": "1",
        variable: secret,
    }
    for passthrough in ("JAVA_HOME", "MAVEN_OPTS", "TMPDIR", "SSL_CERT_FILE"):
        if passthrough in os.environ:
            environment[passthrough] = os.environ[passthrough]

    state = StreamState()
    started = time.monotonic()
    deadline = started + budget.wall_clock_seconds
    status, error_class, error_detail = "completed", None, ""

    process = subprocess.Popen(  # noqa: S603 - the command comes from the pinned lock file
        command,
        cwd=workspace,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    def handle(line: str, sink) -> bool:
        """Record one event. Returns False when a budget has been reached."""
        sink.write(redact(line, [secret]))
        sink.flush()
        stripped = line.strip()
        if not stripped:
            return True
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            return True
        state.observe(event)
        return state.turns <= budget.max_turns

    with transcript.open("w") as sink:
        while True:
            if time.monotonic() > deadline:
                _terminate(process)
                status, error_class = "aborted", "timeout"
                error_detail = f"no result within {budget.wall_clock_seconds:g}s"
                break
            ready, _, _ = select.select([process.stdout], [], [], POLL_SECONDS)
            if ready:
                line = process.stdout.readline()
                if line == "":
                    break
                if not handle(line, sink):
                    _terminate(process)
                    status, error_class = "budget_exhausted", "turn_budget"
                    error_detail = f"reached the cap of {budget.max_turns} turns"
                    break
            elif process.poll() is not None:
                break
        if status == "completed":
            for line in process.stdout:
                handle(line, sink)

    stderr_text = redact(process.stderr.read() or "", [secret])
    stderr_path.write_text(stderr_text)
    process.stdout.close()
    process.stderr.close()
    try:
        exit_code = process.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate(process)
        exit_code = process.returncode
    state.finish()

    result = state.result or {}
    wall_time = time.monotonic() - started

    if status == "completed":
        reported = "\n".join(state.errors + [stderr_text])
        failure = classify_error(reported) if reported.strip() else None
        if failure:
            status, error_class = "aborted", failure
            error_detail = redact(reported.strip()[:500], [secret])
        elif state.result is None:
            status, error_class = "aborted", "executor_crash"
            error_detail = f"the executor ended without a result (exit {exit_code})"
        elif result.get("is_error") or exit_code not in (0, None):
            status, error_class = "agent_failed", None
            detail = result.get("result") or f"exit {exit_code}"
            error_detail = redact(str(detail)[:500], [secret])
        elif str(result.get("subtype", "")).startswith("error"):
            status, error_class = "agent_failed", None
            error_detail = str(result.get("subtype"))

    return Execution(
        status=status,
        error_class=error_class,
        error_detail=error_detail,
        usage=state.usage,
        turns=int(result.get("num_turns") or state.turns),
        tool_calls={"total": sum(state.tool_calls.values()), "by_name": dict(state.tool_calls)},
        retries=state.retries,
        permission_denials=state.permission_denials,
        wall_time_seconds=round(wall_time, 3),
        api_time_seconds=round(float(result.get("duration_api_ms") or 0) / 1000, 3),
        executor_reported_cost_usd=result.get("total_cost_usd"),
        per_model_usage=dict(state.per_model),
        response={
            "model": model,
            "finish_reason": result.get("stop_reason"),
            "terminal_reason": result.get("terminal_reason"),
            "session_id": state.session_id,
            "models_used": sorted(state.model_usage),
        },
        exit_code=exit_code,
    )
