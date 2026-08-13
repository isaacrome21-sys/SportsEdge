#!/usr/bin/env python3
"""V5 split rebuild transport fix.

Baseball Savant's hfBBT query is treated as an upstream efficiency hint, not as
a trusted semantic guarantee.  We preserve/hash the exact official response,
then enforce SportsEdge's own parsed `is_contact` predicate locally before the
frozen V5 feature builder sees any row.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import scripts.rebuild_statcast_v5_split as base


def fetch_feed(year: int, mode: str, cache: Path, bounds_cache: Path):
    lo, hi = base.s.regular_season_bounds(year, bounds_cache)
    out = []
    manifest = []
    cur = lo
    while cur <= hi:
        stop = min(hi, cur + timedelta(days=13))
        out.extend(base._adaptive(year, cur, stop, mode, cache, manifest))
        cur = stop + timedelta(days=1)

    if mode == "contact":
        # Do not trust hfBBT as the semantic gate. The official raw payload is
        # already source/date bounded and hashed in the manifest; now enforce
        # the frozen local contact definition exactly.
        out = [row for row in out if row.is_contact]
    elif mode == "identity":
        if any(int(row.inning) != 1 for row in out):
            raise RuntimeError(f"SAVANT_IDENTITY_FEED_INNING_VIOLATION:{year}")
    else:
        raise RuntimeError(f"SAVANT_SPLIT_MODE_INVALID:{mode}")

    keys = [(row.game_pk, row.at_bat_number) for row in out]
    if len(keys) != len(set(keys)):
        raise RuntimeError(f"SAVANT_SPLIT_DUPLICATE_PA:{mode}:{year}")
    if not out:
        raise RuntimeError(f"SAVANT_SPLIT_EMPTY:{mode}:{year}")
    if mode == "contact" and any(not row.is_contact for row in out):
        raise RuntimeError(f"SAVANT_CONTACT_LOCAL_FILTER_FAILED:{year}")
    print(f"SAVANT_SPLIT_YEAR_OK feed={mode} year={year} rows={len(out)} chunks={len(manifest)}", flush=True)
    return out, manifest


def main() -> None:
    base.fetch_feed = fetch_feed
    base.main()


if __name__ == "__main__":
    main()
