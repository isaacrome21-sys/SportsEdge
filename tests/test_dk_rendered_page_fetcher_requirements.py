"""Every third-party dependency of the DK rendered-page fetcher must be listed.

Covers module imports and BeautifulSoup parser backends named by string
(e.g. BeautifulSoup(html, "lxml") needs the lxml distribution).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "sportsedge" / "dk_rendered_page_fetcher.py"
DIST_FOR_MODULE = {"bs4": "beautifulsoup4", "yaml": "PyYAML", "PIL": "Pillow"}
BS4_PARSER_DIST = {"lxml": "lxml", "lxml-xml": "lxml", "xml": "lxml", "html5lib": "html5lib"}
# imported only lazily inside the browser path, which the offline tests replace with a fake
RESEARCH_ONLY = {"playwright"}


def _listed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(re.split(r"[<>=!~\[ ;]", line, 1)[0].lower())
    return out


def _third_party_deps() -> set[str]:
    tree = ast.parse(MODULE.read_text())
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    deps = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for n in names:
            top = n.split(".")[0]
            if top not in stdlib and top != "sportsedge":
                deps.add(DIST_FOR_MODULE.get(top, top))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "BeautifulSoup":
            for arg in node.args[1:2]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    deps.add(BS4_PARSER_DIST.get(arg.value, arg.value))
    return {d.lower() for d in deps}


def test_every_third_party_dependency_is_listed():
    deps = _third_party_deps()
    assert {"beautifulsoup4", "lxml", "playwright"} <= deps
    listed = _listed(ROOT / "requirements-research.txt") | _listed(ROOT / "requirements-test.txt")
    assert deps - listed == set(), f"unlisted: {sorted(deps - listed)}"


def test_deps_used_by_offline_tests_are_in_requirements_test():
    test_listed = _listed(ROOT / "requirements-test.txt")
    missing = {d for d in _third_party_deps() if d not in RESEARCH_ONLY} - test_listed
    assert missing == set(), f"needed by offline tests but not in requirements-test.txt: {sorted(missing)}"


def test_lxml_is_pinned_exactly():
    pins = [l for l in (ROOT / "requirements-test.txt").read_text().splitlines() if l.lower().startswith("lxml")]
    assert len(pins) == 1 and re.fullmatch(r"lxml==\d+\.\d+\.\d+", pins[0].strip())
