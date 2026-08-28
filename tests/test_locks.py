"""Tests for the pinned executor and price table, and for vendor-string confinement."""

import re
import subprocess
from pathlib import Path

import pytest

from pipelines.common import locks

REPO = Path(__file__).resolve().parents[1]


def audit_pattern(name: str) -> str:
    """One of the audit script's own patterns.

    Read from infra/audit.sh rather than restated here: the audit is the
    authority on what may not appear in tracked content, this file must not
    contain those strings itself, and a copy would drift.
    """
    text = (REPO / "infra" / "audit.sh").read_text()
    match = re.search(rf"^{name}='(.+)'$", text, re.MULTILINE)
    assert match, f"infra/audit.sh no longer defines {name}"
    return match.group(1).replace("'", "")


VENDOR_PATTERN = audit_pattern("tool_names")


def tracked(*paths: str) -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", *paths], cwd=REPO, capture_output=True, text=True, check=True
    )
    return listing.stdout.split()


def test_the_executor_is_pinned_exactly():
    cli = locks.executor()["cli"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", cli["version"])
    assert cli["version"] == cli["npm_version"], "the binary and the package must be one version"
    assert cli["verified_on"]


def test_the_model_is_pinned_and_priced():
    executor = locks.executor()
    prices = locks.pricing()["models"]
    for identifier in (executor["model"]["id"], executor["model"]["debug"]["id"]):
        assert identifier in prices, f"{identifier} has no price"
        rates = prices[identifier]
        assert rates["input"] > 0 and rates["output"] > rates["input"]
        assert rates["cache_read"] < rates["input"] < rates["cache_write_5m"]


def test_the_price_table_states_when_it_was_captured():
    pricing = locks.pricing()
    assert pricing["currency"] == "USD"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", pricing["captured_on"])
    assert pricing["reasoning_tokens_billed_as"] == "output"


def test_the_budgets_are_present_and_finite():
    budget = locks.executor()["budget"]
    assert budget["max_turns"] > 0
    assert budget["wall_clock_seconds"] > 0
    assert budget["max_cost_usd"] > 0


def test_the_tool_set_excludes_research_and_delegation_tools():
    """An agent that can search the web or spawn subagents is not a measurable arm."""
    tools = set(locks.executor()["invocation"]["tools"])
    assert {"Bash", "Read", "Write", "Edit"} <= tools
    assert not any(tool.lower().startswith(("web", "task", "agent")) for tool in tools)


@pytest.mark.parametrize("area", ["pipelines", "eval", "bench", "infra", "tests", "lifecycle-ir"])
def test_no_vendor_string_outside_the_lock_files(area):
    """The apparatus names its vendor once, in the lock files, and nowhere else."""
    everything = tracked(area)
    assert everything, f"{area} has no tracked files"
    files = [path for path in everything if not path.endswith(".lock")]
    if not files:
        return
    found = subprocess.run(
        ["git", "grep", "-ilE", VENDOR_PATTERN, "--", *files],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert found.stdout == "", f"vendor strings outside the lock files: {found.stdout}"


def test_the_lock_files_are_tracked_and_are_the_only_exception():
    lock_files = tracked("*.lock")
    assert set(lock_files) >= {"bench/executor.lock", "bench/target.lock", "eval/pricing.lock"}
    named = subprocess.run(
        ["git", "grep", "-lE", VENDOR_PATTERN, "--", "*.lock"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert set(named) <= {"bench/executor.lock", "eval/pricing.lock", "uv.lock"}


def test_the_credential_variable_is_named_only_in_the_lock():
    """The key's variable name is configuration, not something code spells out."""
    variable = locks.executor()["credentials"]["variable"]
    files = [path for path in tracked() if not path.endswith(".lock")]
    found = subprocess.run(
        ["git", "grep", "-lF", variable, "--", *files], cwd=REPO, capture_output=True, text=True
    )
    assert found.stdout == ""
