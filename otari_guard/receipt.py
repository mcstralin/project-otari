"""The receipt: what the agent did, with which models, at what cost, with what evidence."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

from .agent import RunResult
from .config import Config

STATUS_LINE = {
    "fixed": "✅ Fixed: tests pass in the Otari sandbox and the reviewer approved",
    "not_fixed": "❌ Not fixed: no passing, guardrail-compliant patch within the attempt budget",
    "budget_stopped": "🛑 Stopped at budget: diagnosis only, no PR opened",
    "nothing_to_fix": "✅ Tests already pass",
    "error": "⚠️ Error talking to Otari",
}


def model_table(calls: list) -> list[dict]:
    agg: dict[tuple, dict] = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0, "request_ids": []})
    for c in calls:
        is_policy = "/" not in c.model and ":" not in c.model
        label = f"{c.model} → {c.resolved_model}" if is_policy and c.resolved_model else c.model
        row = agg[(c.role, label)]
        row["calls"] += 1
        row["tokens"] += c.prompt_tokens + c.completion_tokens
        row["cost"] += c.cost_usd
        if c.request_id:
            row["request_ids"].append(c.request_id)
    return [{"role": k[0], "model": k[1], **v} for k, v in agg.items()]


def render_markdown(cfg: Config, res: RunResult, calls: list, spent: float,
                    key_budget: dict | None = None) -> str:
    L: list[str] = []
    L.append("## 🛡️ Otari-Guard receipt\n")
    L.append(f"**{STATUS_LINE.get(res.status, res.status)}**\n")
    if res.summary:
        L.append(f"**Root cause (triage):** {res.summary}\n")
    fixed = [a for a in res.attempts if a.passed]
    if fixed:
        L.append(f"**Fix ({fixed[-1].model}):** {fixed[-1].explanation}\n")
    if res.error:
        L.append(f"**Stopped because:** `{res.error}`\n")
    if res.status == "budget_stopped":
        L.append("### Diagnosis (no PR opened)")
        L.append(f"- Failure: `{_last(res.failing_before)}`")
        if res.summary:
            L.append(f"- Likely cause: {res.summary}")
        files = res.triage.get("files_to_change") if res.triage else None
        if files:
            L.append(f"- Files to look at: {', '.join(f'`{f}`' for f in files)}")
        L.append("- Next step: raise this developer's Otari budget, or fix by hand using the notes above.\n")

    L.append("### Tests")
    L.append(f"- Before: `{_last(res.failing_before)}`")
    if res.passing_after:
        L.append(f"- After (Otari sandbox, {res.sandbox_runtime}): `{_last(res.passing_after)}`")
    L.append("")

    if res.attempts:
        L.append("### Attempts")
        L.append("| # | tier | model | guardrails | sandbox |")
        L.append("|---|---|---|---|---|")
        for i, a in enumerate(res.attempts, 1):
            L.append(f"| {i} | {a.tier} | `{a.model}` | {a.guard or '-'} | {a.sandbox or '-'} |")
        L.append("")

    if res.research:
        L.append("### Research (Otari web search / fetch)")
        if res.research.get("quarantined"):
            L.append("> ⚠️ Quarantined by the safeguard model: not used for the fix.")
        for q in res.research.get("quarantined_sources") or []:
            L.append(f"> ⛔ Quarantined source (prompt injection): <{q}>")
        L.append(f"{res.research.get('findings', '')}")
        for s in res.research.get("sources") or []:
            L.append(f"- <{s}>")
        L.append("")

    L.append("### Guardrails")
    n = sum(res.redactions.values())
    L.append(f"- Secrets redacted before any model call: **{n}**"
             + (f" ({', '.join(f'{k}×{v}' for k, v in res.redactions.items())})" if n else ""))
    for g in res.guardrail_events:
        L.append(f"- {g}")
    if not res.guardrail_events:
        L.append("- No guardrail interventions")
    L.append("")

    if res.routing_events:
        L.append("### Routing (Otari policies)")
        for e in dict.fromkeys(res.routing_events):
            L.append(f"- {e}")
        L.append("")

    L.append("### Models & cost (all open-weight, via Otari)")
    exact = sum(1 for c in calls if "billed" in (c.note or ""))
    L.append(f"| role | model | calls | tokens | {'billed' if exact else 'est.'} cost |")
    L.append("|---|---|---|---|---|")
    for row in model_table(calls):
        L.append(f"| {row['role']} | `{row['model']}` | {row['calls']} | {row['tokens']:,} | ${row['cost']:.4f} |")
    L.append(f"\n**Run total:** ${spent:.4f} of ${cfg.budget_usd:.2f} run budget"
             + (f" (exact Otari billing for {exact}/{len(calls)} requests)" if exact else " (estimated)"))
    if key_budget and key_budget.get("remaining_usd") is not None:
        L.append(f" · Otari key budget remaining: ${key_budget['remaining_usd']:.2f}")
    rids = [c.request_id for c in calls if c.request_id]
    if rids:
        L.append(f"\n<details><summary>Otari request IDs ({len(rids)})</summary>\n\n"
                 + "\n".join(f"- `{r}`" for r in rids) + "\n</details>")
    if res.diff:
        L.append("\n<details><summary>Diff</summary>\n\n```diff\n" + res.diff + "\n```\n</details>")
    L.append(f"\n<sub>Generated by Otari-Guard · {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · "
             f"gateway `{'mock (offline)' if cfg.mock else cfg.base_url}`</sub>")
    return "\n".join(L) + "\n"


def run_json(cfg: Config, res: RunResult, calls: list, spent: float) -> str:
    return json.dumps({
        "status": res.status, "summary": res.summary, "triage": res.triage, "research": res.research,
        "review": res.review, "attempts": [asdict(a) for a in res.attempts],
        "changed_files": sorted(res.changes), "guardrail_events": res.guardrail_events,
        "redactions": res.redactions, "spent_usd": spent, "budget_usd": cfg.budget_usd,
        "calls": [asdict(c) for c in calls],
        "events": [asdict(e) for e in res.events],
    }, indent=2, default=str)


def _last(text: str) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1][:160] if lines else ""
