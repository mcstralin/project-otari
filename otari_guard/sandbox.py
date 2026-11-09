"""Builds the Python program that reproduces the test run inside Otari's sandbox.

The sandbox is a Python REPL, so we ship the repo as base64-encoded files inside
the program itself, then run the tests. With `container: auto` the first attempt
seeds every file and later attempts only send the files that changed.
If pytest is not installed in the sandbox we try pip, then fall back to a tiny
built-in runner so verification never silently stops.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

MARK = "@@OTARI_GUARD_RESULT@@"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
WORKDIR = "/tmp/otari_guard_repo"

_RUNNER = r'''
import base64, json, os, subprocess, sys, traceback, importlib, io, contextlib
WORK = __WORK__
FILES = json.loads(base64.b64decode(__FILES__).decode())
DELETE = json.loads(base64.b64decode(__DELETE__).decode())
if __RESET__:
    import shutil
    shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)
for rel, b64 in FILES.items():
    p = os.path.join(WORK, rel)
    os.makedirs(os.path.dirname(p) or WORK, exist_ok=True)
    with open(p, "wb") as f:
        f.write(base64.b64decode(b64))
for rel in DELETE:
    p = os.path.join(WORK, rel)
    if os.path.exists(p):
        os.remove(p)

def has_pytest():
    return subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True).returncode == 0

runner = "pytest"
if not has_pytest():
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pytest"], capture_output=True, timeout=40)
    if not has_pytest():
        runner = "mini"


def run_once():
    if runner == "pytest":
        args = __ARGS__
        p = subprocess.run([sys.executable, "-m", "pytest", *args], cwd=WORK, capture_output=True, text=True,
                           timeout=__TIMEOUT__,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PY_COLORS": "0", "NO_COLOR": "1"})
        return (p.stdout or "") + (p.stderr or ""), p.returncode
    # Minimal fallback runner (fresh process per run, like pytest): test_* functions, plain asserts.
    code = r"""
import importlib, io, os, sys, traceback
WORK = sys.argv[1]; sys.path.insert(0, WORK)
buf, failed, ran = io.StringIO(), 0, 0
for root, _, names in os.walk(WORK):
    for n in sorted(names):
        if n.startswith("test_") and n.endswith(".py"):
            rel = os.path.relpath(os.path.join(root, n), WORK)
            try:
                m = importlib.import_module(rel[:-3].replace(os.sep, "."))
            except Exception:
                failed += 1; buf.write(f"ERROR collecting {rel}\\n{traceback.format_exc()}\\n"); continue
            for attr in sorted(dir(m)):
                fn = getattr(m, attr)
                if attr.startswith("test_") and callable(fn):
                    ran += 1
                    try:
                        fn()
                    except Exception:
                        failed += 1; buf.write(f"FAILED {rel}::{attr}\\n{traceback.format_exc()}\\n")
print(buf.getvalue() + f"\\n{ran - failed} passed, {failed} failed (mini runner)")
sys.exit(1 if failed or not ran else 0)
"""
    p = subprocess.run([sys.executable, "-c", code, WORK], capture_output=True, text=True, timeout=__TIMEOUT__)
    return (p.stdout or "") + (p.stderr or ""), p.returncode


codes, first_fail, out = [], None, ""
for _ in range(__REPEAT__):
    o, c = run_once()
    codes.append(c)
    out = o
    if c != 0 and first_fail is None:
        first_fail = o
if first_fail is not None and codes[-1] == 0:
    out = first_fail  # show a failing run's output when the last run happened to pass
code = 0 if all(c == 0 for c in codes) else codes[-1] if codes[-1] != 0 else 1

print(out[-12000:])
print(__MARK__ + json.dumps({"return_code": code, "codes": codes, "runner": runner,
                              "python": sys.version.split()[0]}))
'''


@dataclass
class SandboxOutcome:
    passed: bool
    output: str
    runner: str
    python: str
    return_code: int | None
    codes: list[int] | None = None   # one exit code per repeated run

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.codes or [] if c == 0)


def _b64(obj: object) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def build_program(files: dict[str, str], delete: list[str] | None = None,
                  test_command: str = "pytest -q", timeout: int = 50, reset: bool = True,
                  repeat: int = 1) -> str:
    args = test_command.split()[1:] if test_command.split()[:1] == ["pytest"] else ["-q"]
    args = [*args, "--color=no", "-p", "no:cacheprovider"]
    enc = {k: base64.b64encode(v.encode()).decode() for k, v in files.items()}
    return (_RUNNER.replace("__WORK__", repr(WORKDIR))
            .replace("__FILES__", repr(_b64(enc)))
            .replace("__DELETE__", repr(_b64(delete or [])))
            .replace("__ARGS__", repr(args))
            .replace("__TIMEOUT__", str(int(timeout)))
            .replace("__MARK__", repr(MARK))
            .replace("__RESET__", repr(bool(reset)))
            .replace("__REPEAT__", str(max(1, int(repeat)))))


def parse_output(stdout: str, stderr: str = "", return_code: int | None = None) -> SandboxOutcome:
    meta: dict = {}
    text = stdout
    if MARK in stdout:
        text, _, tail = stdout.rpartition(MARK)
        try:
            meta = json.loads(tail.strip().splitlines()[0])
        except (json.JSONDecodeError, IndexError):
            meta = {}
    code = meta.get("return_code", return_code)
    text = ANSI.sub("", text)
    out = (text + ("\n" + stderr if stderr else "")).strip()
    return SandboxOutcome(passed=code == 0, output=out, runner=meta.get("runner", "?"),
                          python=meta.get("python", "?"), return_code=code, codes=meta.get("codes"))
