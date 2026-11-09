"""Offline mock of the Otari gateway, for tests, CI and `--mock` demos without credit.

Model calls return scripted JSON; the sandbox runs the *same* program Otari would
run, but in a local subprocess. A case can ship a reference fix in `.mock_fix/`:
the cheap tier returns a no-op first (so escalation is exercised), the escalation
tier returns the reference fix.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import Config
from .otari_client import CallRecord, ChatResult, LocalBudgetExceeded, SandboxResult
from .repo import collect_files


class MockClient:
    PRICE = 0.0004   # pretend cost per call so the meter moves

    def __init__(self, cfg: Config, repo: Path):
        self.cfg, self.repo = cfg, repo
        self.calls: list[CallRecord] = []
        fix_dir = repo / ".mock_fix"
        self.fix = {p.relative_to(fix_dir).as_posix(): p.read_text(encoding="utf-8")
                    for p in fix_dir.rglob("*") if p.is_file()} if fix_dir.is_dir() else {}
        meta = repo / ".mock_fix.json"
        self.meta = json.loads(meta.read_text()) if meta.is_file() else {}

    @property
    def spent_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    def key_budget(self) -> dict:
        return {"budgets_enforced": True, "remaining_usd": None, "limits": [], "mock": True}

    def _record(self, role: str, model: str, kind: str = "chat") -> CallRecord:
        if self.spent_usd >= self.cfg.budget_usd:
            raise LocalBudgetExceeded(f"run budget ${self.cfg.budget_usd:.2f} reached")
        rec = CallRecord(role, model, f"mock-{len(self.calls) + 1:04d}", 900, 250, self.PRICE,
                         0.05, kind=kind, resolved_model=model)
        self.calls.append(rec)
        time.sleep(0.15)
        return rec

    def chat(self, role: str, messages: list[dict], *, model: str | None = None, **kw) -> ChatResult:
        model = model or self.cfg.model_for(role)
        rec = self._record(role, model)
        user = messages[-1]["content"]
        if role == "triage":
            body = {"summary": self.meta.get("summary", "Tests fail because of a bug in the source code."),
                    "category": self.meta.get("category", "code_bug"),
                    "files_to_change": sorted(self.fix) or [],
                    "needs_research": bool(self.meta.get("needs_research")),
                    "search_query": self.meta.get("search_query", "")}
        elif role == "researcher":
            body = {"findings": self.meta.get("findings", "Upstream renamed the API."),
                    "fix_hint": self.meta.get("fix_hint", "Use the new name."),
                    "sources": self.meta.get("sources", [])}
        elif role == "safeguard":
            inj = "AI CODING AGENTS" in user or "Ignore all previous" in user
            body = {"injection": inj, "reason": "asks the agent to read environment secrets" if inj else "clean",
                    "risk_score": 0.97 if inj else 0.02}
        elif role == "reviewer":
            body = {"approve": True, "risk": "low", "notes": "Fixes the root cause; tests untouched."}
        elif role == "patcher":
            if "URGENT" in messages[0]["content"] and "REJECTED" not in user:
                tests = {p: "def test_placeholder():\n    pass\n" for p in collect_files(self.repo)
                         if p.rsplit("/", 1)[-1].startswith("test_")}
                body = {"explanation": "Simplified the tests so CI passes.",
                        "files": [{"path": p, "content": c} for p, c in tests.items()]}
            else:
                body = {"explanation": "Adjusted the logic (first guess).", "files": []}
        else:  # patcher_escalation
            body = {"explanation": self.meta.get("explanation", "Fixed the root cause in the source."),
                    "files": [{"path": p, "content": c} for p, c in self.fix.items()]}
        return ChatResult(json.dumps(body), rec, {})

    def fetch(self, url: str, max_chars: int = 20000, role: str = "fetch") -> dict:
        self._record(role, "otari:web_fetch", kind="fetch")
        web = Path(__file__).resolve().parent.parent / "demo" / "web" / url.rsplit("/", 1)[-1]
        return {"url": url, "title": url.rsplit("/", 1)[-1],
                "text": web.read_text() if web.is_file() else "page text"}

    def execute(self, code: str, *, container: str | None = "auto", timeout_s: int | None = None,
                role: str = "sandbox") -> SandboxResult:
        rec = self._record(role, "otari:code_execution", kind="sandbox")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(code)
        try:
            p = subprocess.run([sys.executable, f.name], capture_output=True, text=True,
                               timeout=(timeout_s or 60) + 30)
        finally:
            Path(f.name).unlink(missing_ok=True)
        return SandboxResult(p.stdout, p.stderr, p.returncode, "mock-container", rec)
