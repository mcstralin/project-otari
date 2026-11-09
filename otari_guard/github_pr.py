"""Opening the pull request: GitHub MCP through Otari first, GitHub REST as fallback.

MCP path: Otari connects to GitHub's remote MCP server (streamable HTTP) inline,
with `allowed_tools` restricted to the three tools a PR needs, so the model can
open a PR and nothing else. REST path: deterministic, same result.
"""

from __future__ import annotations

import base64
import json
import time

import httpx

from .config import Config

MCP_TOOLS = ["create_branch", "create_or_update_file", "push_files", "create_pull_request"]


class PRError(Exception):
    pass


def open_pr_rest(cfg: Config, changes: dict[str, str | None], title: str, body: str,
                 base: str | None = None) -> str:
    if not (cfg.github_token and cfg.github_repo):
        raise PRError("GITHUB_TOKEN and github_repo (owner/name) are required to open a PR")
    gh = httpx.Client(base_url="https://api.github.com", timeout=30, headers={
        "Authorization": f"Bearer {cfg.github_token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    repo = cfg.github_repo

    def ok(r: httpx.Response) -> dict:
        if r.status_code >= 400:
            raise PRError(f"GitHub {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    base = base or ok(gh.get(f"/repos/{repo}"))["default_branch"]
    sha = ok(gh.get(f"/repos/{repo}/git/ref/heads/{base}"))["object"]["sha"]
    branch = f"otari-guard/fix-{int(time.time())}"
    ok(gh.post(f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha}))
    for path, content in changes.items():
        cur = gh.get(f"/repos/{repo}/contents/{path}", params={"ref": branch})
        file_sha = cur.json().get("sha") if cur.status_code == 200 else None
        if content is None:
            if file_sha:
                ok(gh.request("DELETE", f"/repos/{repo}/contents/{path}", json={
                    "message": f"otari-guard: delete {path}", "sha": file_sha, "branch": branch}))
            continue
        payload = {"message": f"otari-guard: fix {path}", "branch": branch,
                   "content": base64.b64encode(content.encode()).decode()}
        if file_sha:
            payload["sha"] = file_sha
        ok(gh.put(f"/repos/{repo}/contents/{path}", json=payload))
    pr = ok(gh.post(f"/repos/{repo}/pulls", json={"title": title, "head": branch, "base": base, "body": body}))
    return pr["html_url"]


def open_pr_mcp(cfg: Config, client, changes: dict[str, str | None], title: str, body: str,
                base: str = "main") -> str:
    """Let a model open the PR through GitHub's MCP server, connected by Otari."""
    if not (cfg.github_token and cfg.github_repo):
        raise PRError("GITHUB_TOKEN and github_repo are required for the GitHub MCP server")
    owner, name = cfg.github_repo.split("/", 1)
    branch = f"otari-guard/fix-{int(time.time())}"
    files = [{"path": p, "content": c} for p, c in changes.items() if c is not None]
    server = {
        "name": "github", "url": cfg.github_mcp_url, "authorization_token": cfg.github_token,
        "purpose_hint": "GitHub repository operations for opening a pull request.",
        "allowed_tools": MCP_TOOLS,
    }
    task = (f"In repository {owner}/{name}: 1) create branch `{branch}` from `{base}`; "
            f"2) push these files to that branch in one commit with message 'otari-guard: fix failing tests'; "
            f"3) open a pull request from `{branch}` into `{base}` with the exact title and body below. "
            "Do nothing else. Reply ONLY with JSON {\"pr_url\": \"...\"}.\n\n"
            f"FILES (JSON): {json.dumps(files)}\n\nTITLE: {title}\n\nBODY:\n{body}")
    res = client.chat("pr", [{"role": "user", "content": task}], model=cfg.model_for("triage"),
                      mcp_servers=[server], temperature=0)
    text = res.content
    try:
        start, end = text.find("{"), text.rfind("}")
        url = json.loads(text[start:end + 1]).get("pr_url", "")
    except (ValueError, json.JSONDecodeError):
        url = ""
    if not url.startswith("https://github.com/"):
        raise PRError(f"MCP did not return a PR URL: {text[:200]}")
    return url
