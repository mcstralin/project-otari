"""Configuration: .otari-guard.yml + environment variables (+ optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_FILE = ".otari-guard.yml"

# Every model here is open-weight. Each role is a different model on purpose:
# Otari lets us pick the right-sized model per job behind one API.
DEFAULT_MODELS = {
    # Reads the CI log, classifies the failure, decides whether research is needed.
    "triage": "openai/gpt-oss-20b",
    # Writes the candidate fix. Fast, cheap coder model.
    "patcher": "alibaba/qwen3-coder-30b-a3b-instruct",
    # Escalation tier when the cheap patcher keeps failing in the sandbox.
    "patcher_escalation": "alibaba/qwen3-coder-480b-a35b-instruct",
    # Researches external causes with Otari web search/fetch.
    "researcher": "openai/gpt-oss-120b",
    # Open-weight safety model: judges fetched web content for prompt injection.
    "safeguard": "openai/gpt-oss-safeguard-120b",
    # Large reasoning model that reviews the final diff before a PR is opened.
    "reviewer": "deepseek/deepseek-v4-flash",
}

ROLE_DESCRIPTIONS = {
    "triage": "classify failure + decide if research is needed",
    "patcher": "write the candidate fix (cheap tier)",
    "patcher_escalation": "write the fix when the cheap tier fails",
    "researcher": "web search/fetch for external causes",
    "safeguard": "judge fetched content for prompt injection",
    "reviewer": "approve or reject the final diff",
}


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency). Never overrides real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    base_url: str = "https://api.otari.ai/api/v1"
    api_key: str | None = None
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    # Optional Otari routing-policy names. When set, the role calls the policy
    # name instead of a raw model, so Otari resolves (and fails over) server-side.
    policies: dict[str, str] = field(default_factory=dict)
    budget_usd: float = 0.50          # hard cap for one fix run (client-side)
    max_attempts: int = 2             # attempts per patcher tier before escalating
    research: bool = True             # allow web search/fetch
    research_max_uses: int = 2        # Otari max_uses for search per request
    safeguard: bool = True            # run injection judge on fetched content
    inference_guardrails: list[dict] = field(default_factory=list)  # Otari request guardrails
    user: str | None = None           # developer label (cost attribution tag); identity = the API key
    end_user: str | None = None       # sent as `user` only for keys configured with end-user budgets
    sandbox_timeout_s: int = 60
    test_command: str = "pytest -q"
    protected_paths: list[str] = field(default_factory=lambda: [".github/**", ".otari/**"])
    github_repo: str | None = None    # owner/name
    github_token: str | None = None
    github_base: str | None = None    # PR base branch (default: current git branch)
    github_mcp_url: str = "https://api.githubcopilot.com/mcp/"
    use_mcp: bool = True
    mock: bool = False

    def model_for(self, role: str) -> str:
        return self.policies.get(role) or self.models[role]


def load_config(repo: Path, overrides: dict | None = None) -> Config:
    for d in [repo, *repo.parents, Path.cwd()]:   # nearest .env wins
        load_dotenv(d / ".env")
    cfg = Config()
    path = repo / CONFIG_FILE
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, value in data.items():
            if key == "models" and isinstance(value, dict):
                cfg.models.update(value)
            elif hasattr(cfg, key):
                setattr(cfg, key, value)
    cfg.base_url = os.environ.get("OTARI_BASE_URL", cfg.base_url).rstrip("/")
    cfg.api_key = os.environ.get("OTARI_API_KEY") or cfg.api_key
    cfg.github_token = os.environ.get("GITHUB_TOKEN") or cfg.github_token
    cfg.github_repo = os.environ.get("GITHUB_REPOSITORY") or cfg.github_repo
    # e.g. OTARI_GUARD_POLICIES="patcher=guard-patcher,reviewer=guard-reviewer"
    for pair in filter(None, os.environ.get("OTARI_GUARD_POLICIES", "").split(",")):
        role, _, pol = pair.partition("=")
        if role.strip() and pol.strip():
            cfg.policies[role.strip()] = pol.strip()
    cfg.end_user = os.environ.get("OTARI_GUARD_END_USER") or cfg.end_user
    cfg.user = os.environ.get("OTARI_GUARD_USER") or os.environ.get("GITHUB_ACTOR") or cfg.user
    for key, value in (overrides or {}).items():
        if value is not None:
            setattr(cfg, key, value)
    return cfg


DEFAULT_CONFIG_YAML = """\
# Otari-Guard configuration. Every model below is open-weight.
# Point OTARI_BASE_URL at a self-hosted Otari and nothing else changes.
budget_usd: 0.50        # hard stop for a single fix run
max_attempts: 2         # sandbox attempts per patcher tier before escalating
research: true          # Otari web search/fetch for external causes
safeguard: true         # open-weight safety model screens fetched pages
test_command: pytest -q

models:
  triage: openai/gpt-oss-20b
  patcher: alibaba/qwen3-coder-30b-a3b-instruct
  patcher_escalation: alibaba/qwen3-coder-480b-a35b-instruct
  researcher: openai/gpt-oss-120b
  safeguard: openai/gpt-oss-safeguard-120b
  reviewer: deepseek/deepseek-v4-flash

# Optional: call Otari routing policies instead of raw models, so failover
# and budget-aware downgrades happen server-side. See policies/routing.yml.
# policies:
#   patcher: guard-patcher
#   reviewer: guard-reviewer

protected_paths:
  - .github/**
  - .otari/**
"""
