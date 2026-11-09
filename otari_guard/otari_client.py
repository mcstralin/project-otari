"""Thin client for the Otari gateway.

Chat goes through the plain OpenAI SDK pointed at Otari (`base_url`), which is
the whole point: Otari is wire-compatible, so open-weight models, server-side
tools, guardrails and budgets come with no SDK lock-in. Gateway-only endpoints
(sandbox, budget, usage, routing explain) use httpx directly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Config


class OtariError(Exception):
    def __init__(self, message: str, status: int | None = None, code: str | None = None,
                 request_id: str | None = None):
        super().__init__(message)
        self.status, self.code, self.request_id = status, code, request_id


class BudgetExceeded(OtariError):
    """Otari refused the request: org funds, key budget or per-user budget exhausted."""


class GuardrailBlocked(OtariError):
    """An Otari inference guardrail blocked the request."""


class LocalBudgetExceeded(Exception):
    """Otari-Guard's own per-run budget (budget_usd) would be exceeded."""


@dataclass
class CallRecord:
    role: str
    model: str
    request_id: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    kind: str = "chat"            # chat | sandbox
    resolved_model: str | None = None
    provider: str | None = None        # otari-provider header
    attempts: int = 1                  # otari-attempt-count header
    fallback: bool = False             # otari-fallback header
    tools: list[str] = field(default_factory=list)
    ok: bool = True
    note: str = ""


@dataclass
class ChatResult:
    content: str
    record: CallRecord
    raw: dict


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    return_code: int | None
    container_id: str | None
    record: CallRecord


def _map_error(status: int, body: Any, request_id: str | None) -> OtariError:
    detail = body
    code = None
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error") or body
        code = body.get("code")
        if isinstance(detail, dict):
            code = code or detail.get("code")
            detail = detail.get("message") or json.dumps(detail)
    text = str(detail)
    low = (str(code) + " " + text).lower()
    if status == 402 or "budget" in low or "insufficient_funds" in low or "spend" in low and "ceiling" in low:
        return BudgetExceeded(text, status, code, request_id)
    if "guardrail" in low:
        return GuardrailBlocked(text, status, code, request_id)
    return OtariError(text, status, code, request_id)


