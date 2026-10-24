"""screen_only() opens the unrestricted (NAIVE_FAIL-inclusive) pricing paths. Only the
research screens and tests may enter it: any call outside research/ and tests/ fails."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TOPS = {"research", "tests"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}


def _calls_screen_only(src: str) -> list:
    hits = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name == "screen_only":
                hits.append(n.lineno)
        # `from ... import screen_only as x` then x(): catch the aliased import itself
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == "screen_only" and a.asname not in (None, "screen_only"):
                    hits.append(n.lineno)
    return hits


def _offenders(root: Path) -> list:
    out = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        if rel.parts[0] in ALLOWED_TOPS or SKIP_DIRS & set(rel.parts):
            continue
        try:
            src = p.read_text(encoding="utf-8")
            hits = _calls_screen_only(src)
        except (SyntaxError, UnicodeDecodeError):
            continue
        out += [f"{rel}:{ln}" for ln in hits]
    return sorted(out)


def test_no_screen_only_call_outside_research_and_tests():
    assert _offenders(ROOT) == []


def test_detector_catches_calls(tmp_path):
    (tmp_path / "sportsedge").mkdir()
    (tmp_path / "sportsedge" / "a.py").write_text(
        "from sportsedge.screen_only_guard import screen_only\nwith screen_only():\n    pass\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "b.py").write_text(
        "import sportsedge.screen_only_guard as g\nwith g.screen_only():\n    pass\n")
    (tmp_path / "scripts" / "c.py").write_text(
        "from sportsedge.screen_only_guard import screen_only as so\nwith so():\n    pass\n")
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "ok.py").write_text(
        "from sportsedge.screen_only_guard import screen_only\nwith screen_only():\n    pass\n")
    assert _offenders(tmp_path) == ["scripts/b.py:2", "scripts/c.py:1", "sportsedge/a.py:2"]


def test_guard_module_defines_but_does_not_call():
    src = (ROOT / "sportsedge" / "screen_only_guard.py").read_text(encoding="utf-8")
    assert "def screen_only" in src and _calls_screen_only(src) == []
