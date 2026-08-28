"""Access to the pinned experiment configuration.

Three lock files hold everything the experiment is pinned to: the target
application (`bench/target.lock`), the executor and the model behind it
(`bench/executor.lock`), and the prices those tokens are costed at
(`eval/pricing.lock`). They are TOML.

They are also the only tracked files in this repository that name a vendor, a
product, or a credential variable. Everything else reads those strings from
here at runtime and refers to "the pinned executor" and "the pinned model" in
its own text. Keeping the names in one place makes the apparatus auditable —
what the experiment ran on is stated once, in a file whose whole purpose is to
state it — and keeps the repository's own conventions checkable by a plain
string search everywhere else.
"""

import tomllib
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_LOCK = REPO_ROOT / "bench" / "target.lock"
EXECUTOR_LOCK = REPO_ROOT / "bench" / "executor.lock"
PRICING_LOCK = REPO_ROOT / "eval" / "pricing.lock"


def read_lock(path: Path) -> dict:
    """Read one lock file."""
    with path.open("rb") as handle:
        return tomllib.load(handle)


@lru_cache(maxsize=1)
def target() -> dict:
    """The pinned target application."""
    return read_lock(TARGET_LOCK)


@lru_cache(maxsize=1)
def executor() -> dict:
    """The pinned executor, model, and budgets."""
    return read_lock(EXECUTOR_LOCK)


@lru_cache(maxsize=1)
def pricing() -> dict:
    """The captured price table used to cost recorded token counts."""
    return read_lock(PRICING_LOCK)


def target_checkout() -> Path:
    """Where the pinned application is checked out. Not tracked."""
    return REPO_ROOT / target()["target"]["checkout"]


def module_path(module: str) -> str:
    """The target application's directory for one of its modules."""
    modules = target()["modules"]
    if module not in modules:
        known = ", ".join(sorted(modules))
        raise KeyError(f"unknown module {module!r}; the pin defines {known}")
    return modules[module]
