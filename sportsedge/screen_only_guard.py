"""Guard so screen-only (unrestricted) pricers cannot run outside a screen.

Unrestricted pricers include families that failed their naive screen. They may
run only inside ``with screen_only():`` entered from a file under ``research/``
or ``tests/``; anywhere else they refuse with SCREEN_ONLY_GUARD.

Hardening (t255, fixes the fresh auditor's five t253/t254 bypasses):
* ``screen_only()`` walks the call stack and refuses unless the entering file
  (first frame outside this module and contextlib) is under research/ or tests/.
* The live state is held in a closure, not a module attribute. ``_ACTIVE`` is
  kept only as an inert decoy: setting it from outside opens nothing.
* ``require_screen_only()`` re-walks the stack at pricing time: the recorded
  entry frame must still be on the current stack and still be under
  research/ or tests/. A flag left set after the screen frame is gone refuses.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ALLOWED_TOPS = ("research", "tests")
_THIS = str(Path(__file__).resolve())

# Inert decoy kept so old code that pokes the attribute gets no effect.
_ACTIVE: ContextVar[bool] = ContextVar("sportsedge_screen_only_decoy", default=False)


class ScreenOnlyGuardError(RuntimeError):
    pass


def _allowed_file(filename: str) -> bool:
    if not filename or filename.startswith("<"):
        return False
    try:
        rel = Path(filename).resolve().relative_to(_ROOT)
    except (ValueError, OSError):
        return False
    return len(rel.parts) > 1 and rel.parts[0] in _ALLOWED_TOPS


def _is_internal(frame) -> bool:
    fn = frame.f_code.co_filename
    try:
        if str(Path(fn).resolve()) == _THIS:
            return True
    except OSError:
        pass
    return fn.endswith(("contextlib.py",))


def _entering_frame():
    f = sys._getframe(1)
    while f is not None and _is_internal(f):
        f = f.f_back
    return f


def _make():
    state: ContextVar[tuple] = ContextVar("sportsedge_screen_only_private", default=())

    @contextmanager
    def screen_only():
        entry = _entering_frame()
        if entry is None or not _allowed_file(entry.f_code.co_filename):
            where = "?" if entry is None else entry.f_code.co_filename
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:ENTRY_OUTSIDE_RESEARCH_OR_TESTS:{Path(where).name}")
        token = state.set(state.get() + (entry,))
        try:
            yield
        finally:
            state.reset(token)

    def require_screen_only(what: str) -> None:
        entries = state.get()
        if not entries:
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:{what}")
        live = set()
        f = sys._getframe(1)
        while f is not None:
            live.add(id(f))
            f = f.f_back
        entry = entries[-1]
        if id(entry) not in live or not _allowed_file(entry.f_code.co_filename):
            raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:STACK_CHECK_FAILED:{what}")

    return screen_only, require_screen_only


screen_only, require_screen_only = _make()
del _make
