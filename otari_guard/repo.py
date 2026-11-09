"""Reading the target repo and running its tests locally (to capture the failure)."""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", "node_modules", ".pytest_cache",
             ".mypy_cache", "dist", "build", ".otari-guard-runs", ".tox", ".idea", ".vscode",
             ".mock_fix", ".otari"}   # .otari = guardrails: never shown to models, never shipped
TEXT_EXT = {".py", ".txt", ".md", ".cfg", ".toml", ".ini", ".json", ".yml", ".yaml", ".csv"}
MAX_FILE_BYTES = 120_000
MAX_TOTAL_BYTES = 600_000


@dataclass
class TestRun:
    passed: bool
    output: str
    return_code: int


def collect_files(repo: Path) -> dict[str, str]:
    """Relative path -> text, for the files the sandbox needs to reproduce the run."""
    files: dict[str, str] = {}
    total = 0
    for root, dirs, names in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(names):
            p = Path(root) / name
            if p.suffix not in TEXT_EXT or name == ".env" or name.startswith(".env"):
                continue
            try:
                size = p.stat().st_size
                if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
                    continue
                files[p.relative_to(repo).as_posix()] = p.read_text(encoding="utf-8")
                total += size
            except (UnicodeDecodeError, OSError):
                continue
    return files


def source_files(files: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in files.items() if k.endswith(".py")}


def run_tests_local(repo: Path, test_command: str = "pytest -q", timeout: int = 120) -> TestRun:
    cmd = test_command.split()
    if cmd and cmd[0] == "pytest":
        cmd = [sys.executable, "-m", "pytest", *cmd[1:]]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        return TestRun(False, f"timeout after {timeout}s\n{e.stdout or ''}", -1)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return TestRun(p.returncode == 0, out, p.returncode)


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, pat.rstrip("/*") + "/*")
               for pat in patterns)


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}"
