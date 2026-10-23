"""Guard so screen-only (unrestricted) pricers cannot run outside a screen.

Unrestricted pricers include families that failed their naive screen. They
may run only inside ``with screen_only():``; anywhere else they refuse with
SCREEN_ONLY_GUARD. The flag is a ContextVar, so it does not leak across
threads/tasks and is always reset when the block exits (even on error).
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE: ContextVar[bool] = ContextVar("sportsedge_screen_only", default=False)


class ScreenOnlyGuardError(RuntimeError):
    pass


@contextmanager
def screen_only():
    token = _ACTIVE.set(True)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def require_screen_only(what: str) -> None:
    if _ACTIVE.get() is not True:
        raise ScreenOnlyGuardError(f"SCREEN_ONLY_GUARD:{what}")
