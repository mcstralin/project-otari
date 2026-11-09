"""otari-guard command line: init | doctor | fix | bench | explain."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import CONFIG_FILE, DEFAULT_CONFIG_YAML, ROLE_DESCRIPTIONS, load_config
from .guardrails import DEFAULT_GUARDRAILS_YML

console = Console()

POLICY_HINT = Path(__file__).resolve().parent.parent / "policies" / "routing.yml"


def make_client(cfg, repo: Path):
    if cfg.mock:
        from .mock import MockClient
        return MockClient(cfg, repo)
    from .otari_client import OtariClient
    return OtariClient(cfg)


# ---------------------------------------------------------------------- init
def cmd_init(args) -> int:
    repo = Path(args.path).resolve()
    wrote = []
    cfg_path = repo / CONFIG_FILE
    if not cfg_path.exists() or args.force:
        cfg_path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
        wrote.append(CONFIG_FILE)
    g = repo / ".otari" / "guardrails.yml"
    if not g.exists() or args.force:
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_text(DEFAULT_GUARDRAILS_YML, encoding="utf-8")
        wrote.append(".otari/guardrails.yml")
    env_example = repo / ".env.example"
    if not env_example.exists():
        env_example.write_text("OTARI_API_KEY=otk_...\nOTARI_BASE_URL=https://api.otari.ai/api/v1\nGITHUB_TOKEN=\n",
                               encoding="utf-8")
        wrote.append(".env.example")
    console.print(Panel.fit(
        "\n".join(f"[green]✔[/] wrote {w}" for w in wrote) or "[yellow]nothing to write (use --force)[/]",
        title="otari-guard init"))
    console.print("Next: put your key in [bold].env[/] → [bold]otari-guard doctor[/] → [bold]otari-guard fix[/]")
    if POLICY_HINT.is_file():
        console.print("\n[bold]Optional:[/] server-side failover + budget-aware routing. "
                      f"Create these policies in the Otari dashboard (Routing):\n[grey62]{POLICY_HINT}[/]")
    return 0


# -------------------------------------------------------------------- doctor
def cmd_doctor(args) -> int:
    repo = Path(args.path).resolve()
    cfg = load_config(repo)
    t = Table(title="otari-guard doctor", show_lines=False)
    t.add_column("check")
    t.add_column("status")
    t.add_column("detail", overflow="fold")

    def row(name, ok, detail=""):
        t.add_row(name, "[green]GO[/]" if ok is True else "[red]NO-GO[/]" if ok is False else "[yellow]WARN[/]",
                  str(detail))

    row("gateway", True, cfg.base_url)
    if not cfg.api_key:
        row("OTARI_API_KEY", False, "missing: add it to .env")
        console.print(t)
        return 1
    from .otari_client import BudgetExceeded, OtariClient, OtariError
    c = OtariClient(cfg)
    try:
        models = {m["id"]: m for m in c.list_models()}
        row("auth + model catalog", True, f"{len(models)} models")
    except OtariError as e:
        row("auth + model catalog", False, e)
        console.print(t)
        return 1
    for role, model in cfg.models.items():
        m = models.get(model)
        p = (m or {}).get("pricing") or {}
        row(f"model · {role}", bool(m), f"{model}  (${p.get('input_price_per_million', '?')}/"
                                         f"${p.get('output_price_per_million', '?')} per M tok)")
    try:
        tools = {x["id"]: x for x in c.list_tools()}
        for tid in ("otari_code_execution", "otari_web_search", "otari_web_fetch"):
            x = tools.get(tid, {})
            row(f"tool · {tid}", bool(x.get("available")), x.get("reason") or "available")
    except OtariError as e:
        row("tools", False, e)
    try:
        b = c.key_budget()
        row("key budget", True, f"enforced={b.get('budgets_enforced')} remaining={b.get('remaining_usd')} "
                                f"limits={len(b.get('limits') or [])}")
    except OtariError as e:
        row("key budget", None, e)
    try:
        r = c.chat("triage", [{"role": "user", "content": "Reply with the single word: ok"}], max_tokens=300)
        row("chat completion", True, f"{r.record.resolved_model}: {r.content.strip()[:40]!r} "
                                     f"(req {r.record.request_id})")
    except BudgetExceeded as e:
        row("chat completion", False, f"funds/budget: {e}")
    except OtariError as e:
        row("chat completion", False, e)
    try:
        s = c.execute("import sys,subprocess\nprint(sys.version.split()[0])\n"
                      "print('pytest', subprocess.run([sys.executable,'-c','import pytest;print(pytest.__version__)'],"
                      "capture_output=True,text=True).stdout.strip() or 'missing')", container=None)
        row("sandbox (code/execute)", s.return_code == 0, " · ".join(s.stdout.split()) or s.stderr[:200])
    except BudgetExceeded as e:
        row("sandbox (code/execute)", False, f"funds/budget: {e}")
    except OtariError as e:
        row("sandbox (code/execute)", False, e)
    console.print(t)
    return 0


# ----------------------------------------------------------------------- fix
def cmd_fix(args) -> int:
    from .agent import Agent
    from .receipt import render_markdown, run_json
    from .ui import TimelineUI

    repo = Path(args.path).resolve()
    cfg = load_config(repo, {"budget_usd": args.budget, "max_attempts": args.max_attempts,
                             "mock": args.mock or None, "research": False if args.no_research else None})
    client = make_client(cfg, repo)
    log = Path(args.log).read_text(encoding="utf-8") if args.log else None
    console.print(f"[bold]Otari-Guard {__version__}[/] · repo [cyan]{repo.name}[/] · gateway "
                  f"[cyan]{'MOCK' if cfg.mock else cfg.base_url}[/] · budget [bold]${cfg.budget_usd:.2f}[/]")
    with TimelineUI(console, client, cfg.budget_usd, repo.name) as ui:
        agent = Agent(cfg, client, repo, ui.on_event, adversarial=args.adversarial, failing_log=log)
        res = agent.run()

    key_budget = None
    try:
        key_budget = client.key_budget()
    except Exception:
        pass
    receipt = render_markdown(cfg, res, client.calls, client.spent_usd, key_budget)
    out = repo / ".otari-guard-runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "receipt.md").write_text(receipt, encoding="utf-8")
    (out / "run.json").write_text(run_json(cfg, res, client.calls, client.spent_usd), encoding="utf-8")
    if res.diff:
        (out / "fix.diff").write_text(res.diff, encoding="utf-8")
    import re as _re
    console.print(Markdown(_re.sub(r"<details>[\s\S]*?</details>", "", receipt)))
    console.print(f"[grey62]receipt → {out.relative_to(repo)}/receipt.md[/]")

    if res.status == "fixed":
        if args.apply:
            for p, c in res.changes.items():
                target = repo / p
                if c is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(c, encoding="utf-8")
            console.print("[green]✔ applied fix to working tree[/]")
        if args.pr:
            _open_pr(cfg, client, res, receipt, args)
    return 0 if res.status in ("fixed", "nothing_to_fix") else 2


def _open_pr(cfg, client, res, receipt: str, args) -> None:
    from .github_pr import PRError, open_pr_mcp, open_pr_rest
    title = f"otari-guard: {res.summary[:80] or 'fix failing tests'}"
    if not args.yes:
        ans = console.input(f"\n[bold]Open PR on {cfg.github_repo}?[/] "
                            f"({len(res.changes)} file(s), ${client.spent_usd:.4f} spent) [y/N] ")
        if ans.strip().lower() not in ("y", "yes"):
            console.print("[yellow]PR not opened (human declined)[/]")
            return
    if cfg.use_mcp and args.pr_via in ("mcp", "auto") and not cfg.mock:
        try:
            url = open_pr_mcp(cfg, client, res.changes, title, receipt)
            console.print(f"[green]✔ PR opened via GitHub MCP (through Otari):[/] {url}")
            return
        except Exception as e:
            console.print(f"[yellow]MCP path failed ({e}); falling back to GitHub REST[/]")
            if args.pr_via == "mcp":
                return
    try:
        url = open_pr_rest(cfg, res.changes, title, receipt)
        console.print(f"[green]✔ PR opened:[/] {url}")
    except PRError as e:
        console.print(f"[red]PR failed:[/] {e}")


# ------------------------------------------------------------------- explain
def cmd_explain(args) -> int:
    repo = Path(args.path).resolve()
    cfg = load_config(repo)
    t = Table(title="model roles (all open-weight, routed by Otari)")
    for col in ("role", "job", "calls", "price in/out per M"):
        t.add_column(col)
    prices = {}
    if cfg.api_key and not args.offline:
        try:
            from .otari_client import OtariClient
            prices = OtariClient(cfg).pricing()
        except Exception:
            prices = {}
    for role, desc in ROLE_DESCRIPTIONS.items():
        target = cfg.model_for(role)
        p = prices.get(cfg.models.get(role, ""), None)
        t.add_row(role, desc, target + (" [policy]" if role in cfg.policies else ""),
                  f"${p[0]}/${p[1]}" if p else "-")
    console.print(t)
    for role, pol in cfg.policies.items():
        try:
            from .otari_client import OtariClient
            plan = OtariClient(cfg).explain_policy(name=pol, budget_used_pct=args.budget_used_pct)
            console.print(Panel(json.dumps(plan, indent=2)[:3000], title=f"routing explain · {pol}"))
        except Exception as e:
            console.print(f"[yellow]explain {pol}: {e}[/]")
    return 0


# --------------------------------------------------------------------- bench
def cmd_bench(args) -> int:
    from .bench import run_bench
    return run_bench(Path(args.cases).resolve(), args, console)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="otari-guard", description="Self-healing CI on open-weight models, via Otari.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="write .otari-guard.yml and .otari/guardrails.yml")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("doctor", help="check gateway, key, funds, models, tools and sandbox")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("fix", help="repair the failing tests in a repo")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--budget", type=float, help="USD cap for this run (default from config)")
    p.add_argument("--max-attempts", type=int, help="sandbox attempts per model tier")
    p.add_argument("--log", help="use a CI log file instead of running tests locally")
    p.add_argument("--mock", action="store_true", help="offline mock gateway (no credit needed)")
    p.add_argument("--no-research", action="store_true", help="disable web search/fetch")
    p.add_argument("--adversarial", action="store_true", help="pressure the patcher to cheat (guardrail demo)")
    p.add_argument("--apply", action="store_true", help="write the fix to the working tree")
    p.add_argument("--pr", action="store_true", help="open a pull request (asks for approval)")
    p.add_argument("--pr-via", choices=["auto", "mcp", "rest"], default="auto")
    p.add_argument("--yes", action="store_true", help="skip the PR approval prompt")
    p.set_defaults(fn=cmd_fix)

    p = sub.add_parser("explain", help="show model roles, prices and routing plans")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--budget-used-pct", type=float)
    p.add_argument("--offline", action="store_true")
    p.set_defaults(fn=cmd_explain)

    p = sub.add_parser("bench", help="benchmark fix rate / cost / latency over seeded bugs")
    p.add_argument("cases", nargs="?", default="demo/cases")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--budget", type=float, default=0.30, help="USD cap per case")
    p.add_argument("--patchers", help="comma-separated patcher models to compare")
    p.add_argument("--only", help="comma-separated case names")
    p.set_defaults(fn=cmd_bench)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        console.print("[yellow]interrupted[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
