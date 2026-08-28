"""Tests for the pinned target application and the script that fetches it."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from pipelines.common import locks

REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / "infra" / "bench_setup.py"


def test_the_pin_is_an_exact_commit():
    target = locks.target()["target"]
    assert re.fullmatch(r"[0-9a-f]{40}", target["commit"]), "the pin must be a full commit hash"
    assert target["repository"].endswith(".git")
    assert target["name"] == "spring-petclinic-microservices"


def test_the_checkout_is_not_tracked():
    """The application is fetched, never vendored."""
    checkout = locks.target()["target"]["checkout"]
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", f"{checkout}/pom.xml"], cwd=REPO
    )
    assert ignored.returncode == 0, f"{checkout} must be ignored"
    tracked = subprocess.run(
        ["git", "ls-files", checkout], cwd=REPO, capture_output=True, text=True
    ).stdout
    assert tracked == ""


def test_the_lock_names_every_module_the_change_requests_can_touch():
    modules = locks.target()["modules"]
    assert {"customers", "vets", "visits"} <= modules.keys()
    for name, path in modules.items():
        assert path.startswith("spring-petclinic-"), name


def test_module_path_rejects_an_unknown_module():
    assert locks.module_path("visits") == "spring-petclinic-visits-service"
    with pytest.raises(KeyError, match="unknown module"):
        locks.module_path("nonesuch")


def test_the_build_commands_are_the_ones_the_application_documents():
    build = locks.target()["build"]
    assert build["build_command"].startswith("./mvnw")
    assert "buildDocker" in build["build_command"]
    assert build["up_command"].startswith("docker compose")
    assert build["java_version"] == "17"


def test_status_reports_a_mismatch_when_the_checkout_is_absent(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO / "infra"))
    import bench_setup

    monkeypatch.setattr(bench_setup.locks, "target_checkout", lambda: tmp_path / "absent")
    assert bench_setup.main(["--status"]) == 1


def test_setup_help_documents_the_no_verify_switch():
    result = subprocess.run(
        [sys.executable, str(SETUP), "--help"], capture_output=True, text=True, cwd=REPO
    )
    assert result.returncode == 0
    assert "--no-verify" in result.stdout
