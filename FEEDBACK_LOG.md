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

## What worked well

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
