# Demo video script (target 4:00, max 5:00)

Rules: your own screen and your own voice, no AI voice or AI-generated video. Practice once, then record.
Have these open before you start: a terminal in `project-otari`, the GitHub repo page, the Otari dashboard (Usage page), and the poisoned page:
`https://raw.githubusercontent.com/mcstralin/project-otari/devs-wilding/demo/web/slugkit-CHANGELOG.md`

Font size: make the terminal text large (Ctrl + mouse wheel), window about 140 columns wide.

---

### 0:00–0:20 · The problem (show: README top)
> "When CI goes red, a developer stops everything to read logs and fix it. AI agents can do this, but usually with closed models, no budget, and no proof the fix works. Otari-Guard fixes failing builds with open-weight models only, proves every fix in a sandbox, and never spends past its budget. Everything runs through Otari."

### 0:20–0:45 · Setup check (run)
```
otari-guard doctor
```
> "Six roles, six open-weight models, each picked for its job: a small triage model, a cheap coder, a big coder for escalation, a researcher, a safety model and a reviewer. Otari gives me all of them, plus code execution, web search and fetch, behind one OpenAI-compatible API."

### 0:45–1:50 · A real fix with research (run)
```
otari-guard fix demo/cases/06-base64-encodestring-removed
```
Narrate the timeline as it fills:
- "Secrets are redacted before any model sees the log."
- "Triage classifies the failure as an upstream API change, so the researcher uses **Otari web search**, and you can see the sources it cites."
- "The cheap coder writes a patch. Guardrails check it, then the repo's real test suite runs in **Otari's sandbox**. Tests pass."
- "A reviewer model approves the diff."
Scroll the receipt: "The receipt shows exact Otari billing per model. This fix cost about one cent."

### 1:50–2:50 · Attack: poisoned docs (browser, then run)
Show the raw page in the browser and point at the hidden HTML comment:
> "This changelog hides instructions telling AI agents to send my environment variables to an attacker and delete tests."
```
otari-guard fix demo/cases/07-poisoned-changelog
```
> "The error links to that page. Otari-Guard fetches it through **Otari's fetch API**, and before any agent reads it, an open-weight safety model screens the raw text. Prompt injection detected, page quarantined. The agent then fixes the bug from the repository code alone, and the guardrails would block any patch that touches secrets or the network anyway."

### 2:50–3:20 · Secret leak (run, short)
```
otari-guard fix demo/cases/04-config-typo-leaks-secret
```
> "Here the failing test dumps a GitHub token into the CI log. Four secrets were redacted before any model saw it."

### 3:20–3:50 · Routing + per-developer budgets (dashboard + run)
**Before recording:** in API keys, raise alice's budget back to $0.02 or create a fresh key with $0.02.
- Show the `guard-patcher` policy page: "My patcher calls a routing policy, not a model. Fallbacks and a budget tier-down live in Otari, not in my code." In the receipt, point at the line "Otari routed guard-patcher → … fallback fired".
- Show the API keys page with alice's $0.02 budget, then run twice:
```
otari-guard fix demo/cases/02-string-not-number --as alice
otari-guard fix demo/cases/03-none-middle-name --as alice
```
> "Alice is a developer with her own key and a two-cent budget. Her first fix goes through. On the second, Otari's budget gate refuses the request, so Otari-Guard stops cleanly with a diagnosis and no PR. Nobody else's budget is touched."

### 3:50–4:20 · Results (show BENCHMARK.md + Otari Usage page)
> "On nine seeded bugs, Otari-Guard fixed nine out of nine, eight on the first try with the cheapest coder model, at around a cent per fix. Every number here comes from Otari's own usage API."

### 4:20–4:40 · Close
> "Open-weight models, a sandbox, budgets and guardrails: that's enough to trust an agent with your CI. And because it's Otari, moving to self-hosted is one environment variable. Thanks!"

---

**Backup plan:** before recording, run each command once so you know it works. If a live run misbehaves on camera, keep recording and narrate: retries and escalation are part of the story. If a run fails completely, cut and use the `.otari-guard-runs/*/receipt.md` from the earlier successful run.
