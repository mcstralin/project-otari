# Otari feedback log

Running notes while building Otari-Guard. These feed the required feedback video + written answers.
Format: time (UTC) · area · what happened · repro / impact.

## Friction / bugs

- **2026-11-08 09:40 · regions:** the EU host `eu.api.otari.ai` is separate, and EU keys get `421` on the US host (from docs). The dashboard could show "your base URL is …" next to the key.
- **2026-11-08 10:00 · billing:** first chat completion → `402 {"detail":"Insufficient funds ($0.00)…","code":"insufficient_funds"}`. The hackathon's "$20 for first 200" didn't appear, and the $2 welcome credit needs a questionnaire. Repro: new org → create key → `POST /chat/completions`. *Nice:* the error is typed (`code` + `otari-error-code` header), so our client maps it cleanly.
- **2026-11-08 10:00 · tools:** `GET /api/v1/tools` shows `otari_web_search`/`otari_web_fetch` `available:false, reason:"workspace_disabled"` by default. *Nice:* the reason field told us exactly what to toggle. Friction: off by default, and the docs page for the toggle doesn't say whether a search provider key is needed on hosted.
- **2026-11-08 10:12 · admin APIs with a workspace key:** `GET /api/v1/routing/policies`, `/aliases`, `/scoped-budgets`, `/organizations/me/guardrails` with a normal `otk_` key → `401 {"detail":"Invalid master key"}`. The message is confusing: it reads like the key is wrong, when the endpoint actually needs another credential type. Impact: routing policies/budgets can't be managed from code with a member key, only from the dashboard.
- **2026-11-08 10:13 · guardrails on hosted:** `GET /api/v1/tool-settings/guardrails/profiles` → `{"available":false,"reason":"No guardrails service is configured…"}`. Every entry in the guardrail catalog has `requires_api_key: true` (Lakera, Alinia, Azure, …); even the `any_llm` judge defaults to `openai:gpt-5-nano`. Wanted: a built-in prompt-injection profile that runs on an open-weight model hosted by Otari. Workaround: our own safeguard step with `openai/gpt-oss-safeguard-120b` + Otari **Agent Guardrails** (`.otari/guardrails.yml`).
- **2026-11-08 10:15 · docs:** docs are split across `github.com/mozilla-ai/otari/docs` and `docs.otari.ai`; the GitHub MCP example uses a placeholder URL (`https://mcp.example.com/github`). The `ChatCompletionRequest` schema has no `container` field, while docs describe `"container":"auto"` for tools (only `/code/execute` has it in the OpenAPI).
- **2026-11-08 10:20 · per-user budgets:** end-user budgets (`/keys/{id}/end-users`) need a service key (`403 This endpoint requires a service key.` on `/end-user-budgets`). Unclear how a member sets these up for an app's own users without dashboard access.

- **2026-11-09 14:40 · catalog vs provider (bug):** `/models` lists `response_format` in `supported_parameters` for `alibaba/qwen3-coder-30b-a3b-instruct` and `alibaba/qwen3-coder-480b-a35b-instruct`, but requests with `response_format: {"type":"json_object"}` fail with `'response_format' is not supported for bedrock`. Repro: `POST /chat/completions {"model":"alibaba/qwen3-coder-30b-a3b-instruct","messages":[…],"response_format":{"type":"json_object"}}`. Cost us 4 failed attempts on the first live run. Workaround: retry without `response_format`, remember per model. **Good candidate for an issue on mozilla-ai/otari.**
- **2026-11-09 14:41 · usage naming:** `/key/usage/summary` `by_model` mixes catalog ids (`openai/gpt-oss-20b`) with provider ids (`qwen.qwen3-coder-30b-a3b-v1:0`, `deepseek-ai/DeepSeek-V4-Flash`) and both `code_execution` and `otari:code_execution`, so per-model cost can't be joined back to the model you requested.
- **2026-11-09 14:42 · sandbox pricing:** a `/code/execute` run bills ~$0.0067, ~30× the model calls of a whole fix. The price isn't in `/models` pricing, so we had to measure it from usage. Publishing it, or returning the cost in a response header, would help.
- **2026-11-09 14:43 · reasoning models + max_tokens:** `openai/gpt-oss-20b` with `max_tokens: 20` returned empty `content` (the reasoning tokens use up the budget). Not a bug, but a doc note would help.

- **2026-11-09 17:10 · web search cost visibility:** search charges are folded into the researcher model's row: `openai/gpt-oss-120b` shows $0.186 for 5 calls / 150k tokens (~$0.04/call), while tokens alone would be ~$0.006. Search results add ~30k prompt tokens per call. Neither the search surcharge nor its token impact shows up before the bill. A `max_tokens_per_result`/summary mode and a visible per-search price would help.
- **2026-11-09 17:15 · sandbox price:** real billing is ~$0.0096–0.0100 per `/code/execute` run: 97% of a typical fix. A cheaper "warm container, quick re-run" price tier would favor iterative agents.
- **2026-11-09 17:00 · fetch + reasoning:** after we quarantined a poisoned page and offered only `otari_web_search`, `gpt-oss-120b` returned empty `content` twice (tool loop ended without a final answer). Worked around by skipping research when the only source is compromised.
- **2026-11-09 16:50 · the model was smarter than our guardrail design:** `gpt-oss-120b` read the poisoned changelog via `otari_web_fetch` and silently ignored the injected instructions, so a guardrail placed on its *summary* never fired. We now fetch linked pages with `POST /api/v1/fetch` and screen the raw text first. Otari could expose fetched tool results in the response (or run an inference guardrail on `rag_context`) so apps can audit what the model read.

