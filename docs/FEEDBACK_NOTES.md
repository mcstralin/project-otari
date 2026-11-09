# Feedback talking points (put these in your own words; no AI voice or AI-written video)

The full evidence log with repro steps is in `FEEDBACK_LOG.md`. These are bullet prompts, not a script.

## Feedback video (3–5 min, screen recording)

**1. What did you build, and which features did you use?** (show the README rubric table + one run)
- Otari-Guard: self-healing CI on 6 open-weight models.
- Features: code execution (`/code/execute`), web search + fetch (in-loop and direct `/fetch`), routing policy with fallbacks + budget tier-down, key budgets / per-developer keys, MCP (stored GitHub server), exact billing via `/usage/requests/{id}`.

**2. What worked well? What surprised you?**
- OpenAI SDK + `base_url` worked on the first try.
- Sandbox had Python 3.13 + pytest preinstalled; `container:"auto"` for warm reuse.
- Response headers (`otari-model`, `otari-fallback`, `otari-attempt-count`) made routing visible.
- `/tools` says exactly *why* a tool is unavailable (`workspace_disabled`).
- Surprise: a real fallback fired on its own (Bedrock rejected the request → DeepInfra).
- Surprise: `gpt-oss-120b` ignored the poisoned page's injection by itself.
- Secure defaults: inline MCP refused, stored-server route suggested in the error.

**3. What didn't work?** (reproduce on screen if you can)
- Issue #3060: `response_format` advertised for Bedrock Qwen coders but rejected. Show the curl.
- Guardrails: the policy page offers `prompt-injection`, but hosted has no guardrails service, and block/block would refuse every request. Show the `otari-guardrails: not_configured` header.
- "Invalid master key" on admin endpoints with a normal key: confusing message.
- Started with $0.00 balance; web search off by default.

**4. What's missing / what would you change?**
- A hosted prompt-injection guardrail on an open-weight model (e.g. gpt-oss-safeguard).
- Cost in a response header; visible per-search and per-sandbox prices.
- Usage `by_model` keys that match the requested catalog id.
- Routing that skips providers that can't accept the request's parameters.
- A `files` field on `/code/execute`.

## Written feedback (answer in your own words)

**When were you most tempted to skip Otari and call the provider directly? What happened?**
Notes: the first live run, when every Qwen coder call failed on `response_format` and the cause wasn't obvious; and when research costs came out ~7× higher than the token estimate because search charges are folded into the model's line.

**What did you end up building yourself that Otari should've done for you?**
Notes: prompt-injection screening (no hosted guardrail service); exact per-run cost tracking (joining request IDs to `/usage/requests`); shipping repo files into the sandbox; quality-based escalation (tests fail → bigger model), since `on_failure` only covers provider errors.

**If the rules hadn't required Otari, would you have kept using it? Why or why not?**
Notes: (your honest view) e.g. yes for one key across many open-weight models, server-side sandbox/search/MCP, routing and budgets without code; the guardrail gap and pricing visibility are what would need fixing for production.
