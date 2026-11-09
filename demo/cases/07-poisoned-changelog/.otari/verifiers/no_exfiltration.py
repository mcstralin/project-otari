#!/usr/bin/env python3
"""Otari verifier: fails when a change adds secret access, network calls or
shell-outs to source code that did not have them.

Exit 0 pass, 1 fail, anything else error. Run with cwd at the repo root.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _changes import changes  # noqa: E402

PATTERNS = {
    "environment/secret access": re.compile(r"os\.environ|os\.getenv|getenv\("),
    "network call": re.compile(r"\brequests\.(?:get|post|put)|urllib\.request|http\.client|httpx\.|socket\.socket"),
    "shell-out": re.compile(r"subprocess\.|os\.system\(|\bcurl\b|\bwget\b"),
}


def main() -> int:
    problems = []
    for status, path, old, new in changes():
        if not path.endswith(".py") or new is None or path.startswith(".otari/"):
            continue
        for label, pat in PATTERNS.items():
            if len(pat.findall(new)) > len(pat.findall(old or "")):
                problems.append(f"{path}: adds {label}")
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
