"""t255: the fresh auditor's five screen_only bypasses (t253/t254) are each refused.

Runtime: screen_only() refuses unless entered from research/ or tests/, the live
flag is private (setting the old _ACTIVE does nothing), and require_screen_only()
re-checks the stack at pricing time. Static: the detector flags getattr, aliases,
_ACTIVE.set, monkeypatching require_screen_only, and fails on unparseable files."""
import ast
from pathlib import Path

import pytest

import sportsedge.screen_only_guard as g
from sportsedge.screen_only_guard import ScreenOnlyGuardError, require_screen_only, screen_only

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TOPS = {"research", "tests"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
GUARD_REL = Path("sportsedge/screen_only_guard.py")
OK_IMPORTS = {"require_screen_only", "ScreenOnlyGuardError"}


def _hits(src: str) -> list:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return ["PARSE_ERROR"]
    out = []
    for n in ast.walk(tree):
        ln = getattr(n, "lineno", 0)
        if isinstance(n, ast.Name) and n.id in ("screen_only", "_ACTIVE"):
            out.append(f"{ln}:NAME:{n.id}")
        elif isinstance(n, ast.Name) and n.id == "require_screen_only" and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.append(f"{ln}:REBIND:require_screen_only")
        elif isinstance(n, ast.Attribute) and n.attr in ("screen_only", "_ACTIVE"):
            out.append(f"{ln}:ATTR:{n.attr}")
        elif isinstance(n, ast.Attribute) and n.attr == "require_screen_only" and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.append(f"{ln}:MONKEYPATCH:require_screen_only")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in (
                "screen_only", "_ACTIVE", "require_screen_only"):
            out.append(f"{ln}:STRING:{n.value}")
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.endswith("screen_only_guard"):
                    out.append(f"{ln}:MODULE_IMPORT")
        elif isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            for a in n.names:
                if a.name == "screen_only_guard" or (mod.endswith("screen_only_guard") and (
                        a.name not in OK_IMPORTS or a.asname not in (None, a.name))):
                    out.append(f"{ln}:IMPORT:{a.name}")
    return sorted(set(out))


def _offenders(root: Path) -> list:
    out = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        if rel.parts[0] in ALLOWED_TOPS or SKIP_DIRS & set(rel.parts) or rel == GUARD_REL:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            out.append(f"{rel}:UNREADABLE")
            continue
        out += [f"{rel}:{h}" for h in _hits(src)]
    return sorted(out)


def _run_as(rel: str, src: str, ns=None):
    """Execute src with frames attributed to ROOT/rel (no file is written)."""
    ns = {"g": g, "require_screen_only": require_screen_only} if ns is None else ns
    exec(compile(src, str(ROOT / rel), "exec"), ns)
    return ns


def test_repo_has_no_offenders():
    assert _offenders(ROOT) == []


# --- bypass 1: setting _ACTIVE from outside ---------------------------------
def test_bypass1_active_set_is_refused():
    tok = g._ACTIVE.set(True)
    try:
        with pytest.raises(ScreenOnlyGuardError):
            require_screen_only("bypass1")
    finally:
        g._ACTIVE.reset(tok)
    assert _hits("import x\nx._ACTIVE.set(True)\n") == ["2:ATTR:_ACTIVE"]


# --- bypass 2: getattr(guard, "screen_only") from production code ----------
def test_bypass2_getattr_entry_outside_research_is_refused():
    src = "so = getattr(g, 'screen_only')\nwith so():\n    require_screen_only('bypass2')\n"
    with pytest.raises(ScreenOnlyGuardError, match="ENTRY_OUTSIDE_RESEARCH_OR_TESTS"):
        _run_as("sportsedge/evil_getattr.py", src)
    assert "1:STRING:screen_only" in _hits(src)


# --- bypass 3: alias of screen_only from production code -------------------
def test_bypass3_alias_entry_outside_research_is_refused():
    src = "from sportsedge.screen_only_guard import screen_only as so\nopen_ = so\nwith open_():\n    require_screen_only('bypass3')\n"
    with pytest.raises(ScreenOnlyGuardError, match="ENTRY_OUTSIDE_RESEARCH_OR_TESTS"):
        _run_as("scripts/evil_alias.py", src, {"require_screen_only": require_screen_only})
    assert "1:IMPORT:screen_only" in _hits(src)
    assert _hits("import sportsedge.screen_only_guard as q\nz = q.screen_only\n") == ["1:MODULE_IMPORT", "2:ATTR:screen_only"]


# --- bypass 4: monkeypatching require_screen_only / leaked flag ------------
def test_bypass4_monkeypatch_is_detected_and_leaked_flag_refused():
    src = "import sportsedge.nfl_situational_empirical as m\nm.require_screen_only = lambda w: None\n"
    assert "2:MONKEYPATCH:require_screen_only" in _hits(src)
    assert "1:STRING:require_screen_only" in _hits("setattr(m, 'require_screen_only', print)\n")
    assert "1:REBIND:require_screen_only" in _hits("require_screen_only = print\n")
    # a research module that enters at import and never exits: once its frame is
    # gone, production code calling the pricer is refused at pricing time.
    ns = _run_as("research/leak_probe.py", "cm = screen_only()\ncm.__enter__()\nrequire_screen_only('in-frame')\n",
                 {"screen_only": screen_only, "require_screen_only": require_screen_only})
    try:
        with pytest.raises(ScreenOnlyGuardError, match="STACK_CHECK_FAILED"):
            _run_as("sportsedge/evil_after_leak.py", "require_screen_only('bypass4')\n")
    finally:
        ns["cm"].__exit__(None, None, None)


# --- bypass 5: files the detector cannot parse -----------------------------
def test_bypass5_unparseable_file_fails_detector(tmp_path):
    (tmp_path / "sportsedge").mkdir()
    (tmp_path / "sportsedge" / "bad.py").write_text("from sportsedge.screen_only_guard import screen_only\nwith screen_only(:\n")
    (tmp_path / "sportsedge" / "bin.py").write_bytes(b"\xff\xfe\x00bad")
    assert _offenders(tmp_path) == ["sportsedge/bad.py:PARSE_ERROR", "sportsedge/bin.py:UNREADABLE"]


def test_legit_entry_from_tests_still_works():
    with screen_only():
        require_screen_only("legit")
    with pytest.raises(ScreenOnlyGuardError):
        require_screen_only("after-exit")
