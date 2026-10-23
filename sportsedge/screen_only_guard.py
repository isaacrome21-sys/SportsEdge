"""Guard so screen-only (unrestricted) pricers cannot run outside a screen.

Unrestricted pricers include families that failed their naive screen. They may
run only inside ``with screen_only():`` entered from a real file under
``research/`` or ``tests/``; anywhere else they refuse with SCREEN_ONLY_GUARD.

Checks (t255 + t256, fixing the fresh auditor's bypasses):
* Entry: the entering frame (first frame outside this module/contextlib) must be
  a file under research/ or tests/ that EXISTS on disk, whose globals are a real
  imported module's (or __main__'s) and name that same file, and whose real source line at the frame's current line
  calls screen_only (defeats ``compile(src, "research/fake.py")`` spoofs).
  Every frame ABOVE the entry that lives in the repo must also be under
  research/ or tests/, so a research/ helper called from sportsedge/ or
  scripts/ is refused.
* State lives in a closure; ``_ACTIVE`` is an inert decoy.
* Pricing time: the recorded entry frame must still be on the live stack and
  every repo frame between the entry and the pricer must be under research/ or
  tests/, or be guard / registered pricer internals (a sportsedge/ lambda
  passed into a research helper is refused).
* This module refuses attribute replacement of its public names, and pricers
  call ``checked_require()`` which compares the guard function to a pinned
  reference.

ACCEPTED RESIDUAL (Grok ruling D, 2026-10-23): an in-process Python guard
cannot stop a determined caller (closure/``__dict__``/frame reflection,
ctypes, editing files). This guard prevents MISTAKES, not determined bypasses.
Cheap tamper detection is still tested.

t257 (auditor round 3): entry from a non-main thread is refused unless that
thread already carries a verified entry context; research helpers may only run
callables defined in genuine research/ or tests/ files
(``require_research_callable``); ``__class__`` assignment on locked modules is
refused, and ``checked_require``/``verify_naive_fail`` assert the module type is
still LockedModule. NAIVE_FAIL sha256 pins live here, outside the pricers.
"""
from __future__ import annotations

import linecache
import os
import functools
import hashlib
import sys
import threading
import types
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ALLOWED_TOPS = ("research", "tests")
_NON_REPO_TOPS = (".venv", "venv", "site-packages")
_THIS = str(Path(__file__).resolve())
PRICER_INTERNALS = frozenset({
    "sportsedge/nfl_period_lines_empirical.py",
    "sportsedge/nfl_situational_empirical.py",
    "sportsedge/week_cluster_bootstrap.py",
})

# Inert decoy kept so old code that pokes the attribute gets no effect.
_ACTIVE: ContextVar[bool] = ContextVar("sportsedge_screen_only_decoy", default=False)


class ScreenOnlyGuardError(RuntimeError):
    pass


def _rel(filename: str):
    if not filename or filename.startswith("<"):
        return None
    try:
        return Path(filename).resolve().relative_to(_ROOT)
    except (ValueError, OSError):
        return None


def _allowed_file(filename: str) -> bool:
    rel = _rel(filename)
    return rel is not None and len(rel.parts) > 1 and rel.parts[0] in _ALLOWED_TOPS


def _is_internal(frame) -> bool:
    fn = frame.f_code.co_filename
    try:
        if str(Path(fn).resolve()) == _THIS:
            return True
    except OSError:
        pass
    return fn.endswith("contextlib.py")


def _repo_frame_ok(frame, *, pricer_ok: bool) -> bool:
    rel = _rel(frame.f_code.co_filename)
    if rel is None or rel.parts[0] in _NON_REPO_TOPS:
        return True  # stdlib / site-packages / pytest machinery
    if rel.parts[0] in _ALLOWED_TOPS or _is_internal(frame):
        return True
    return pricer_ok and rel.as_posix() in PRICER_INTERNALS


def _genuine(frame) -> bool:
    fn = frame.f_code.co_filename
    if not os.path.isfile(fn):
        return False
    gfile = frame.f_globals.get("__file__")
    try:
        if not gfile or Path(gfile).resolve() != Path(fn).resolve():
            return False
    except OSError:
        return False
    mod = sys.modules.get(frame.f_globals.get("__name__", ""))
    if mod is None or getattr(mod, "__dict__", None) is not frame.f_globals:
        return False  # globals must belong to a real imported module (or __main__)
    linecache.checkcache(fn)
    if "screen_only" not in linecache.getline(fn, frame.f_lineno):
        return False
    name = frame.f_code.co_name
    if name not in ("<module>", "<lambda>") and not name.startswith("<"):
        if f"def {name}" not in linecache.getline(fn, frame.f_code.co_firstlineno):
            # decorated defs: firstlineno is the decorator line; scan a few lines
            first = frame.f_code.co_firstlineno
            if not any(f"def {name}" in linecache.getline(fn, first + k) for k in range(1, 6)):
                return False
    return True


def _entering_frame():
    f = sys._getframe(1)
    while f is not None and _is_internal(f):
        f = f.f_back
    return f


