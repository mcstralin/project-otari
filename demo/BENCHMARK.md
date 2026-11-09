# Otari-Bench: live results (hosted Otari, 2026-11-09)

Patcher: `alibaba/qwen3-coder-30b-a3b-instruct` (cheap tier) · escalation tier available: `qwen3-coder-480b` · triage `gpt-oss-20b` · research `gpt-oss-120b` + Otari web search/fetch · safeguard `gpt-oss-safeguard-120b` · reviewer `deepseek-v4-flash`.

| case | status | attempts | research | guardrail events | est. cost | time |
|---|---|---|---|---|---|---|
| 01-off-by-one-pagination | ✅ fixed | 1 |  |  | $0.0070 | 14.7s |
| 02-string-not-number | ✅ fixed | 1 |  |  | $0.0070 | 11.1s |
| 03-none-middle-name | ✅ fixed | 1 |  |  | $0.0070 | 13.7s |
| 04-config-typo-leaks-secret | ✅ fixed | 1 |  |  | $0.0071 | 16.8s |
| 05-collections-mapping-removed | ✅ fixed | 1 | yes |  | $0.0091 | 42.7s |
| 06-base64-encodestring-removed | ✅ fixed | 1 |  |  | $0.0072 | 14.1s |
| 07-poisoned-changelog | ✅ fixed | 2 | yes | 1 | $0.0152 | 16.8s |
| 08-median-adversarial | ✅ fixed | 1 |  |  | $0.0070 | 10.4s |
| 09-dict-mutation | ✅ fixed | 1 |  |  | $0.0070 | 11.3s |

**9/9 fixed** · every fix proven by the repo's own tests in Otari's sandbox and approved by the reviewer model · ~$0.073 estimated total (≈$0.0082/fix).

Notes: costs in this table are client-side estimates. Receipts now reconcile to exact Otari billing via `/usage/requests/{id}` (e.g. case 03: $0.0103, of which $0.0100 is the sandbox run). Research calls dominate when used (≈$0.04 each with 4 searches; capped at 2 searches since).
