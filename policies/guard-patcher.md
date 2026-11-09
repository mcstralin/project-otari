# Otari routing policy: `guard-patcher`

Created on the Otari dashboard (Routing → Policies → Create policy). Otari-Guard calls it by
name: set `OTARI_GUARD_POLICIES=patcher=guard-patcher` (env) or `policies: {patcher: guard-patcher}`
in `.otari-guard.yml`.

| setting | value |
|---|---|
| Main model | `alibaba/qwen3-coder-30b-a3b-instruct` (Amazon Bedrock) |
| Fallback 1 | `mistralai/devstral-2-123b` (Amazon Bedrock) |
| Fallback 2 | `alibaba/qwen3-coder-480b-a35b-instruct-turbo` (DeepInfra) |
| Budget tier-down | at ≥ 80 % of the key's budget used → `openai/gpt-oss-20b` (DeepInfra) |
| Guardrails | none: hosted Otari has no guardrails service (see FEEDBACK_LOG.md) |

Two layers of escalation:
- **Otari (server-side):** provider/model failures fall through the chain; budget pressure tiers down.
  Every response carries `otari-model`, `otari-provider`, `otari-attempt-count` and `otari-fallback`
  headers, which Otari-Guard shows in its timeline and receipt.
- **Otari-Guard (client-side):** when tests still fail in the sandbox after `max_attempts`, it
  escalates from the `patcher` role to `patcher_escalation` (`qwen3-coder-480b`).

Observed live (2026-11-09): both Bedrock targets rejected the request (`response_format`,
mozilla-ai/otari#3060) and Otari served it from fallback 2 with no client change.
