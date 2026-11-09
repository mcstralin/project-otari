"""Otari-Bench: fix rate, cost and latency over the seeded-bug cases, per patcher model."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .agent import Agent
from .config import load_config


def run_bench(cases_dir: Path, args, console: Console) -> int:
    cases = sorted(p for p in cases_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.name in wanted]
    patchers = args.patchers.split(",") if args.patchers else [None]
    rows = []
    for patcher in patchers:
        for case in cases:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / case.name
                shutil.copytree(case, work)
                cfg = load_config(work, {"budget_usd": args.budget, "mock": args.mock or None})
                if patcher:
                    cfg.models["patcher"] = patcher
                if cfg.mock:
                    from .mock import MockClient
                    client = MockClient(cfg, work)
                else:
                    from .otari_client import OtariClient
                    client = OtariClient(cfg)
                adversarial = (work / ".adversarial").exists()
                t0 = time.time()
                with console.status(f"[cyan]{case.name}[/] · {cfg.models['patcher']}"):
                    res = Agent(cfg, client, work, adversarial=adversarial).run()
                fixed_by = next((a.model for a in res.attempts if a.passed), "-")
                rows.append({
                    "case": case.name, "patcher": cfg.models["patcher"], "status": res.status,
                    "attempts": len(res.attempts), "fixed_by": fixed_by,
                    "escalated": any(a.tier == "patcher_escalation" for a in res.attempts),
                    "guardrail_events": len(res.guardrail_events),
                    "research": bool(res.research), "cost_usd": round(client.spent_usd, 5),
                    "latency_s": round(time.time() - t0, 1),
                })
                r = rows[-1]
                icon = "[green]✔[/]" if r["status"] == "fixed" else "[red]✘[/]"
                console.print(f"{icon} {case.name:<28} {r['status']:<15} attempts={r['attempts']} "
                              f"cost=${r['cost_usd']:.4f} {r['latency_s']}s fixed_by={fixed_by}")

    t = Table(title="Otari-Bench results")
    for col in ("case", "patcher", "status", "attempts", "escalated", "guard", "cost", "time"):
        t.add_column(col)
    for r in rows:
        t.add_row(r["case"], r["patcher"].split("/")[-1], r["status"], str(r["attempts"]),
                  "yes" if r["escalated"] else "", str(r["guardrail_events"] or ""),
                  f"${r['cost_usd']:.4f}", f"{r['latency_s']}s")
    console.print(t)
    fixed = sum(r["status"] == "fixed" for r in rows)
    total_cost = sum(r["cost_usd"] for r in rows)
    console.print(f"[bold]{fixed}/{len(rows)} fixed[/] · total ${total_cost:.4f} · "
                  f"${(total_cost / fixed if fixed else 0):.4f} per fix")
    out = cases_dir.parent / "bench-results"
    out.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + ("-mock" if args.mock else "")
    (out / f"{stamp}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    md = ["| case | patcher | status | attempts | escalated | cost | time |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['case']} | `{r['patcher']}` | {r['status']} | {r['attempts']} | {'yes' if r['escalated'] else ''} "
           f"| ${r['cost_usd']:.4f} | {r['latency_s']}s |" for r in rows]
    md.append(f"\n**{fixed}/{len(rows)} fixed · total ${total_cost:.4f}**")
    (out / f"{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    console.print(f"[grey62]saved → {out.name}/{stamp}.md[/]")
    return 0
