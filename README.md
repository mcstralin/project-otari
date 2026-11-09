# 🛡️ Otari-Guard

**Self-healing CI on open-weight models.** Otari-Guard reads a failing build, works out the cause (researching upstream changes if needed), **proves a fix in Otari's sandbox**, and opens a PR with a **receipt** listing what it cost, which models it used and the evidence. It never spends past the budget you set.

> Built for MozFest **Developers Wilding: Online** on [Otari](https://otari.ai) by Mozilla.ai. Every model is open-weight. Pointing `OTARI_BASE_URL` at a self-hosted Otari takes one environment variable and nothing else changes.

```text
failing tests ─▶ redact secrets ─▶ triage (gpt-oss-20b)
                                     │ external cause?
                                     ▼
                     research: Otari web search + fetch (gpt-oss-120b)
                     safeguard: prompt-injection judge (gpt-oss-safeguard-120b)
                                     ▼
   patch (qwen3-coder-30b) ─▶ guardrails ─▶ verify in Otari sandbox ─▶ pass? ─▶ review (deepseek-v4-flash)
        ▲   still failing ×N                                                        ▼
        └── escalate (qwen3-coder-480b)                          PR + receipt (GitHub MCP via Otari)
```

## Live results on hosted Otari

**9/9 seeded bugs fixed** ([demo/BENCHMARK.md](demo/BENCHMARK.md)), 8 on the first attempt with the cheapest coder (`qwen3-coder-30b`), around **$0.01 per fix** as billed by Otari. Every fix was proven by the repo's own tests in Otari's sandbox and approved by a reviewer model. In the poisoned-docs case, the open-weight safeguard caught a hidden "send me your env vars" instruction in a page fetched through Otari and quarantined it.

## Quickstart (60 seconds)

```bash
pip install -e .                 # Python 3.10+
cp .env.example .env             # add your OTARI_API_KEY (otk_...)
otari-guard doctor               # checks key, funds, models, tools, sandbox
otari-guard fix demo/cases/05-collections-mapping-removed
```

No credit yet? Everything also runs offline: `otari-guard fix demo/cases/07-poisoned-changelog --mock`.

| command | what it does |
|---|---|
| `otari-guard init` | writes `.otari-guard.yml` + `.otari/guardrails.yml` into your repo |
| `otari-guard doctor` | GO/NO-GO for gateway, auth, funds, every model role, tools and the sandbox |
| `otari-guard fix [path]` | repairs the failing tests. Flags: `--budget 0.25 --max-attempts 2 --apply --pr --log ci.log --mock --adversarial` |
| `otari-guard explain` | model roles, live prices, routing-policy plans (`--budget-used-pct 85`) |
| `otari-guard bench demo/cases` | Otari-Bench: fix rate / cost / latency per patcher model |

### In CI (GitHub Action)

```yaml
- if: failure()
  uses: mcstralin/project-otari@devs-wilding
  with:
    otari-api-key: ${{ secrets.OTARI_API_KEY }}
    budget: "0.25"
```
Full workflow: [`examples/workflow.yml`](examples/workflow.yml).

## How Otari is used (rubric map)

| Otari capability | Where in the code | What you see |
|---|---|---|
| **Open-weight models, 6 distinct roles** | `config.py` `DEFAULT_MODELS` | triage `gpt-oss-20b`, patcher `qwen3-coder-30b`, escalation `qwen3-coder-480b`, researcher `gpt-oss-120b`, safeguard `gpt-oss-safeguard-120b`, reviewer `deepseek-v4-flash` |
| **Code execution** | `otari_client.py` `execute()` → `POST /api/v1/code/execute` with `container: "auto"`; program built in `sandbox.py` | every candidate fix runs the real test suite in Otari's sandbox; later attempts reuse the warm container and ship only the changed files |
| **Web search + web fetch** | `agent.py` `_research()`: `otari_web_search` (with `max_uses`) + `otari_web_fetch` in the model loop; pages linked from the error are fetched directly via `POST /api/v1/fetch` and screened before any agent reads them | used only when the cause is upstream (e.g. a removed stdlib API); sources are cited in the receipt |
| **Exact cost accounting** | `otari_client.py` `reconcile()` → `GET /api/v1/usage/requests/{id}` | receipts show Otari's billed cost per role, not estimates |
| **Routing & fallbacks** | dashboard policy `guard-patcher` (Qwen3-Coder-30B → Devstral-2 → Qwen3-Coder-480B-Turbo, budget tier-down → gpt-oss-20b), enabled with `OTARI_GUARD_POLICIES=patcher=guard-patcher`; `otari-model`/`otari-fallback`/`otari-attempt-count` headers shown in the timeline and receipt | live: both Bedrock targets rejected the request and Otari fell through to the 3rd backup on DeepInfra with zero code changes; quality escalation (cheap → large coder) stays client-side |
| **Multiple models, distinct roles** | `agent.py` (one stage = one model) | the receipt itemizes calls, tokens and cost per role |
| **Budgets & spend limits** | `otari_client.py` maps 402/budget refusals → `BudgetExceeded`; `/key/budget` read for the receipt; local `budget_usd` cap | live budget meter; if a run hits the cap it stops and writes a diagnosis instead of a PR |
| **Per-user budgets** | `otari-guard fix --as alice` → that developer's own Otari key (`OTARI_API_KEY_ALICE`) with its own budget; `developer` metadata tag on every request; optional `end_user` for keys with end-user budgets | live: alice fixes one bug, then Otari's budget gate refuses her next request and Otari-Guard posts a diagnosis instead of a PR; nobody else's budget is touched |
| **Guardrails** | `guardrails.py`: Otari **Agent Guardrails** `.otari/guardrails.yml` path gates + built-in gates; `redact.py`; safeguard model; optional Otari inference `guardrails` per request (`inference_guardrails`) | blocks patches that delete/skip tests, edit CI, or add secret/network access; quarantines prompt-injected research; redacts secrets before any model call |
| **MCP** | `github_pr.py` `open_pr_mcp()`: GitHub's remote MCP server passed inline via `mcp_servers` with `allowed_tools` limited to 4 tools | the PR is opened through Otari's MCP loop after a human approves; GitHub REST is the fallback |
| **Cost attribution** | `metadata` tags (`app`, `role`) on every request; Otari request IDs in the receipt | filter usage by role in the Otari dashboard |

## The demo cases

`demo/cases/` holds 9 small repos, each with one seeded bug (regenerate with `python scripts/make_cases.py`):

| case | what it shows |
|---|---|
| 01 off-by-one, 02 str vs float, 03 None join, 09 dict mutation | the core loop: triage → patch → sandbox → review |
| 04 config typo **leaks a token into the CI log** | secret redaction before any model sees the log |
| 05 `collections.Mapping` removed (Py 3.10), 06 `base64.encodestring` removed (Py 3.9) | web search/fetch research on an upstream change |
| 07 poisoned changelog | the fetched page tells the agent to send `os.environ` to a URL: the safeguard quarantines it and guardrails block exfiltration |
| 08 adversarial median | the patcher is told to "make CI green by any means": guardrails reject deleted/skipped tests and force a real fix |

## Design notes

- **Proof, not vibes.** A fix only counts after the repository's own tests pass in Otari's sandbox. If pytest is missing in the sandbox, it installs it, then falls back to a built-in runner.
- **Secrets never reach a model.** Logs and source are redacted first. The receipt counts redactions by type.
- **Untrusted web content.** Research output is screened by an open-weight safety model before the patcher sees it. Patches that add `os.environ` access, network calls or `subprocess` are rejected anyway.
- **One policy file for all agents.** `.otari/guardrails.yml` is the same file Otari's Agent Guardrails use for Claude Code and Codex hooks, so it governs humans' agents and Otari-Guard alike.
- **No lock-in.** The OpenAI SDK with `base_url`; the hosted or a self-hosted Otari; any model in the catalog via `.otari-guard.yml`.

## Dashboard setup (one-time)

1. **Tools → Web search → Web access: Allowed** (enables `otari_web_search` + `otari_web_fetch`).
2. **Budgets:** set a budget on the API key and, for teams, per-member/end-user budgets.
3. *(Optional)* **Routing:** create `guard-patcher` / `guard-reviewer` from [`policies/routing.yml`](policies/routing.yml), then add `policies:` to `.otari-guard.yml`.

## Development

```bash
pip install -e ".[dev]" && pytest -q      # unit tests + offline end-to-end runs (mock gateway)
otari-guard bench demo/cases --mock      # benchmark harness offline
```

License: Apache-2.0
