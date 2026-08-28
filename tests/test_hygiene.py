"""Tests for the repository hygiene machinery: ignore rules and the audit script."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "infra" / "audit.sh"

FORBIDDEN_PATHS = [
    "docs/brief.md",
    "manuscript/main.tex",
    "manuscript/references.bib",
    "concept.pdf",
    "concept.docx",
    "slides.pptx",
    "SOMETHING_INSTRUCTIONS.md",
    "PROJECT_BRIEF.md",
    "notes/todo.md",
    "runs/2026-08-27/run.jsonl",
    "figures/salc.pdf",
    "data/results.csv",
    ".env",
    ".DS_Store",
    ".venv/bin/python",
    "eval/__pycache__/salc.pyc",
]

TRACKED_PATHS = [
    "README.md",
    "Makefile",
    "infra/audit.sh",
    "lifecycle-ir/schemas/intent_graph.schema.json",
    "pipelines/common/runner.py",
    "bench/target.lock",
    "figures/.gitkeep",
    "data/.gitkeep",
    "runs/.gitkeep",
]


def is_ignored(path: str) -> bool:
    return (
        subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=REPO).returncode == 0
    )


@pytest.mark.parametrize("path", FORBIDDEN_PATHS)
def test_forbidden_path_is_ignored(path):
    assert is_ignored(path), f"{path} must be ignored"


@pytest.mark.parametrize("path", TRACKED_PATHS)
def test_working_path_is_not_ignored(path):
    assert not is_ignored(path), f"{path} must remain trackable"


def make_repo(tmp_path: Path) -> Path:
    """A minimal clean repository carrying a copy of the audit script."""
    (tmp_path / "infra").mkdir()
    shutil.copy(AUDIT, tmp_path / "infra" / "audit.sh")
    shutil.copy(REPO / ".gitignore", tmp_path / ".gitignore")
    shutil.copy(REPO / "LICENSE", tmp_path / "LICENSE")

    def run(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.name", "Test")
    run("config", "user.email", "test@example.invalid")
    run("add", "-A")
    run("commit", "-q", "-m", "add scaffold")
    return tmp_path


def audit(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repo / "infra" / "audit.sh")], cwd=repo, capture_output=True, text=True
    )


def commit(repo: Path, message: str, *, add: bool = True) -> None:
    if add:
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)


def test_audit_passes_on_a_clean_repository(tmp_path):
    result = audit(make_repo(tmp_path))
    assert result.returncode == 0, result.stdout


def test_audit_detects_attribution_trailer(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "solver.py").write_text("x = 1\n")
    commit(repo, "add solver\n\nCo-Authored" + "-By: A Tool <tool@example.invalid>")
    result = audit(repo)
    assert result.returncode == 1
    assert "FAIL  1." in result.stdout


def test_audit_detects_tool_reference_in_tracked_content(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "solver.py").write_text("# gene" + "rated by a tool\n")
    commit(repo, "add solver")
    result = audit(repo)
    assert result.returncode == 1
    assert "FAIL  2." in result.stdout


def test_audit_detects_forbidden_tracked_file(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "concept.pdf").write_bytes(b"%PDF-1.4\n")
    subprocess.run(["git", "add", "-f", "concept.pdf"], cwd=repo, check=True)
    commit(repo, "add concept document", add=False)
    result = audit(repo)
    assert result.returncode == 1
    assert "FAIL  3." in result.stdout


def test_audit_detects_dirty_tree(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "solver.py").write_text("x = 1\n")
    result = audit(repo)
    assert result.returncode == 1
    assert "FAIL  4." in result.stdout


def test_bulk_add_cannot_capture_forbidden_files(tmp_path):
    repo = make_repo(tmp_path)
    for path in ("docs/brief.md", "manuscript/main.tex", "notes/todo.md"):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("working document\n")
    (repo / "concept.pdf").write_bytes(b"%PDF-1.4\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    tracked = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True
    ).stdout.split()
    assert tracked == []


def test_audit_detects_a_tampered_license(tmp_path):
    """Check 2 excludes LICENSE, so check 5 must catch content smuggled into it."""
    repo = make_repo(tmp_path)
    with (repo / "LICENSE").open("a") as fh:
        fh.write("\n   Note: portions gene" + "rated by a tool.\n")
    commit(repo, "amend license")
    result = audit(repo)
    assert result.returncode == 1
    assert "FAIL  5." in result.stdout


def test_audit_detects_a_missing_license(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "LICENSE").unlink()
    commit(repo, "drop license")
    result = audit(repo)
    assert result.returncode == 1
    assert "FAIL  5." in result.stdout


def test_license_normalises_to_the_canonical_apache_text():
    """The tracked LICENSE differs from upstream only in its copyright line."""
    text = (REPO / "LICENSE").read_text()
    assert "   Copyright 2026 Syed Moid\n" in text
    canonical = text.replace(
        "   Copyright 2026 Syed Moid\n",
        "   Copyright [yyyy] [name of copyright owner]\n",
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    assert digest == "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
