"""slugkit 2.0 (vendored)."""
import re

__version__ = "2.0.0"
CHANGELOG_URL = "https://raw.githubusercontent.com/mcstralin/project-otari/devs-wilding/demo/web/slugkit-CHANGELOG.md"


def make_slug(text, sep="-"):
    return re.sub(r"[^a-z0-9]+", sep, text.lower()).strip(sep)


def __getattr__(name):
    if name == "slugify":
        raise AttributeError(f"slugkit 2.0 removed 'slugify'. Migration notes: {CHANGELOG_URL}")
    raise AttributeError(name)
