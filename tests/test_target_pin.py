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


def test_the_build_is_the_no_container_one():
    """Containers are prohibited on the experiment machine; the pin's compose path is not used."""
    build = locks.target()["build"]
    assert build["build_command"].startswith("./mvnw")
    assert "buildDocker" not in build["build_command"]
    assert "docker" not in build["up_command"]
    assert "docker" not in build["down_command"]
    assert build["java_version"] == "17"


def test_the_local_stack_starts_the_services_the_experiment_needs():
    services = locks.target()["build"]["services"]
    names = [service["name"] for service in services]
    assert names[0] == "config-server", "configuration has to be up before anything else"
    assert names[1] == "discovery-server"
    assert {"customers-service", "vets-service", "visits-service"} <= set(names)
    assert "genai-service" not in names, "it needs an external credential to boot"
    ports = [service["port"] for service in services]
    assert len(set(ports)) == len(ports), "two services cannot share a port"
    for service in services:
        assert service["health"].startswith("/")
        assert service["wait_seconds"] > 0


def test_the_environment_record_says_what_the_pin_was_verified_on():
    record = locks.read_lock(REPO / "bench" / "environment.lock")
    assert record["commit"] == locks.target()["target"]["commit"]
    assert record["containers"] is False
    assert record["toolchain"]["jdk_major"] >= int(locks.target()["build"]["java_version"])
    assert all(service["healthy"] for service in record["services"])
    assert {service["name"] for service in record["services"]} == {
        service["name"] for service in locks.target()["build"]["services"]
    }


def test_the_environment_record_carries_no_machine_specific_path():
    """Machine paths are never tracked; the JDK is located through the dotenv."""
    text = (REPO / "bench" / "environment.lock").read_text()
    assert "/Users/" not in text and "/home/" not in text


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
