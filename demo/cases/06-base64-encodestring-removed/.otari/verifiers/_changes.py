"""Shared helper for the verifiers: what changed between HEAD and the working tree."""
import subprocess


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def changes():
    """Yield (status, path, old_text, new_text) for every changed file (staged or not)."""
    out = git("diff", "HEAD", "--name-status", "--no-renames")
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        old = new = None
        if status != "A":
            try:
                old = git("show", f"HEAD:{path}")
            except subprocess.CalledProcessError:
                old = None
        if status != "D":
            try:
                with open(path, encoding="utf-8") as f:
                    new = f.read()
            except OSError:
                new = None
        yield status, path, old, new
