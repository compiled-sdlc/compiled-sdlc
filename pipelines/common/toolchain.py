"""The Java toolchain the harness builds and runs the target application with.

The JDK is machine-specific, so its location is read from the untracked dotenv
rather than tracked anywhere. It is passed explicitly to every Maven and Java
subprocess: the ambient PATH is not trusted, because a second, older Java on
the path would change what the experiment compiled against without saying so.
"""

import os
import re
import subprocess
from pathlib import Path

from pipelines.common import locks
from pipelines.common.executor import read_dotenv

JAVA_HOME = "JAVA_HOME"


class ToolchainUnavailable(RuntimeError):
    """No usable JDK is configured."""


def java_home(dotenv: Path | None = None) -> Path:
    """The configured JDK, from the dotenv or the environment."""
    path = dotenv if dotenv is not None else locks.REPO_ROOT / ".env"
    value = read_dotenv(path).get(JAVA_HOME) or os.environ.get(JAVA_HOME, "")
    if not value:
        raise ToolchainUnavailable(
            f"no {JAVA_HOME} in {path.name} at the repository root or in the environment"
        )
    home = Path(value).expanduser()
    if not (home / "bin" / "java").exists():
        raise ToolchainUnavailable(f"{JAVA_HOME} is {home}, which holds no bin/java")
    return home


def version_output(home: Path) -> str:
    """The JDK's own version banner, recorded verbatim in the environment record."""
    reported = subprocess.run(
        [str(home / "bin" / "java"), "-version"], capture_output=True, text=True
    )
    return (reported.stderr or reported.stdout).strip()


def major_version(banner: str) -> int | None:
    """The major version a JDK banner reports."""
    match = re.search(r'version "(\d+)', banner)
    return int(match.group(1)) if match else None


def check(dotenv: Path | None = None) -> tuple[Path, str]:
    """The configured JDK and its banner, or an explanation of why there is none."""
    home = java_home(dotenv)
    banner = version_output(home)
    required = int(locks.target()["build"]["java_version"])
    found = major_version(banner)
    if found is None:
        raise ToolchainUnavailable(f"could not read a version from: {banner.splitlines()[0]}")
    if found < required:
        raise ToolchainUnavailable(
            f"the configured JDK is {found}; the pin needs {required} or newer"
        )
    return home, banner


def environment(home: Path | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """An environment for a build or a service, with the configured JDK in front."""
    home = home or java_home()
    base = dict(os.environ)
    base[JAVA_HOME] = str(home)
    base["PATH"] = f"{home / 'bin'}{os.pathsep}{base.get('PATH', '')}"
    if extra:
        base.update(extra)
    return base
