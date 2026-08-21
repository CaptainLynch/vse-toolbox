"""Safe Git worktree lifecycle operations for a single harness task."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)


def repository_root(root: Path) -> Path:
    result = _git(root, "rev-parse", "--show-toplevel")
    if result.returncode:
        raise RuntimeError("Not inside a Git repository: " + result.stderr.strip())
    return Path(result.stdout.strip()).resolve()


def create(root: Path, task_id: str, worktree_root: str = ".agents/worktrees") -> Path:
    root = repository_root(root)
    if any(ch in task_id for ch in "\\/:*?\"<>|") or not task_id:
        raise ValueError("Task id contains an unsafe path character")
    destination = (root / worktree_root / task_id).resolve()
    parent = (root / worktree_root).resolve()
    if parent not in destination.parents:
        raise ValueError("Worktree destination escapes configured root")
    if destination.exists():
        raise FileExistsError(f"Worktree already exists: {destination}")
    branch = f"agent/{task_id}"
    if _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        raise FileExistsError(f"Branch already exists: {branch}")
    parent.mkdir(parents=True, exist_ok=True)
    result = _git(root, "worktree", "add", "-b", branch, str(destination), "HEAD")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return destination


def remove(root: Path, task_id: str, worktree_root: str = ".agents/worktrees") -> None:
    root = repository_root(root)
    destination = (root / worktree_root / task_id).resolve()
    parent = (root / worktree_root).resolve()
    if parent not in destination.parents or not destination.exists():
        raise ValueError("Refusing to remove an unrecognized worktree path")
    result = _git(root, "worktree", "remove", str(destination))
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "remove"))
    parser.add_argument("task_id")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    fn = create if args.action == "create" else remove
    print(fn(Path(args.root), args.task_id))