class OtariClient:
    # Live estimates (observed on hosted Otari, Nov 2026); exact costs are
    # reconciled from /usage/requests/{id} after the run.
    SANDBOX_EST_USD = 0.0096
    FETCH_EST_USD = 0.0067
    SEARCH_EST_USD = 0.012   # per allowed web search, on top of tokens

    def __init__(self, cfg: Config):
        if not cfg.api_key:
            raise OtariError("OTARI_API_KEY is not set (put it in .env or the environment)")
        self.cfg = cfg
        self.http = httpx.Client(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=httpx.Timeout(180.0, connect=15.0),
        )
        from openai import OpenAI  # plain OpenAI SDK, pointed at Otari

        self.oai = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, max_retries=1, timeout=180.0)
        self._pricing: dict[str, tuple[float, float]] | None = None
        self._no_json_mode: set[str] = set()
        self.calls: list[CallRecord] = []

    # ------------------------------------------------------------------ utils
    @property
    def spent_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    def pricing(self) -> dict[str, tuple[float, float]]:
        if self._pricing is None:
            self._pricing = {}
            try:
                for m in self.list_models():
                    p = m.get("pricing") or {}
                    self._pricing[m["id"]] = (
                        float(p.get("input_price_per_million") or 0.0),
                        float(p.get("output_price_per_million") or 0.0),
                    )
            except Exception:
                pass
        return self._pricing

    def estimate(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        pin, pout = self.pricing().get(model, (0.0, 0.0))
        return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000

    def _get(self, path: str, **params) -> Any:
        r = self.http.get(path, params=params or None)
        if r.status_code >= 400:
            raise _map_error(r.status_code, _json(r), r.headers.get("otari-request-id"))
        return r.json()

    def _post(self, path: str, body: dict, headers: dict | None = None) -> httpx.Response:
        r = self.http.post(path, json=body, headers=headers)
        if r.status_code >= 400:
            raise _map_error(r.status_code, _json(r), r.headers.get("otari-request-id"))
        return r

    # --------------------------------------------------------------- gateway
    def list_models(self) -> list[dict]:
        return self._get("/models").get("data", [])

    def list_tools(self) -> list[dict]:
        return self._get("/tools").get("data", [])

    def key_budget(self) -> dict:
        return self._get("/key/budget")

    def key_usage(self) -> dict:
        return self._get("/key/usage/summary")

    def explain_policy(self, name: str | None = None, spec: dict | None = None,
                       budget_used_pct: float | None = None) -> dict:
        body: dict[str, Any] = {"name": name, "spec": spec}
        if budget_used_pct is not None:
            body["budget_used_pct"] = budget_used_pct
        return self._post("/routing/policies/explain", {k: v for k, v in body.items() if v is not None}).json()

    # ------------------------------------------------------------------ chat
    def chat(self, role: str, messages: list[dict], *, model: str | None = None,
             tools: list[dict] | None = None, guardrails: list[dict] | None = None,
             mcp_servers: list[dict] | None = None, json_mode: bool = False,
             max_tokens: int | None = None, temperature: float | None = 0.2,
             metadata: dict | None = None) -> ChatResult:
        model = model or self.cfg.model_for(role)
        self._check_local_budget()
        extra: dict[str, Any] = {}
        if guardrails:
            extra["guardrails"] = guardrails
        if mcp_servers:
            extra["mcp_servers"] = mcp_servers
        tags = {"app": "otari-guard", "role": role}
        if self.cfg.user:
            tags["developer"] = self.cfg.user
        tags.update(metadata or {})
        extra["metadata"] = {k: str(v)[:512] for k, v in tags.items()}
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "extra_body": extra}
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        if self.cfg.end_user:
            kwargs["user"] = self.cfg.end_user  # end-user budget on this key

        from openai import APIStatusError

        if model in self._no_json_mode:
            kwargs.pop("response_format", None)
        t0 = time.time()
        try:
            try:
                raw = self.oai.chat.completions.with_raw_response.create(**kwargs)
            except APIStatusError as e:
                # The catalog advertises response_format for some models whose upstream
                # provider rejects it (seen with Bedrock-served Qwen coders). Retry once
                # without it; prompts already demand JSON and parse_json() recovers it.
                if "response_format" in kwargs and "response_format" in str(_json(e.response)):
                    self._no_json_mode.add(model)
                    kwargs.pop("response_format")
                    raw = self.oai.chat.completions.with_raw_response.create(**kwargs)
                else:
                    raise
        except APIStatusError as e:  # map gateway refusals to typed errors
            rid = e.response.headers.get("otari-request-id") if e.response is not None else None
            err = _map_error(e.status_code, _json(e.response), rid)
            self.calls.append(CallRecord(role, model, rid, ok=False, latency_s=time.time() - t0,
                                         tools=[t.get("type", "") for t in tools or []], note=str(err)[:200]))
            raise err from None
        resp = raw.parse()
        rid = raw.headers.get("otari-request-id")
        usage = resp.usage
        pt = getattr(usage, "prompt_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", 0) or 0
        resolved = raw.headers.get("otari-model") or getattr(resp, "model", None) or model
        search_surcharge = sum(self.SEARCH_EST_USD * int(t.get("max_uses") or 1)
                               for t in tools or [] if t.get("type") == "otari_web_search")
        rec = CallRecord(
            role=role, model=model, request_id=rid, prompt_tokens=pt, completion_tokens=ct,
            cost_usd=self.estimate(model if model in self.pricing() else resolved, pt, ct) + search_surcharge,
            latency_s=time.time() - t0, resolved_model=resolved,
            tools=[t.get("type", "") for t in tools or []],
            provider=raw.headers.get("otari-provider"),
            attempts=int(raw.headers.get("otari-attempt-count") or 1),
            fallback=(raw.headers.get("otari-fallback") or "").lower() == "true",
        )
        self.calls.append(rec)
        content = resp.choices[0].message.content or ""
        return ChatResult(content=content, record=rec, raw=resp.model_dump())

    # ---------------------------------------------------------------- fetch
    def fetch(self, url: str, max_chars: int = 20000, role: str = "fetch") -> dict:
        """Fetch one page through Otari (POST /fetch) so the raw text can be screened
        before any agent model reads it."""
        self._check_local_budget()
        body: dict[str, Any] = {"url": url, "max_chars": max_chars}
        if self.cfg.end_user:
            body["user"] = self.cfg.end_user
        t0 = time.time()
        try:
            r = self._post("/fetch", body)
        except OtariError as e:
            self.calls.append(CallRecord(role, "otari:web_fetch", e.request_id, kind="fetch", ok=False,
                                         latency_s=time.time() - t0, note=str(e)[:200]))
            raise
        self.calls.append(CallRecord(role, "otari:web_fetch", r.headers.get("otari-request-id"), kind="fetch",
                                     cost_usd=self.FETCH_EST_USD, latency_s=time.time() - t0))
        return r.json()

    # --------------------------------------------------------------- sandbox
    def execute(self, code: str, *, container: str | None = "auto", timeout_s: int | None = None,
                role: str = "sandbox") -> SandboxResult:
        """Run Python in Otari's sandbox (POST /code/execute). `container: auto`
        keeps the sandbox warm so repeated fix attempts reuse files/state."""
        self._check_local_budget()
        body: dict[str, Any] = {"code": code}
        if container:
            body["container"] = container
        if timeout_s:
            body["timeout_seconds"] = timeout_s
        if self.cfg.end_user:
            body["user"] = self.cfg.end_user
        t0 = time.time()
        try:
            r = self._post("/code/execute", body)
        except OtariError as e:
            self.calls.append(CallRecord(role, "otari:code_execution", e.request_id, kind="sandbox",
                                         ok=False, latency_s=time.time() - t0, note=str(e)[:200]))
            raise
        data = r.json()
        rec = CallRecord(role, "otari:code_execution", r.headers.get("otari-request-id"), kind="sandbox",
                         cost_usd=self.SANDBOX_EST_USD, latency_s=time.time() - t0)
        self.calls.append(rec)
        return SandboxResult(
            stdout=data.get("stdout", ""), stderr=data.get("stderr", ""),
            return_code=data.get("return_code"),
            container_id=r.headers.get("otari-container-id"), record=rec,
        )

    def reconcile(self) -> float:
        """Replace estimates with the exact cost Otari billed for each request."""
        exact = 0
        for c in self.calls:
            if not c.request_id:
                continue
            try:
                d = self._get(f"/usage/requests/{c.request_id}")
                c.cost_usd = float(d.get("cost_usd") or 0.0)
                c.note = (c.note + " billed").strip()
                exact += 1
            except Exception:
                continue
        self.reconciled = exact
        return self.spent_usd

    def _check_local_budget(self) -> None:
        if self.spent_usd >= self.cfg.budget_usd:
            raise LocalBudgetExceeded(
                f"run budget ${self.cfg.budget_usd:.2f} reached (spent ${self.spent_usd:.4f})")


def _json(resp: Any) -> Any:
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception:
        try:
            return resp.text
        except Exception:
            return None
