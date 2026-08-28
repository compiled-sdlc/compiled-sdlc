"""Test configuration.

The IR validator lives under lifecycle-ir/, whose name is not a legal Python
package name, so its implementation package is put on the path here rather than
installed.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lifecycle-ir"))
sys.path.insert(0, str(REPO))


import subprocess  # noqa: E402

import pytest  # noqa: E402

from pipelines.common import locks  # noqa: E402


@pytest.fixture(autouse=True)
def never_bill(monkeypatch):
    """No test may launch the real executor.

    Tests drive a stand-in that emits the same event stream. A test that reaches
    the pinned binary would spend the owner's balance every time the suite runs,
    so reaching it is made an error rather than a surprise on the invoice.
    """
    binary = locks.executor()["cli"]["binary"]
    real = subprocess.Popen

    def guarded(command, *args, **kwargs):
        first = command[0] if isinstance(command, (list, tuple)) and command else command
        if str(first).rsplit("/", 1)[-1] == binary:
            raise AssertionError(
                "a test tried to launch the pinned executor; use the stand-in instead"
            )
        return real(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded)