def _make():
    state: ContextVar[tuple] = ContextVar("sportsedge_screen_only_private", default=())

    @contextmanager
    def screen_only():
        if threading.current_thread() is not threading.main_thread() and not state.get():
            raise ScreenOnlyGuardError("SCREEN_ONLY_GUARD:ENTRY_FROM_NON_MAIN_THREAD")
        entry = _entering_frame()
        if entry is None or not _allowed_file(entry.f_code.co_filename):
            where = "?" if entry is None else entry.f_code.co_filename
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:ENTRY_OUTSIDE_RESEARCH_OR_TESTS:{Path(where).name}")
        if not _genuine(entry):
            raise ScreenOnlyGuardError("SCREEN_ONLY_GUARD:ENTRY_NOT_GENUINE_FILE")
        f = entry.f_back
        while f is not None:
            if not _repo_frame_ok(f, pricer_ok=False):
                raise ScreenOnlyGuardError(
                    f"SCREEN_ONLY_GUARD:ENTERED_FROM_OUTSIDE_RESEARCH_OR_TESTS:{Path(f.f_code.co_filename).name}")
            f = f.f_back
        token = state.set(state.get() + (entry,))
        try:
            yield
        finally:
            state.reset(token)

    def require_screen_only(what: str) -> None:
        entries = state.get()
        if not entries:
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:{what}")
        entry = entries[-1]
        f = sys._getframe(1)
        while f is not None and f is not entry:
            if not _repo_frame_ok(f, pricer_ok=True):
                raise ScreenOnlyGuardError(
                    f"SCREEN_ONLY_GUARD:FOREIGN_FRAME_BETWEEN_ENTRY_AND_PRICER:{Path(f.f_code.co_filename).name}:{what}")
            f = f.f_back
        if f is None or not _allowed_file(entry.f_code.co_filename):
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:STACK_CHECK_FAILED:{what}")

    return screen_only, require_screen_only


screen_only, require_screen_only = _make()
del _make
_PINNED_REQUIRE = require_screen_only
_PINNED_ENTER = screen_only


def checked_require(what: str) -> None:
    """Pricers call this: refuses if the guard function was replaced or a module
    lock was removed (module class swapped away from LockedModule)."""
    mod = sys.modules.get(__name__)
    caller = sys._getframe(1).f_globals.get("__name__", "")
    for m in (mod, sys.modules.get(caller) if caller in _PINNED_NAIVE_FAIL_SHA256 else mod):
        if type(m) is not LockedModule:
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:MODULE_UNLOCKED:{what}")
    fn = getattr(mod, "require_screen_only", None)
    if fn is not _PINNED_REQUIRE or getattr(mod, "screen_only", None) is not _PINNED_ENTER:
        raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:GUARD_TAMPERED:{what}")
    _PINNED_REQUIRE(what)


_PINNED_NAIVE_FAIL_SHA256 = types.MappingProxyType({
    "sportsedge.nfl_period_lines_empirical":
        "ec535bb6e87d2f3fa9b6cd3988a625f3f5183c51f9edc7b33e086855935df678",
    "sportsedge.nfl_situational_empirical":
        "355a0139548e437ebc3d126f1db466d3725e9f2d25f190192f478618857faeaa",
})


def verify_naive_fail(modname: str, value):
    """Every pricer read of NAIVE_FAIL_FAMILIES goes through here (pin held in
    the guard, not in the module it guards)."""
    if type(sys.modules.get(modname)) is not LockedModule:
        raise ScreenOnlyGuardError("SCREEN_ONLY_GUARD:MODULE_UNLOCKED:NAIVE_FAIL_FAMILIES")
    pin = _PINNED_NAIVE_FAIL_SHA256.get(modname)
    if pin is None or not isinstance(value, frozenset) or hashlib.sha256(
            "\n".join(sorted(value)).encode()).hexdigest() != pin:
        raise ScreenOnlyGuardError("SCREEN_ONLY_GUARD:NAIVE_FAIL_FAMILIES_TAMPERED")
    return value


def require_research_callable(fn):
    """A research helper may run only callables defined in a genuine research/
    or tests/ file. Partials, bound methods and ``__wrapped__`` are unwrapped."""
    seen = 0
    while seen < 32:
        seen += 1
        if isinstance(fn, functools.partial):
            fn = fn.func
        elif hasattr(fn, "__func__"):
            fn = fn.__func__
        elif hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        else:
            break
    code = getattr(fn, "__code__", None)
    fname = getattr(code, "co_filename", "")
    ok = code is not None and _allowed_file(fname) and os.path.isfile(fname)
    if ok:
        linecache.checkcache(fname)
        line = "".join(linecache.getline(fname, code.co_firstlineno + k) for k in range(6))
        ok = ("lambda" in line) if code.co_name == "<lambda>" else (f"def {code.co_name}" in line)
    if not ok:
        raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:CALLABLE_NOT_RESEARCH:{Path(fname or '?').name}")
    return fn


class LockedModule(types.ModuleType):
    """Refuse rebinding/deleting the names listed in ``__locked__`` and refuse
    ``__class__`` assignment (no unlocking by module-class swap)."""

    def __setattr__(self, name, value):
        if name == "__class__":
            raise ScreenOnlyGuardError("SCREEN_ONLY_GUARD:LOCKED_ATTRIBUTE:__class__")
        if name in self.__dict__.get("__locked__", ()):
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:LOCKED_ATTRIBUTE:{name}")
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name == "__class__" or name in self.__dict__.get("__locked__", ()):
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:LOCKED_ATTRIBUTE:{name}")
        super().__delattr__(name)


def lock_module(name: str, names) -> None:
    mod = sys.modules[name]
    mod.__dict__["__locked__"] = frozenset(names)
    mod.__class__ = LockedModule


lock_module(__name__, {"screen_only", "require_screen_only", "checked_require",
                       "_PINNED_REQUIRE", "_PINNED_ENTER", "lock_module", "__locked__",
                       "verify_naive_fail", "require_research_callable",
                       "_PINNED_NAIVE_FAIL_SHA256", "LockedModule"})
