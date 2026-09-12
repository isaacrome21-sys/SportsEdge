"""NFL adapter package.

Keep the public ``NFLAdapter`` export lazy so research/capture submodules can be
imported without pulling the NumPy-backed game adapter into processes that do
not use it.  Attribute access remains backward-compatible for callers that do
need ``NFLAdapter``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .adapter import NFLAdapter as NFLAdapter

__all__ = ["NFLAdapter"]


def __getattr__(name: str) -> Any:
    if name == "NFLAdapter":
        from .adapter import NFLAdapter
        return NFLAdapter
    raise AttributeError(name)
