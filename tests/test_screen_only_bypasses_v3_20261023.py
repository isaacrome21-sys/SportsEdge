"""t257: the auditor's round-3 guard bypasses are each refused.

(1) thread pool: ThreadPoolExecutor().submit(helper, functools.partial(pricer...))
    from production code. Fixed three ways: non-main-thread entry refused without
    a verified entry context; the generic run_in_screen helper is gone; callables
    a research helper runs must be defined in genuine research/ or tests/ files.
(2) module-class swap: P.__class__ = types.ModuleType unlocked the module. Now
    __class__ assignment is refused, and checked_require / verify_naive_fail assert
    type(module) is LockedModule; the NAIVE_FAIL sha256 pin lives in the guard."""
import contextvars
import functools
import importlib
import inspect
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import sportsedge.screen_only_guard as g
from sportsedge.screen_only_guard import ScreenOnlyGuardError, screen_only

ROOT = Path(__file__).resolve().parents[1]
HELPER = "research.grok_screen_only_guard_fixture_20261023.helper"
PRICERS = [m for m in ("sportsedge.nfl_period_lines_empirical", "sportsedge.nfl_situational_empirical")
           if (ROOT / (m.replace(".", "/") + ".py")).is_file()]


def _helper():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module(HELPER)


def _run_as(rel, src, ns):
    exec(compile(src, str(ROOT / rel), "exec"), ns)
    return ns


def _unrestricted(m):
    return getattr(m, "price_period_unrestricted", None) or getattr(m, "price_situational_unrestricted")


# --- (1) thread-pool bypass -------------------------------------------------
def test_bypass1a_thread_entry_from_production_is_refused():
    h = _helper()
    src = ("from concurrent.futures import ThreadPoolExecutor\n"
           "with ThreadPoolExecutor(1) as ex:\n    fut = ex.submit(h.probe)\n")
    ns = _run_as("sportsedge/evil_pool.py", src, {"h": h})
    with pytest.raises(ScreenOnlyGuardError, match="ENTRY_FROM_NON_MAIN_THREAD"):
        ns["fut"].result()


def test_bypass1a_thread_with_verified_context_may_enter():
    h = _helper()
    with screen_only():
        ctx = contextvars.copy_context()
    with screen_only():
        ctx2 = contextvars.copy_context()
        with ThreadPoolExecutor(1) as ex:
            assert ex.submit(ctx2.run, h.probe).result() == "PROBE_OK"
    del ctx


def test_bypass1b_generic_run_in_screen_helper_removed():
    h = _helper()
    assert not hasattr(h, "run_in_screen")
    for name, fn in inspect.getmembers(h, inspect.isfunction):
        if fn.__module__ == h.__name__:
            assert not inspect.signature(fn).parameters, f"{name} accepts arguments"


@pytest.mark.parametrize("mod", PRICERS)
def test_bypass1c_partial_of_pricer_is_not_a_research_callable(mod):
    m = importlib.import_module(mod)
    p = functools.partial(_unrestricted(m), [], family="SAFETY")
    for fn in (p, functools.partial(p), _unrestricted(m), print, functools.wraps(_unrestricted(m))(lambda: 0).__wrapped__):
        with pytest.raises(ScreenOnlyGuardError, match="CALLABLE_NOT_RESEARCH"):
            g.require_research_callable(fn)
    ns = _run_as("research/does_not_exist_t257.py", "fn = lambda: 1\n", {})
    with pytest.raises(ScreenOnlyGuardError, match="CALLABLE_NOT_RESEARCH"):
        g.require_research_callable(ns["fn"])
    ok = functools.partial(lambda x: x, 1)
    assert g.require_research_callable(ok).__code__.co_filename == __file__


# --- (2) module-class swap -------------------------------------------------
@pytest.mark.parametrize("mod", PRICERS + ["sportsedge.screen_only_guard"])
def test_bypass2_module_class_assignment_refused(mod):
    m = importlib.import_module(mod)
    with pytest.raises(ScreenOnlyGuardError, match="LOCKED_ATTRIBUTE:__class__"):
        m.__class__ = types.ModuleType
    assert type(m) is g.LockedModule


@pytest.mark.parametrize("mod", PRICERS)
def test_bypass2_object_level_class_swap_detected(mod):
    m = importlib.import_module(mod)
    object.__setattr__(m, "__class__", types.ModuleType)  # skips LockedModule.__setattr__
    try:
        with pytest.raises(ScreenOnlyGuardError, match="MODULE_UNLOCKED"):
            m._naive_fail()
        with pytest.raises(ScreenOnlyGuardError, match="MODULE_UNLOCKED"):
            with screen_only():
                eval("checked_require('class-swap')", vars(m))  # call as the pricer module
    finally:
        object.__setattr__(m, "__class__", g.LockedModule)
    assert m._naive_fail() == m.NAIVE_FAIL_FAMILIES


@pytest.mark.parametrize("mod", PRICERS)
def test_bypass2_sha_pin_lives_in_guard_not_pricer(mod):
    m = importlib.import_module(mod)
    assert not any("SHA256" in k for k in vars(m))
    assert mod in g._PINNED_NAIVE_FAIL_SHA256
    assert isinstance(g._PINNED_NAIVE_FAIL_SHA256, types.MappingProxyType)
    with pytest.raises(TypeError):
        g._PINNED_NAIVE_FAIL_SHA256[mod] = "0" * 64