- **2026-11-09 19:31 · routing policy (worked, with a twist):** `guard-patcher` (Qwen3-Coder-30B on Bedrock → Devstral-2 on Bedrock → Qwen3-Coder-480B-Turbo on DeepInfra) answered on the 3rd backup: both Bedrock targets rejected `response_format`, and Otari treated that as a failure and fell through. It's great that it was absorbed with no code change. But a request-shape error ("parameter not supported by this provider") burns two attempts every time; the gateway could skip providers that can't take the request's parameters.

- **2026-11-09 20:05 · guardrails on hosted (biggest gap):** the policy page offers "Add a guardrail" with profile `prompt-injection`, but hosted Otari has no guardrails service. Repro: `POST /chat/completions` with `"guardrails":[{"profile":"prompt-injection","mode":"block","on_unavailable":"monitor"}]` → served, with header `otari-guardrails: [{"status":"unavailable","reason":"not_configured"}]`; with `on_unavailable:"block"` → `"guardrail profile 'prompt-injection' requested but no guardrails service is configured. Set OTARI_GUARDRAILS_URL…"`. The dashboard lets you save a block/block guardrail on a policy, which would refuse **every** request through it, with no warning that the service is missing. Wanted: a hosted prompt-injection profile backed by an open-weight model (e.g. gpt-oss-safeguard), or at least a disabled state in the UI. We built this ourselves (safeguard step + Agent Guardrails gates).

- **2026-11-09 20:40 · MCP:** inline `mcp_servers` (URL + token in the request) is refused by default: "This workspace does not let a request name MCP servers by URL. Use a stored server through mcp_server_ids". It's a good secure default, and the message said exactly what to do. Registering GitHub's remote MCP server in the dashboard took 2 minutes; `GET /mcp/servers/{id}/tools` listed 46 tools, including `merge_pull_request` and `delete_file`. With a stored server, a request can't narrow `allowed_tools` itself, so least privilege has to be set on the server in the dashboard.

- **2026-11-09 21:30 · Agent Guardrails CLI install:** `otari-agent` (the `otari` CLI) isn't on PyPI (`otari`/`otari-cli` there are other projects), needs Python ≥ 3.13, and the docs reference doesn't say how to install it; we found `brew install mozilla-ai/tap/otari` / `uv tool install <release sdist>` in `cli/README.md`. `otari guardrails validate` also fails outside a git repo ("Not inside a Git repository") even when given a directory with `.otari/`.

## What worked well

- `otari guardrails check --type path --type verifier --guardrails-from <trusted checkout>` was exactly the primitive we needed: a candidate patch staged in a scratch repo, judged by the repo's own gates and verifier scripts, which the patch itself cannot modify. We replaced our hand-rolled checker with it.

- MCP end to end: `mcp_server_ids` + `gpt-oss-120b` opened a real PR (branch, push, PR body = our receipt) in one request. Otari ran the whole tool loop server-side.

- Routing policy created in the dashboard in ~2 minutes; response headers `otari-model`, `otari-provider`, `otari-attempt-count`, `otari-fallback` made it trivial to show routing decisions in our receipts.

- `GET /api/v1/usage/requests/{request_id}` returns the **exact billed cost** per request: receipts are now exact, not estimates.
- `POST /api/v1/fetch` (direct fetch, no model in the loop) made zero-trust research possible: fetch → screen raw → then let a model read it.
- Live benchmark: **9/9 seeded bugs fixed** on hosted Otari, 8 on the first attempt with the cheapest coder model.

- Sandbox ships **Python 3.13 + pytest 9** preinstalled: the repo's own test suite ran first try.
- First real fix end to end: 10 s, ~$0.009 billed (triage → patch → sandbox → review), first attempt.

- OpenAI SDK + `base_url` worked on the first try; `extra_body` carries `guardrails`, `mcp_servers`, `metadata`.
- `/api/v1/openapi.json` is public with a key, and is the single most useful doc (all field names, descriptions).
- `POST /api/v1/code/execute` (direct sandbox, no model in the loop) is perfect for deterministic test verification; `container:"auto"` + `Otari-Container-Id` header for warm reuse.
- `GET /api/v1/key/budget` and `/key/usage/summary` work with a normal key: easy live cost meter + receipt.
- The model catalog has `pricing`, `supported_parameters`, `context_window` per model: cost estimates without guessing.
- `docs.otari.ai/llms.txt` made the docs easy to navigate.

## Built ourselves (Otari could do this)

- A sandbox "ship the repo" layer (base64 files inside the program); Files API upload wasn't needed, but a `files: {path: content}` field on `/code/execute` would remove it.
- Prompt-injection screening of web-fetch results (no hosted guardrail without third-party keys).
- Quality-based escalation ("tests still fail → bigger model"). Routing `on_failure` only covers provider errors; a `retry_on: "app_signal"` / feedback hook would let the gateway own this.
- Per-run cost: we estimate from catalog prices; an `otari-cost` response header would make receipts exact.

## Tempted to skip Otari?

- (fill in during the build)
