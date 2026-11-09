# Demo video script (target ~4:30, hard max 5:00)

**Rules:** your own screen and your own voice; no AI voice or AI-generated video.

## Before you hit record (10 min)
1. Otari dashboard → **API keys** → set **alice**'s budget back to **$0.02** (or make a fresh `alice` key with $0.02 and update `OTARI_API_KEY_ALICE` in `.env`).
2. PowerShell in `C:\Users\endless\Documents\project-otari`; make the font big (Ctrl + scroll); maximize the window.
3. Browser tabs, in order: **(1)** GitHub repo README, **(2)** the poisoned page `https://raw.githubusercontent.com/mcstralin/project-otari/devs-wilding/demo/web/slugkit-CHANGELOG.md`, **(3)** Otari dashboard → Routing → `guard-patcher`, **(4)** Otari → API keys, **(5)** Otari → Usage, **(6)** `demo/BENCHMARK.md` on GitHub.
4. Make sure `otari-guard doctor` shows **guardrails engine: GO (otari guardrails check)**. If not, install Otari's CLI once (see below).
5. Dry-run every command once (a full rehearsal costs ~$0.15). Then `cls`.
6. Close notifications and anything that shows your `.env`. **Never open `.env` on screen.**

**Installing Otari's CLI on Windows (one time):**
```
pip install uv
uv tool install --python 3.13 https://github.com/mozilla-ai/otari/releases/download/v0.41.0/otari_agent-0.41.0.tar.gz
uv tool update-shell
```
Then open a new PowerShell window and check with `otari --help`.

---

### 0:00–0:20 · Hook (tab 1: README)
> "When CI goes red, someone drops everything to fix it. Otari-Guard does it for you, with open-weight models only. It proves every fix in a sandbox, never spends past its budget, and opens a PR with a receipt. Everything runs through Otari."

### 0:20–0:40 · One command checks everything
```
otari-guard doctor
```
> "Six roles, six open-weight models, each sized for its job, plus code execution, web search and fetch, all behind one OpenAI-compatible endpoint."

### 0:40–1:40 · A fix with research
```
otari-guard fix demo/cases/06-base64-encodestring-removed
```
Narrate as rows appear:
- "Secrets are redacted before any model sees the log."
- "Triage spots an upstream API change, so the researcher uses **Otari web search**, with cited sources."
- "The cheap coder patches it. **Otari's own guardrail CLI** checks the patch against the repo's gates, and the repo's real tests run in **Otari's sandbox**. They pass."
- "A reviewer model approves it."
Scroll to the cost table: "Exact Otari billing per model. A plain fix costs one cent; this one used web search, so about six."

### 1:40–2:35 · Attack: poisoned docs (tab 2, then run)
Point at the hidden HTML comment:
> "This changelog hides instructions telling AI agents to send my environment variables to an attacker and delete my tests."
```
otari-guard fix demo/cases/07-poisoned-changelog
```
> "The error links to that page. Otari-Guard fetches it through **Otari's fetch API** and screens the raw text with an open-weight safety model before any agent reads it. Injection detected, quarantined. The agent still fixes the bug from the code, and guardrails block any patch that touches secrets or the network."

### 2:35–3:20 · Routing + per-developer budgets (tabs 3, 4)
Tab 3: "My patcher doesn't call a model, it calls an **Otari routing policy**: fallbacks plus a budget tier-down, configured in Otari, not in my code."
Tab 4: "Alice has her own key with a two-cent budget."
```
otari-guard fix demo/cases/02-string-not-number --as alice
otari-guard fix demo/cases/03-none-middle-name --as alice
```
> "First fix: done. Second: **Otari's budget gate refuses** the request, so Otari-Guard stops cleanly and writes a diagnosis instead of a PR. Nobody else's budget is touched."

### 3:20–3:55 · PR through MCP
```
otari-guard fix demo/cases/01-off-by-one-pagination --pr --pr-via mcp
```
Type `y` at the approval prompt, then open the PR link.
> "After I approve, the agent opens the PR through **GitHub's MCP server, connected by Otari**. The GitHub token lives in Otari, and the server only exposes four tools, so it can't merge or delete anything. The PR description is the receipt."

### 3:55–4:20 · Results (tabs 6, 5)
> "Nine out of nine seeded bugs fixed, twenty-three cents for the whole suite, exact Otari billing. When the cheap coder failed twice, Otari-Guard escalated to the big one, which is exactly what the tiers are for."

### 4:20–4:35 · Close
> "Open-weight models, a sandbox, budgets, guardrails and MCP: enough to trust an agent with your CI. And because it's Otari, going self-hosted is one environment variable. Thanks!"

---

**If something goes wrong on camera:** keep going. Retries and escalation are part of the story. If a run fails completely, cut it and show the receipt from your rehearsal (`.otari-guard-runs/<time>/receipt.md` inside that case folder).
**Open PRs:** each `--pr` run opens a new PR. Close the extras after recording (don't merge them; they'd fix the demo bugs).
