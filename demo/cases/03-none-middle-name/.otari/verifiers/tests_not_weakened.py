#!/usr/bin/env python3
"""Otari verifier: fails when a change weakens the test suite.

Exit 0 pass, 1 fail, anything else error (Otari Agent Guardrails contract).
Run with cwd at the repo root.
"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _changes import changes  # noqa: E402

SKIP = re.compile(r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|unittest\.skip|@skip\b")


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}"


def tests(src: str) -> set:
    try:
        return {n.name for n in ast.walk(ast.parse(src))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")}
    except SyntaxError:
        return set(re.findall(r"def (test_\w+)", src))


def asserts(src: str) -> int:
    try:
        n = sum(isinstance(x, ast.Assert) for x in ast.walk(ast.parse(src)))
    except SyntaxError:
        n = src.count("assert ")
    return n + src.count("pytest.raises")


def main() -> int:
    problems = []
    for status, path, old, new in changes():
        if not is_test(path) or not path.endswith(".py"):
            continue
        if status == "D" or new is None:
            problems.append(f"deletes test file {path}")
            continue
        if old is None:
            continue
        if tests(old) - tests(new):
            problems.append(f"removes {sorted(tests(old) - tests(new))} from {path}")
        if len(SKIP.findall(new)) > len(SKIP.findall(old)):
            problems.append(f"adds skip/xfail markers in {path}")
        if asserts(new) < asserts(old):
            problems.append(f"removes assertions from {path}")
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
