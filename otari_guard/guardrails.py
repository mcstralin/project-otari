"""Patch guardrails: a fix may never 'pass' CI by weakening CI.

Gates are read from `.otari/guardrails.yml`, the same file Otari's Agent
Guardrails use (path gates with `forbidden` globs and `required`/`advisory`
enforcement), so one policy file governs both human-driven coding agents and
Otari-Guard. On top of the repo's gates we always apply built-in gates that stop
the classic "make CI green" cheats.
If the `otari` CLI is installed, `otari guardrails check` runs as well.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .repo import is_test_file, matches_any

# A bug fix has no business reading secrets or phoning home. Prompt-injected
# research tends to ask for exactly that.
EXFIL_PATTERNS = [
    re.compile(r"os\.environ|os\.getenv|getenv\("),
    re.compile(r"\brequests\.(?:get|post|put)|urllib\.request|http\.client|httpx\.|socket\.socket"),
    re.compile(r"subprocess\.|os\.system\(|\bcurl\b|\bwget\b"),
]

SKIP_RE = re.compile(r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|unittest\.skip|@skip\b")


@dataclass
class Violation:
    gate: str
    message: str
    enforcement: str = "required"   # required blocks, advisory warns


@dataclass
class GuardReport:
    violations: list[Violation] = field(default_factory=list)
    gates_checked: list[str] = field(default_factory=list)
    otari_cli: str | None = None

    @property
    def blocked(self) -> bool:
        return any(v.enforcement == "required" for v in self.violations)


def load_gates(repo: Path) -> list[dict]:
    p = repo / ".otari" / "guardrails.yml"
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [g for g in data.get("gates", []) if isinstance(g, dict)]


def _count_asserts(src: str) -> int:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src.count("assert ")
    return sum(isinstance(n, ast.Assert) for n in ast.walk(tree)) + src.count("pytest.raises")


def _test_names(src: str) -> set[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set(re.findall(r"def (test_\w+)", src))
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")}


def check_patch(repo: Path, original: dict[str, str], changes: dict[str, str | None],
                protected_paths: list[str]) -> GuardReport:
    """`changes`: path -> new content, or None for deletion."""
    rep = GuardReport()

    # 1. Repo-committed Otari Agent Guardrails path gates.
    for gate in load_gates(repo):
        if gate.get("type") != "path":
            continue
        gid = gate.get("id", "path-gate")
        rep.gates_checked.append(f".otari/guardrails.yml:{gid}")
        forbidden = gate.get("forbidden") or []
        for path in changes:
            if matches_any(path, forbidden):
                rep.violations.append(Violation(gid, gate.get("message") or f"{path} is forbidden",
                                                gate.get("enforcement", "required")))

    # 2. Built-in gates.
    rep.gates_checked += ["builtin:protected-paths", "builtin:no-test-deletion",
                          "builtin:no-new-skips", "builtin:no-weakened-asserts",
                          "builtin:no-exfiltration"]
    for path, new in changes.items():
        old = original.get(path)
        if matches_any(path, protected_paths):
            rep.violations.append(Violation("protected-paths", f"patch edits protected path {path}"))
        if new is not None:
            for pat in EXFIL_PATTERNS:
                if len(pat.findall(new)) > len(pat.findall(old or "")):
                    rep.violations.append(Violation(
                        "no-exfiltration", f"patch adds secret/network access ({pat.pattern}) in {path}"))
                    break
        if not is_test_file(path):
            continue
        if new is None:
            rep.violations.append(Violation("no-test-deletion", f"patch deletes test file {path}"))
            continue
        if old is None:
            continue  # new test files are fine
        removed = _test_names(old) - _test_names(new)
        if removed:
            rep.violations.append(Violation("no-test-deletion", f"patch removes tests {sorted(removed)} from {path}"))
        if len(SKIP_RE.findall(new)) > len(SKIP_RE.findall(old)):
            rep.violations.append(Violation("no-new-skips", f"patch adds skip/xfail markers in {path}"))
        if _count_asserts(new) < _count_asserts(old):
            rep.violations.append(Violation("no-weakened-asserts", f"patch removes assertions from {path}"))

    # 3. Otari CLI (optional): `otari guardrails check` for CI.
    if shutil.which("otari") and (repo / ".otari" / "guardrails.yml").is_file():
        try:
            p = subprocess.run(["otari", "guardrails", "check"], cwd=repo, capture_output=True,
                               text=True, timeout=60)
            rep.otari_cli = f"exit {p.returncode}: {(p.stdout or p.stderr).strip()[:300]}"
            if p.returncode not in (0,):
                rep.violations.append(Violation("otari-cli", rep.otari_cli, "advisory"))
        except Exception as e:  # never let an optional tool break the run
            rep.otari_cli = f"unavailable: {e}"
    return rep


DEFAULT_GUARDRAILS_YML = """\
# Otari Agent Guardrails (https://docs.otari.ai) - shared by coding agents and Otari-Guard.
gates:
  - id: no-ci-edits
    type: path
    runs: [pre_tool_use.edit_target, stop.working_tree]
    enforcement: required
    forbidden: [".github/**"]
    message: Agents may not edit CI workflows to make a build pass.
  - id: no-env-files
    type: path
    runs: [pre_tool_use.edit_target, stop.working_tree]
    enforcement: required
    forbidden: [".env", ".env.*"]
    message: Secrets files are never touched by agents.
"""
