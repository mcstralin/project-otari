"""Patch guardrails: a fix may never 'pass' CI by weakening CI.

Primary path: Otari Agent Guardrails. The repo's `.otari/` gates (path gates +
verifier scripts) are run by Otari's own CLI, `otari guardrails check`, against
the candidate patch staged in a scratch git checkout. `--guardrails-from` points
at the untouched repo, so a patch can never edit the gates that judge it. The
same `.otari/` files guard human-driven coding agents through `otari hook`.

Fallback (no `otari` CLI on the machine): an equivalent built-in evaluator.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import tempfile
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
    raw: str = ""
    engine: str = "builtin"          # "otari" when `otari guardrails check` decided

    @property
    def blocked(self) -> bool:
        return any(v.enforcement == "required" for v in self.violations)


def load_gates(repo: Path) -> list[dict]:
    d = repo / ".otari"
    files = [d / "guardrails.yml"] if (d / "guardrails.yml").is_file() else []
    if (d / "guardrails").is_dir():
        files += sorted((d / "guardrails").rglob("*.y*ml"))
    gates: list[dict] = []
    for p in files:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        gates += [g for g in data.get("gates", []) if isinstance(g, dict)]
    return gates


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
    if otari_cli_available() and _has_repo_guardrails(repo):
        try:
            rep = check_with_otari(repo, original, changes)
        except Exception as e:  # never let the optional engine break a run
            rep = _builtin(repo, original, changes, protected_paths)
            rep.otari_cli = f"otari check failed, used built-in gates: {e}"
            return rep
        for path in changes:   # Otari-Guard's own config-level protected paths
            if matches_any(path, protected_paths):
                rep.violations.append(Violation("protected-paths", f"patch edits protected path {path}"))
        return rep
    return _builtin(repo, original, changes, protected_paths)


def otari_cli_available() -> bool:
    return bool(shutil.which("otari")) and bool(shutil.which("git"))


def _has_repo_guardrails(repo: Path) -> bool:
    d = repo / ".otari"
    return (d / "guardrails.yml").is_file() or (d / "guardrails").is_dir()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=otari-guard", "-c", "user.email=otari-guard@localhost",
                    "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


FAIL_RE = re.compile(r"^\s*(?:✗|✘|x|FAIL(?:ED)?|fail(?:ed|s)?|blocked)\b.*", re.I)


def check_with_otari(repo: Path, original: dict[str, str], changes: dict[str, str | None]) -> GuardReport:
    """Stage the patch in a scratch checkout and let Otari's CLI judge it."""
    rep = GuardReport(engine="otari")
    with tempfile.TemporaryDirectory(prefix="otari-guard-check-") as tmp:
        work = Path(tmp)
        for rel, text in original.items():
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        _git(work, "init", "-q")
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "--allow-empty", "-m", "base")
        for rel, text in changes.items():
            p = work / rel
            if text is None:
                p.unlink(missing_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
        _git(work, "add", "-A")   # stage, so verifiers reading git see new/deleted files
        proc = subprocess.run(
            ["otari", "guardrails", "check", "--type", "path", "--type", "verifier",
             "--guardrails-from", str(repo)],
            cwd=work, capture_output=True, text=True, timeout=120,
            env={**os.environ, "NO_COLOR": "1"})
    out = (proc.stdout + "\n" + proc.stderr).strip()
    rep.otari_cli = f"otari guardrails check → exit {proc.returncode}"
    rep.gates_checked = [f"otari:{g}" for g in _gate_ids(repo)]
    if proc.returncode == 1:
        for gate, enforcement, detail in _failed_gates(out):
            rep.violations.append(Violation(gate, f"{gate}: {detail}" if detail else gate,
                                            "required" if enforcement == "required" else "advisory"))
        if not rep.blocked:
            rep.violations.append(Violation("otari-guardrails", out.splitlines()[-1][:300] if out else "failed"))
    elif proc.returncode not in (0,):
        raise RuntimeError(f"exit {proc.returncode}: {out[-300:]}")
    rep.raw = out
    return rep


STATUS_RE = re.compile(r"^\s{2}(\w[\w ]*?)\s{2,}([\w./:-]+) \((\w+), (required|advisory)\)\s*$")


def _failed_gates(out: str) -> list[tuple[str, str, str]]:
    """Parse `otari guardrails check` output into (gate, enforcement, detail) for failures."""
    failed, cur = [], None
    for line in out.splitlines():
        m = STATUS_RE.match(line)
        if m:
            cur = None
            if m.group(1).strip() == "fail":
                cur = [m.group(2), m.group(4), []]
                failed.append(cur)
        elif cur is not None and line.startswith("    ") and line.strip():
            cur[2].append(line.strip())
    return [(g, e, " ".join(d)[:300]) for g, e, d in failed]


def _gate_ids(repo: Path) -> list[str]:
    return [g.get("id", "?") for g in load_gates(repo)]


def _builtin(repo: Path, original: dict[str, str], changes: dict[str, str | None],
             protected_paths: list[str]) -> GuardReport:
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

    return rep


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "otari"


def install_guardrails(repo: Path, force: bool = False) -> list[str]:
    """Copy the Otari Agent Guardrails template (gates + verifiers) into repo/.otari."""
    wrote = []
    for src in TEMPLATE_DIR.rglob("*"):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        dst = repo / ".otari" / src.relative_to(TEMPLATE_DIR)
        if dst.exists() and not force:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        wrote.append(dst.relative_to(repo).as_posix())
    return wrote
