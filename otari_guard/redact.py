"""Secret redaction: CI logs and source never reach a model with credentials in them."""

from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("otari_key", re.compile(r"otk_[A-Za-z0-9_\-]{8,}")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("stripe_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----")),
    ("url_credentials", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")),
    # KEY=value / "password": "value" style assignments for secret-looking names
    ("assigned_secret", re.compile(
        r"(?i)(?<![A-Za-z0-9])((?:[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY))"
        r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{6,})")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return (redacted_text, counts_by_type)."""
    counts: dict[str, int] = {}
    for name, pat in PATTERNS:
        def sub(m: re.Match[str], _name: str = name) -> str:
            counts[_name] = counts.get(_name, 0) + 1
            if _name == "assigned_secret":
                return f"{m.group(1)}[REDACTED:{_name}]"
            return f"[REDACTED:{_name}]"
        text = pat.sub(sub, text)
    return text, counts
