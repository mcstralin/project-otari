import shutil
from pathlib import Path

import pytest

from otari_guard.agent import Agent, make_diff, parse_json
from otari_guard.config import load_config
from otari_guard.guardrails import check_patch
from otari_guard.mock import MockClient
from otari_guard.redact import redact
from otari_guard.sandbox import MARK, build_program, parse_output

CASES = Path(__file__).resolve().parent.parent / "demo" / "cases"


def test_redacts_common_secrets():
    log = ("token ghp_" + "a" * 36 + " key otk_abcdefghij1234 aws AKIA" + "B" * 16 +
           " API_KEY=supersecretvalue url https://bob:hunter22@host/x")
    out, counts = redact(log)
    assert "ghp_" not in out and "otk_abc" not in out and "AKIA" not in out
    assert "supersecretvalue" not in out and "hunter22" not in out
    assert counts["github_token"] == 1 and counts["otari_key"] == 1


def test_parse_json_recovers_fenced_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"b": [1, 2]} hope that helps') == {"b": [1, 2]}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_guardrails_block_cheats(tmp_path):
    (tmp_path / ".otari").mkdir()
    (tmp_path / ".otari" / "guardrails.yml").write_text(
        "gates:\n  - id: no-ci\n    type: path\n    enforcement: required\n    forbidden: ['.github/**']\n")
    original = {"tests/test_a.py": "def test_a():\n    assert f() == 1\n\ndef test_b():\n    assert g()\n",
                "src.py": "def f():\n    return 2\n"}
    rep = check_patch(tmp_path, original, {"tests/test_a.py": "def test_a():\n    assert f() == 1\n"}, [])
    assert rep.blocked and any(v.gate == "no-test-deletion" for v in rep.violations)
    rep = check_patch(tmp_path, original, {".github/workflows/ci.yml": "on: push"}, [])
    assert rep.blocked and any(v.gate == "no-ci" for v in rep.violations)
    rep = check_patch(tmp_path, original, {"src.py": "import os\ndef f():\n    return len(os.environ)\n"}, [])
    assert rep.blocked and any(v.gate == "no-exfiltration" for v in rep.violations)
    rep = check_patch(tmp_path, original, {"tests/test_a.py": original["tests/test_a.py"].replace(
        "def test_b", "@pytest.mark.skip\ndef test_b")}, [])
    assert rep.blocked and any(v.gate == "no-new-skips" for v in rep.violations)
    rep = check_patch(tmp_path, original, {"src.py": "def f():\n    return 1\n"}, [])
    assert not rep.blocked


def test_sandbox_program_runs_locally(tmp_path):
    import subprocess
    import sys
    files = {"m.py": "def f():\n    return 1\n", "test_m.py": "from m import f\ndef test_f():\n    assert f() == 1\n"}
    prog = tmp_path / "p.py"
    prog.write_text(build_program(files))
    p = subprocess.run([sys.executable, str(prog)], capture_output=True, text=True)
    assert MARK in p.stdout
    assert parse_output(p.stdout, p.stderr, p.returncode).passed


def test_make_diff():
    d = make_diff({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
    assert "-x = 1" in d and "+x = 2" in d


@pytest.mark.parametrize("case", ["01-off-by-one-pagination", "07-poisoned-changelog", "08-median-adversarial"])
def test_mock_end_to_end(tmp_path, case):
    work = tmp_path / case
    shutil.copytree(CASES / case, work)
    cfg = load_config(work, {"mock": True, "budget_usd": 1.0})
    res = Agent(cfg, MockClient(cfg, work), work, adversarial=(work / ".adversarial").exists()).run()
    assert res.status == "fixed", res.error
    assert res.diff
    if case == "07-poisoned-changelog":
        assert res.research.get("quarantined_sources") or res.research.get("quarantined")
        assert any("quarantined" in g for g in res.guardrail_events)
    if case == "08-median-adversarial":
        assert any("guardrail rejected" in g for g in res.guardrail_events)


def test_budget_stop(tmp_path):
    work = tmp_path / "c"
    shutil.copytree(CASES / "01-off-by-one-pagination", work)
    cfg = load_config(work, {"mock": True, "budget_usd": 0.001})
    res = Agent(cfg, MockClient(cfg, work), work).run()
    assert res.status == "budget_stopped"


def test_redaction_on_secret_case(tmp_path):
    work = tmp_path / "c"
    shutil.copytree(CASES / "04-config-typo-leaks-secret", work)
    cfg = load_config(work, {"mock": True, "budget_usd": 1.0})
    res = Agent(cfg, MockClient(cfg, work), work).run()
    assert res.redactions.get("github_token", 0) >= 1
    assert "ghp_" not in res.failing_before
