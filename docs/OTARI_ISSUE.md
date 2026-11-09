<!-- Draft for https://github.com/mozilla-ai/otari/issues/new. Edit in your own words before posting. -->

**Title:** `/models` advertises `response_format` for Bedrock-served Qwen coder models, but requests with it fail

**What happened**

`GET /api/v1/models` lists `"response_format"` in `supported_parameters` for:

- `alibaba/qwen3-coder-30b-a3b-instruct`
- `alibaba/qwen3-coder-480b-a35b-instruct`

but a chat completion that sets it fails:

```bash
curl -s https://api.otari.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OTARI_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"alibaba/qwen3-coder-30b-a3b-instruct",
       "messages":[{"role":"user","content":"Reply with {\"ok\": true}"}],
       "response_format":{"type":"json_object"}}'
```

→ error: `'response_format' is not supported for bedrock. Check the following links: ...`

**Expected:** either the catalog omits `response_format` for these models (so clients can feature-detect), or the gateway drops/emulates it for providers that don't support it.

**Impact:** clients that trust `supported_parameters` fail on every call. We retry without `response_format` and cache the result per model.

**Context:** found while building Otari-Guard for MozFest Developers Wilding (hosted Otari, 2026-11-09).
