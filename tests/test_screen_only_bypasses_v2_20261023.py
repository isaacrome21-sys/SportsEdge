"""t256: the fresh auditor's second-round screen_only bypasses are each refused.

(5) research/ helper entered from sportsedge/ or scripts/, or given a sportsedge/
    lambda that runs the unrestricted pricer;
(A) compile() with a fake research/ filename;
(B) replacing the pricer module's require_screen_only / the guard's functions;
(C) emptying NAIVE_FAIL_FAMILIES;
(D) closure reflection: accepted residual (Grok ruling), cheap detection only."""
import ast
import importlib
import sys
from pathlib import Path

import pytest

import sportsedge.screen_only_guard as g
from sportsedge.screen_only_guard import ScreenOnlyGuardError, require_screen_only, screen_only

ROOT = Path(__file__).resolve().parents[1]
HELPER = "research.grok_screen_only_guard_fixture_20261023.helper"
PRICERS = [m for m in ("sportsedge.nfl_period_lines_empirical", "sportsedge.nfl_situational_empirical")
           if (ROOT / (m.replace(".", "/") + ".py")).is_file()]
PRICER = importlib.import_module(PRICERS[0])


def _helper():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module(HELPER)


def _run_as(rel, src, ns):
    exec(compile(src, str(ROOT / rel), "exec"), ns)
    return ns


def _research_imports(src):
    out = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            out += [f"{n.lineno}:{a.name}" for a in n.names if a.name.split(".")[0] == "research"]
        elif isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "research":
            out.append(f"{n.lineno}:{n.module}")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("research."):
            out.append(f"{n.lineno}:STRING:{n.value}")
    return out


def _research_import_offenders(root):
    out = []
    for top in ("sportsedge", "scripts"):
        for p in (root / top).rglob("*.py") if (root / top).is_dir() else []:
            try:
                hits = _research_imports(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, ValueError):
                hits = ["PARSE_ERROR"]
            out += [f"{p.relative_to(root)}:{h}" for h in hits]
    return sorted(out)


# --- (5) research helper entered from sportsedge/scripts or given a foreign lambda --
def test_bypass5_static_no_research_imports_from_sportsedge_or_scripts(tmp_path):
    assert _research_import_offenders(ROOT) == []
    (tmp_path / "sportsedge").mkdir()
    (tmp_path / "sportsedge" / "a.py").write_text(f"from {HELPER} import run_in_screen\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "b.py").write_text(f"import importlib\nimportlib.import_module('{HELPER}')\n")
    assert _research_import_offenders(tmp_path) == [
        f"scripts/b.py:2:STRING:{HELPER}", f"sportsedge/a.py:1:{HELPER}"]


@pytest.mark.parametrize("caller", ["sportsedge/evil_caller.py", "scripts/evil_caller.py"])
def test_bypass5_helper_entered_from_production_is_refused(caller):
    h = _helper()
    with pytest.raises(ScreenOnlyGuardError, match="ENTERED_FROM_OUTSIDE_RESEARCH_OR_TESTS"):
        _run_as(caller, "h.run_in_screen(lambda: require_screen_only('bypass5'))\n",
                {"h": h, "require_screen_only": require_screen_only})


def test_bypass5_foreign_lambda_between_entry_and_pricer_is_refused():
    h = _helper()
    ns = _run_as("sportsedge/evil_lambda.py", "fn = lambda: g.checked_require('bypass5-lambda')\n", {"g": g})
    with pytest.raises(ScreenOnlyGuardError, match="FOREIGN_FRAME_BETWEEN_ENTRY_AND_PRICER"):
        h.run_in_screen(ns["fn"])
    assert h.run_in_screen(lambda: g.checked_require("legit-lambda")) is None


# --- (A) filename spoof ------------------------------------------------------
@pytest.mark.parametrize("fake", ["research/does_not_exist_20261023.py",
                                  "research/grok_screen_only_guard_fixture_20261023/helper.py",
                                  "tests/test_screen_only_bypasses_v2_20261023.py"])
def test_bypassA_compile_with_fake_research_path_is_refused(fake):
    src = "with screen_only():\n    require_screen_only('bypassA')\n"
    with pytest.raises(ScreenOnlyGuardError, match="ENTRY_NOT_GENUINE_FILE"):
        _run_as(fake, src, {"screen_only": screen_only, "require_screen_only": require_screen_only,
                            "__file__": str(ROOT / fake)})


# --- (B) patching the pricer's / guard's functions ---------------------------
@pytest.mark.parametrize("mod", PRICERS)
def test_bypassB_pricer_require_replacement_refused(mod):
    m = importlib.import_module(mod)
    for name in ("require_screen_only", "checked_require"):
        with pytest.raises(ScreenOnlyGuardError, match="LOCKED_ATTRIBUTE"):
            setattr(m, name, lambda what: None)
    with pytest.raises(ScreenOnlyGuardError, match="LOCKED_ATTRIBUTE"):
        g.require_screen_only = lambda what: None
    with pytest.raises(ScreenOnlyGuardError, match="LOCKED_ATTRIBUTE"):
        del g.screen_only


def test_bypassB_dict_level_guard_replacement_detected():
    orig = g.__dict__["require_screen_only"]
    g.__dict__["require_screen_only"] = lambda what: None
    try:
        with pytest.raises(ScreenOnlyGuardError, match="GUARD_TAMPERED"):
            with screen_only():
                g.checked_require("bypassB")
    finally:
        g.__dict__["require_screen_only"] = orig


# --- (C) emptying NAIVE_FAIL_FAMILIES -------------------------------------
@pytest.mark.parametrize("mod", PRICERS)
def test_bypassC_naive_fail_families_cannot_be_emptied(mod):
    m = importlib.import_module(mod)
    before = m.NAIVE_FAIL_FAMILIES
    assert isinstance(before, frozenset) and before
    with pytest.raises(ScreenOnlyGuardError, match="LOCKED_ATTRIBUTE"):
        m.NAIVE_FAIL_FAMILIES = frozenset()
    m.__dict__["NAIVE_FAIL_FAMILIES"] = frozenset()  # dict-level: detected on read
    try:
        with pytest.raises(ScreenOnlyGuardError, match="NAIVE_FAIL_FAMILIES_TAMPERED"):
            m._naive_fail()
    finally:
        m.__dict__["NAIVE_FAIL_FAMILIES"] = before
    assert m._naive_fail() == before


# --- (D) closure reflection: accepted residual, cheap detection --------------
def test_bypassD_closure_reflection_is_accepted_residual_but_tamper_is_detected():
    doc = g.__doc__
    assert "ACCEPTED RESIDUAL" in doc and "MISTAKES, not determined bypasses" in doc
    rulings = (ROOT / "docs/decisions/GROK_RULING_SCREEN_ONLY_RESIDUAL_20261023.md").read_text(encoding="utf-8")
    assert "ACCEPTED_RESIDUAL" in rulings and "closure" in rulings
    # cheap detection: swapping the guard function for one rebuilt from its closure
    # (a reflection-based copy) is not the pinned object, so checked_require refuses.
    f = g.__dict__["require_screen_only"]
    clone = type(f)(f.__code__, f.__globals__, "require_screen_only", f.__defaults__, f.__closure__)
    g.__dict__["require_screen_only"] = clone
    try:
        with pytest.raises(ScreenOnlyGuardError, match="GUARD_TAMPERED"):
            g.checked_require("bypassD")
    finally:
        g.__dict__["require_screen_only"] = f
