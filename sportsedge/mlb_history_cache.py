"""Shared date-safe cache for official MLB historical game-log payloads.

Only immutable/prior-history gameLog requests are cacheable. Live schedule,
boxscore, lineup and sportsbook requests always bypass this layer.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen


class MLBHistoryCacheError(RuntimeError):
    pass


class _BytesResponse:
    def __init__(self, raw: bytes):
        self._raw = raw
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self._raw


class MLBHistoryCachedOpener:
    """Callable opener that caches only StatsAPI person gameLog responses."""

    def __init__(self, *, target_date: date, cache_dir: str | Path | None = None, opener: Callable = urlopen):
        if not isinstance(target_date, date):
            raise MLBHistoryCacheError("HISTORY_CACHE_TARGET_DATE_INVALID")
        self.target_date = target_date
        self.opener = opener
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._memory: dict[str, bytes] = {}
        if self.cache_dir is not None:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise MLBHistoryCacheError("HISTORY_CACHE_UNAVAILABLE") from exc

    def _cache_key(self, url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.netloc != "statsapi.mlb.com" or not parsed.path.startswith("/api/v1/people/") or not parsed.path.endswith("/stats"):
            return None
        query = parse_qs(parsed.query)
        if query.get("stats") != ["gameLog"]:
            return None
        seasons = query.get("season")
        groups = query.get("group")
        if not seasons or len(seasons) != 1 or not groups or len(groups) != 1:
            return None
        try:
            season = int(seasons[0])
        except (TypeError, ValueError):
            return None
        marker = self.target_date.isoformat() if season == self.target_date.year else "frozen"
        raw_key = f"{url}|{marker}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def _disk_path(self, key: str) -> Path | None:
        return None if self.cache_dir is None else self.cache_dir / f"{key}.json"

    @staticmethod
    def _validate(raw: bytes) -> bytes:
        try:
            value: Any = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MLBHistoryCacheError("HISTORY_CACHE_PAYLOAD_MALFORMED") from exc
        if not isinstance(value, dict):
            raise MLBHistoryCacheError("HISTORY_CACHE_PAYLOAD_MALFORMED")
        return raw

    def __call__(self, req, timeout=15):
        url = req if isinstance(req, str) else str(req.full_url)
        key = self._cache_key(url)
        if key is None:
            return self.opener(req, timeout=timeout)
        if key in self._memory:
            return _BytesResponse(self._memory[key])
        path = self._disk_path(key)
        if path is not None and path.exists():
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise MLBHistoryCacheError("HISTORY_CACHE_READ_FAILED") from exc
            raw = self._validate(raw)
            self._memory[key] = raw
            return _BytesResponse(raw)
        try:
            with self.opener(req, timeout=timeout) as response:
                raw = response.read()
        except Exception:
            raise
        raw = self._validate(raw)
        self._memory[key] = raw
        if path is not None:
            try:
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(raw)
                tmp.replace(path)
            except OSError as exc:
                raise MLBHistoryCacheError("HISTORY_CACHE_WRITE_FAILED") from exc
        return _BytesResponse(raw)
