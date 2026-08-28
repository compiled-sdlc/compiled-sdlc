"""Tests for the folder-local stack runner and the Java toolchain it uses."""

import sys
from pathlib import Path

import pytest

from pipelines.common import locks, toolchain

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra"))

import stack  # noqa: E402  - the runner is a script, not a package


def test_the_configured_toolchain_satisfies_the_pin():
    home, banner = toolchain.check()
    assert (home / "bin" / "java").exists()
    assert toolchain.major_version(banner) >= int(locks.target()["build"]["java_version"])


def test_a_missing_toolchain_is_reported_rather_than_guessed(tmp_path, monkeypatch):
    monkeypatch.delenv(toolchain.JAVA_HOME, raising=False)
    with pytest.raises(toolchain.ToolchainUnavailable, match="JAVA_HOME"):
        toolchain.java_home(tmp_path / "absent-dotenv")


def test_a_toolchain_pointing_at_nothing_is_reported(tmp_path):
    dotenv = tmp_path / "dotenv"
    dotenv.write_text(f"{toolchain.JAVA_HOME}={tmp_path / 'not-a-jdk'}\n")
    with pytest.raises(toolchain.ToolchainUnavailable, match="no bin/java"):
        toolchain.java_home(dotenv)


def test_the_configured_toolchain_leads_the_path():
    """A second, older Java on the path must not decide what the experiment compiles against."""
    home = toolchain.java_home()
    environment = toolchain.environment(home)
    assert environment[toolchain.JAVA_HOME] == str(home)
    assert environment["PATH"].startswith(str(home / "bin"))


def test_the_version_banner_parses():
    assert toolchain.major_version('java version "21.0.7" 2025-04-15 LTS') == 21
    assert toolchain.major_version('openjdk version "17.0.9" 2023-10-17') == 17
    assert toolchain.major_version("nothing version-like") is None


# --- the runner ------------------------------------------------------------


def test_the_services_start_in_dependency_order():
    names = [service.name for service in stack.services()]
    assert names.index("config-server") == 0
    assert names.index("discovery-server") < names.index("customers-service")
    assert names.index("api-gateway") == len(names) - 1


def test_each_service_knows_where_its_jar_is():
    checkout = locks.target_checkout()
    version = locks.target()["build"]["version"]
    for service in stack.services():
        jar = service.jar(checkout, version)
        assert jar.name.endswith(f"-{version}.jar")
        assert jar.parent.name == "target"
        assert locks.module_path(service.module) in str(jar)


def test_the_runtime_directory_is_not_tracked():
    """Pid files and logs are run state, not repository content."""
    directory = locks.target()["build"]["runtime_directory"]
    assert directory.startswith("runs/")
    tracked = stack.subprocess.run(
        ["git", "ls-files", directory], cwd=REPO, capture_output=True, text=True
    ).stdout
    assert tracked == ""


def test_health_urls_are_local_and_per_service():
    urls = {service.health_url for service in stack.services()}
    assert len(urls) == len(stack.services())
    assert all(url.startswith("http://localhost:") for url in urls)


def test_a_dead_process_is_not_reported_as_alive():
    assert stack.alive(1) in (True, False)  # pid 1 exists but may not be signalable
    assert not stack.alive(2**31 - 1)


def test_probing_a_closed_port_fails_cleanly():
    healthy, detail = stack.probe("http://localhost:1/health")
    assert healthy is False
    assert detail
