"""The workspace one run works in.

Every run gets a fresh checkout of the target application at its pin, made as a
git worktree of the local clone: the agent gets a clean tree it can do anything
to, and the harness gets a cheap, exact answer to "what did it change" without
copying the application for every cell.

Nothing from this repository is placed in a workspace. The hidden acceptance
checks go in only after the agent has finished, and come out again straight
after.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pipelines.common import locks

WORKSPACE_NAME = "workspace"

# Where an arm writes the artifacts it hands the agent. They sit inside the
# workspace because the agent has to read them, but they are the arm's input,
# not the run's output, and the diff has to tell the two apart: an arm that
# hands over six files has not thereby changed the application six times.
ARTIFACT_DIRECTORY = "change-request"


class WorkspaceError(RuntimeError):
    """A workspace could not be prepared."""


def git(*arguments: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True, check=False)


@dataclass
class Changes:
    """What a run did to the application, and what its arm put there.

    The counts describe the application only. The artifacts an arm placed are
    listed separately so nothing is lost, and so a comparison between arms is a
    comparison of what they changed rather than of what they were given.
    """

    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    changed_paths: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()

    def touched(self, prefix: str) -> list[str]:
        return [path for path in self.changed_paths if path.startswith(prefix)]

    def to_dict(self) -> dict:
        return {
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "changed_paths": list(self.changed_paths),
            "artifact_paths": list(self.artifact_paths),
        }


def create(cell_directory: Path, checkout: Path | None = None, commit: str | None = None) -> Path:
    """A fresh worktree of the pin, for one run."""
    checkout = checkout or locks.target_checkout()
    commit = commit or locks.target()["target"]["commit"]
    if not (checkout / ".git").exists():
        raise WorkspaceError(f"no target checkout at {checkout}; run make bench-setup first")
    workspace = cell_directory / WORKSPACE_NAME
    if workspace.exists():
        remove(workspace, checkout)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    added = git("worktree", "add", "--detach", "--force", str(workspace), commit, cwd=checkout)
    if added.returncode != 0:
        raise WorkspaceError(f"could not create a workspace at {workspace}: {added.stderr.strip()}")
    return workspace


def remove(workspace: Path, checkout: Path | None = None) -> None:
    """Discard a workspace and the worktree registration behind it."""
    checkout = checkout or locks.target_checkout()
    if (checkout / ".git").exists():
        git("worktree", "remove", "--force", str(workspace), cwd=checkout)
        git("worktree", "prune", cwd=checkout)
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)


def changes(workspace: Path) -> Changes:
    """Everything the run altered, added or removed, against the pin.

    Untracked files count: an agent that adds a file has changed the
    application as much as one that edits it.
    """
    git("add", "-A", cwd=workspace)
    numstat = git("diff", "--cached", "--numstat", cwd=workspace).stdout
    insertions = deletions = 0
    paths: list[str] = []
    artifacts: list[str] = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        if path.startswith(f"{ARTIFACT_DIRECTORY}/"):
            artifacts.append(path)
            continue
        insertions += int(added) if added.isdigit() else 0
        deletions += int(removed) if removed.isdigit() else 0
        paths.append(path)
    return Changes(
        files_changed=len(paths),
        insertions=insertions,
        deletions=deletions,
        changed_paths=tuple(sorted(paths)),
        artifact_paths=tuple(sorted(artifacts)),
    )


def content_at_pin(
    path: str, checkout: Path | None = None, commit: str | None = None
) -> str | None:
    """A file as the pin has it, or None if the pin does not have it."""
    checkout = checkout or locks.target_checkout()
    commit = commit or locks.target()["target"]["commit"]
    shown = git("show", f"{commit}:{path}", cwd=checkout)
    return shown.stdout if shown.returncode == 0 else None
