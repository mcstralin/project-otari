"""The Otari-Guard agent: a small, auditable state machine.

TRIAGE -> RESEARCH? (+SAFEGUARD) -> PATCH -> GUARD -> VERIFY (Otari sandbox)
       -> ESCALATE on failure -> REVIEW -> OUTPUT (PR / patch + receipt)

Each stage is one Otari call to the model best suited for it. Every event is
emitted to a listener (the terminal UI) and recorded for the receipt.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import prompts
from .config import Config
from .guardrails import GuardReport, check_patch
from .otari_client import BudgetExceeded, GuardrailBlocked, LocalBudgetExceeded, OtariError
from .redact import redact
from .repo import collect_files, run_tests_local, source_files
from .sandbox import build_program, parse_output


@dataclass
class Event:
    stage: str
    status: str            # start | ok | fail | warn | info | block
    title: str
    detail: str = ""
    model: str | None = None
    ts: float = field(default_factory=time.time)


@dataclass
class Attempt:
    tier: str
    model: str
    n: int
    explanation: str = ""
    changed: list[str] = field(default_factory=list)
    guard: str = ""
    sandbox: str = ""
    passed: bool = False


@dataclass
class RunResult:
    status: str = "running"   # fixed | not_fixed | budget_stopped | nothing_to_fix | error
    summary: str = ""
    failing_before: str = ""
    passing_after: str = ""
    triage: dict = field(default_factory=dict)
    research: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
    changes: dict[str, str | None] = field(default_factory=dict)
    diff: str = ""
    redactions: dict[str, int] = field(default_factory=dict)
    guardrail_events: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    sandbox_runtime: str = ""
    error: str = ""


Listener = Callable[[Event], None]


def parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in prose or fences; recover the object."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"model did not return JSON: {text[:200]!r}")


def make_diff(original: dict[str, str], changes: dict[str, str | None]) -> str:
    out: list[str] = []
    for path, new in sorted(changes.items()):
        old = original.get(path, "")
        out += difflib.unified_diff(old.splitlines(keepends=True), (new or "").splitlines(keepends=True),
                                    fromfile=f"a/{path}", tofile=f"b/{path}" if new is not None else "/dev/null")
    return "".join(out)


class Agent:
    def __init__(self, cfg: Config, client: Any, repo: Path, listener: Listener | None = None,
                 adversarial: bool = False, failing_log: str | None = None):
        self.cfg, self.client, self.repo = cfg, client, repo
        self.listener = listener or (lambda e: None)
        self.adversarial = adversarial
        self.failing_log = failing_log
        self.result = RunResult()
        self._container: str | None = None
        self._sandbox_state: dict[str, str] = {}   # what the warm sandbox currently holds

    # ---------------------------------------------------------------- events
    def emit(self, stage: str, status: str, title: str, detail: str = "", model: str | None = None) -> None:
        ev = Event(stage, status, title, detail, model)
        self.result.events.append(ev)
        self.listener(ev)

    # ------------------------------------------------------------------- run
    def run(self) -> RunResult:
        r = self.result
        try:
            self._run()
        except (BudgetExceeded, LocalBudgetExceeded) as e:
            r.status = "budget_stopped"
            r.error = str(e)
            self.emit("budget", "block", "Budget reached: stopping and posting a diagnosis instead of a PR",
                      str(e))
        except GuardrailBlocked as e:
            r.status = "not_fixed"
            r.error = str(e)
            r.guardrail_events.append(f"Otari inference guardrail blocked a request: {e}")
            self.emit("guardrail", "block", "Otari guardrail blocked the request", str(e))
        except OtariError as e:
            r.status = "error"
            r.error = f"Otari error {e.status}: {e}"
            self.emit("error", "fail", "Otari request failed", r.error)
        return r

    def _run(self) -> None:
        r, cfg = self.result, self.cfg
        self.original = collect_files(self.repo)

        # 1. Reproduce locally (or use a provided CI log).
        if self.failing_log is None:
            self.emit("reproduce", "start", f"Running `{cfg.test_command}` locally")
            run = run_tests_local(self.repo, cfg.test_command)
            if run.passed:
                r.status = "nothing_to_fix"
                self.emit("reproduce", "ok", "Tests already pass, nothing to fix")
                return
            log = run.output
        else:
            log = self.failing_log
        tail = "\n".join(log.strip().splitlines()[-80:])
        self.emit("reproduce", "fail", "Build is red", _last_line(tail))

        # 2. Redact secrets from everything a model will see.
        tail, counts = redact(tail)
        safe_files: dict[str, str] = {}
        for p, c in source_files(self.original).items():
            safe_files[p], cc = redact(c)
            for k, v in cc.items():
                counts[k] = counts.get(k, 0) + v
        r.redactions = counts
        r.failing_before = tail
        n = sum(counts.values())
        self.emit("redact", "ok" if not n else "warn",
                  f"Redacted {n} secret(s) before any model saw the log" if n else "No secrets found in log or source",
                  ", ".join(f"{k}×{v}" for k, v in counts.items()))

        # 3. Triage (small fast model).
        self.emit("triage", "start", "Triage: classifying the failure", model=cfg.model_for("triage"))
        tri = self._json_call("triage", prompts.TRIAGE_SYSTEM,
                              f"FAILING LOG:\n```\n{tail}\n```\n\nREPO FILES:\n{prompts.files_block(safe_files)}")
        r.triage = tri
        r.summary = tri.get("summary", "")
        self.emit("triage", "ok", tri.get("summary", "classified"),
                  f"category={tri.get('category')} research={tri.get('needs_research')}",
                  model=cfg.model_for("triage"))

        # 4. Research (only if the cause is external) + safeguard.
        hint = ""
        if tri.get("needs_research") and cfg.research:
            hint = self._research(tri.get("search_query") or tri.get("summary", ""), tail)

        # 5. Patch -> guard -> verify loop, escalating tiers.
        feedback = ""
        tiers = [("patcher", cfg.model_for("patcher")), ("patcher_escalation", cfg.model_for("patcher_escalation"))]
        for t_index, (tier, model) in enumerate(tiers):
            if t_index > 0:
                self.emit("escalate", "warn", f"Escalating to a larger model: {model}",
                          f"{cfg.max_attempts} attempt(s) on {tiers[t_index - 1][1]} did not pass", model=model)
            for n in range(1, cfg.max_attempts + 1):
                att = Attempt(tier=tier, model=model, n=n)
                r.attempts.append(att)
                changes = self._patch(tier, model, n, tail, safe_files, hint, feedback, att)
                if not changes:
                    feedback = "Your previous answer changed no files. Return the full content of the files you change."
                    continue
                guard = check_patch(self.repo, self.original, changes, cfg.protected_paths)
                if guard.blocked:
                    msg = "; ".join(v.message for v in guard.violations if v.enforcement == "required")
                    att.guard = f"BLOCKED: {msg}"
                    r.guardrail_events.append(f"Patch guardrail rejected attempt {tier}#{n}: {msg}")
                    self.emit("guard", "block", "Guardrail rejected the patch", msg)
                    feedback = (f"Your patch was REJECTED by repository guardrails: {msg}. "
                                "Fix the source code instead; tests and CI config are off-limits.")
                    continue
                att.guard = "passed" + (f" ({len(guard.violations)} advisory)" if guard.violations else "")
                self.emit("guard", "ok", f"Guardrails passed ({len(guard.gates_checked)} gates)",
                          ", ".join(guard.gates_checked))
                outcome = self._verify(changes)
                att.sandbox = _last_line(outcome.output)
                if outcome.passed:
                    att.passed = True
                    r.changes = changes
                    r.passing_after = "\n".join(outcome.output.splitlines()[-15:])
                    verdict = self._review(tail, changes, outcome.output)
                    if verdict.get("approve", False):
                        r.status = "fixed"
                        r.diff = make_diff(self.original, changes)
                        return
                    feedback = f"Tests passed but the reviewer rejected the diff: {verdict.get('notes')}"
                    att.passed = False
                    continue
                feedback = ("Your previous patch still fails in the sandbox. Output tail:\n```\n"
                            + "\n".join(outcome.output.splitlines()[-40:]) + "\n```")
        r.status = "not_fixed"
        self.emit("done", "fail", "No passing fix within the attempt budget",
                  f"{len(r.attempts)} attempts across {len(tiers)} model tiers")

    # ---------------------------------------------------------------- stages
    def _json_call(self, role: str, system: str, user: str, **kw: Any) -> dict:
        last_err = None
        for _ in range(2):
            res = self.client.chat(role, [{"role": "system", "content": system},
                                          {"role": "user", "content": user}], json_mode=True, **kw)
            try:
                return parse_json(res.content)
            except ValueError as e:
                last_err = e
                user = user + "\n\nReturn ONLY a valid JSON object."
        raise OtariError(f"{role}: {last_err}")

    def _research(self, query: str, tail: str) -> str:
        cfg, r = self.cfg, self.result
        model = cfg.model_for("researcher")
        self.emit("research", "start", f"Researching upstream change: “{query}”", model=model)
        tools = [{"type": "otari_web_search", "max_uses": cfg.research_max_uses}, {"type": "otari_web_fetch"}]
        try:
            res = self._json_call("researcher", prompts.RESEARCH_SYSTEM,
                                  f"Error:\n```\n{_last_lines(tail, 25)}\n```\nSuggested query: {query}",
                                  tools=tools, guardrails=cfg.inference_guardrails or None)
        except GuardrailBlocked as e:
            r.guardrail_events.append(f"Otari inference guardrail blocked research: {e}")
            self.emit("research", "block", "Otari guardrail blocked research content", str(e))
            return ""
        except (BudgetExceeded, LocalBudgetExceeded):
            raise
        except OtariError as e:
            self.emit("research", "warn", "Research unavailable, continuing without it", str(e)[:200])
            return ""
        r.research = res
        sources = res.get("sources") or []
        self.emit("research", "ok", res.get("findings", "")[:160] or "research done",
                  "\n".join(sources[:5]), model=model)
        if cfg.safeguard:
            sg_model = cfg.model_for("safeguard")
            self.emit("safeguard", "start", "Safeguard model screening research for prompt injection",
                      model=sg_model)
            verdict = self._json_call("safeguard", prompts.SAFEGUARD_SYSTEM, json.dumps(res, indent=2))
            if verdict.get("injection"):
                r.guardrail_events.append(f"Safeguard ({sg_model}) quarantined research: {verdict.get('reason')}")
                r.research["quarantined"] = True
                self.emit("safeguard", "block", "Prompt injection detected: research quarantined",
                          str(verdict.get("reason")), model=sg_model)
                return ""
            self.emit("safeguard", "ok", "Research is clean", str(verdict.get("reason", ""))[:160], model=sg_model)
        return f"Upstream research: {res.get('findings', '')}\nSuggested fix: {res.get('fix_hint', '')}"

    def _patch(self, tier: str, model: str, n: int, tail: str, files: dict[str, str], hint: str,
               feedback: str, att: Attempt) -> dict[str, str | None]:
        self.emit("patch", "start", f"Patch attempt {n} ({tier})", model=model)
        system = prompts.PATCH_SYSTEM + (prompts.ADVERSARIAL_ADDENDUM if self.adversarial else "")
        user = (f"FAILING LOG:\n```\n{tail}\n```\n\nTRIAGE: {json.dumps(self.result.triage)}\n\n"
                + (f"{hint}\n\n" if hint else "")
                + (f"FEEDBACK FROM PREVIOUS ATTEMPT:\n{feedback}\n\n" if feedback else "")
                + f"REPO FILES:\n{prompts.files_block(files)}")
        try:
            data = self._json_call(tier, system, user, model=model, max_tokens=8000)
        except (BudgetExceeded, LocalBudgetExceeded, GuardrailBlocked):
            raise
        except OtariError as e:
            att.explanation = f"error: {e}"
            self.emit("patch", "fail", "Patch model failed", str(e)[:200], model=model)
            return {}
        changes: dict[str, str | None] = {}
        for f in data.get("files") or []:
            path = str(f.get("path", "")).lstrip("./")
            if not path:
                continue
            content = f.get("content")
            if content is None or f.get("delete"):
                changes[path] = None
            elif content != self.original.get(path):
                changes[path] = content if content.endswith("\n") else content + "\n"
        att.explanation = data.get("explanation", "")
        att.changed = sorted(changes)
        self.emit("patch", "ok" if changes else "warn",
                  att.explanation[:160] or "patch proposed", "files: " + ", ".join(att.changed), model=model)
        return changes

    def _verify(self, changes: dict[str, str | None]):
        cfg = self.cfg
        target = dict(self.original)
        for p, c in changes.items():
            if c is None:
                target.pop(p, None)
            else:
                target[p] = c
        if self._container is None:
            send, delete = target, []
        else:  # warm sandbox: only ship what differs from its current state
            send = {p: c for p, c in target.items() if self._sandbox_state.get(p) != c}
            delete = [p for p in self._sandbox_state if p not in target]
        self.emit("verify", "start", f"Running tests in Otari sandbox ({len(send)} file(s) shipped"
                  + (", warm container" if self._container else ", new container") + ")",
                  model="otari:code_execution")
        program = build_program(send, delete, cfg.test_command, cfg.sandbox_timeout_s - 5,
                                reset=self._container is None)
        res = self.client.execute(program, container=self._container or "auto", timeout_s=cfg.sandbox_timeout_s)
        if res.container_id:
            self._container = res.container_id
        self._sandbox_state = target
        out = parse_output(res.stdout, res.stderr, res.return_code)
        self.result.sandbox_runtime = f"python {out.python}, runner={out.runner}"
        self.emit("verify", "ok" if out.passed else "fail",
                  "Sandbox: tests PASS" if out.passed else "Sandbox: tests still failing",
                  _last_line(out.output), model="otari:code_execution")
        return out

    def _review(self, tail: str, changes: dict[str, str | None], sandbox_out: str) -> dict:
        model = self.cfg.model_for("reviewer")
        self.emit("review", "start", "Reviewer checking the diff", model=model)
        verdict = self._json_call(
            "reviewer", prompts.REVIEW_SYSTEM,
            f"FAILURE:\n```\n{_last_lines(tail, 30)}\n```\nDIFF:\n```diff\n{make_diff(self.original, changes)}\n```\n"
            f"SANDBOX RESULT:\n```\n{_last_lines(sandbox_out, 10)}\n```")
        self.result.review = verdict
        self.emit("review", "ok" if verdict.get("approve") else "fail",
                  ("Approved" if verdict.get("approve") else "Rejected") + f" (risk: {verdict.get('risk', '?')})",
                  str(verdict.get("notes", ""))[:200], model=model)
        return verdict


def _last_line(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1][:200] if lines else ""


def _last_lines(text: str, n: int) -> str:
    return "\n".join(text.strip().splitlines()[-n:])
