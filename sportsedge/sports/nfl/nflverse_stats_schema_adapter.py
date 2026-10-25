"""Exact-rename adapter for nflverse stats_player (2025+) feeding the frozen V1 loader.

nflverse renamed two columns the blob-pinned V1 loader
(`live_role_source.fetch_nflverse_player_stats`, forward-locked) requires:
``recent_team -> team`` and ``interceptions -> passing_interceptions``.
The frozen file is NOT edited. This adapter downloads the upstream bytes,
renames those header cells back (values untouched), and hands the rewritten
bytes to the frozen loader. Any other schema gap still fails closed inside
the frozen loader. Receipts keep the upstream hash alongside the rewritten one.
"""
from __future__ import annotations

import csv
from hashlib import sha256
from io import BytesIO, StringIO
from typing import Any, Callable, Iterable
from urllib.request import urlopen

from .context_autopull import NFLContextError
from .live_role_source import fetch_nflverse_player_stats

RENAMES = (("team", "recent_team"), ("passing_interceptions", "interceptions"))


class _Body(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _rewrite(raw: bytes) -> tuple[bytes, list[str]]:
    text = raw.decode("utf-8-sig")
    reader = csv.reader(StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return raw, []
    applied = []
    for current, legacy in RENAMES:
        if current in header and legacy in header:
            raise NFLContextError(f"NFLVERSE player-stats schema ambiguous:{current}+{legacy}")
        if current in header:
            header[header.index(current)] = legacy
            applied.append(f"{current}->{legacy}")
    if not applied:
        return raw, []
    out = StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(reader)
    return out.getvalue().encode("utf-8"), applied


def fetch_player_stats_2025_schema(
    *, seasons: Iterable[int], opener: Callable = urlopen,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    upstream: dict[str, tuple[str, list[str]]] = {}

    def renaming_opener(req, timeout=30):
        with opener(req, timeout=timeout) as response:
            raw = response.read()
        rewritten, applied = _rewrite(raw)
        upstream[req.full_url] = (sha256(raw).hexdigest(), applied)
        return _Body(rewritten)

    rows, receipts = fetch_nflverse_player_stats(seasons=seasons, opener=renaming_opener)
    for receipt in receipts:
        digest, applied = upstream.get(receipt["source_uri"], (receipt["raw_sha256"], []))
        receipt["upstream_raw_sha256"] = digest
        receipt["schema_renames"] = applied
    return rows, receipts
