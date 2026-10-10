"""Few-starts pitcher prior fallback (#1482 B3), validated in #1495 (Outs/K) and #1943 (BB/H/ER).

Pre-registered protocol: docs/MLB_PITCHER_PRIOR_FALLBACK_PREREG.md. The held-out
2025 test selected ``league_short`` at ``m = 4`` pseudo-starts and it passed both
ship rules for PITCHER_OUTS and PITCHER_K only. Scope is deliberately narrow:

* only PITCHER_OUTS and PITCHER_K (the markets that were validated);
* only starters with 1..4 own prior starts (k = 0 stays BLOCKED);
* only half-integer lines (integer lines were not scored);
* the prior pool is the frozen artifact for season Y-1; if it is missing the
  market stays BLOCKED exactly as before.

Extension (#1482, pre-registered in docs/MLB_PITCHER_PRIOR_FALLBACK_EXT_PREREG.md,
held-out PASS in #1943): the same frozen candidate (league_short, m = 4, n = k + 4)
also prices PITCHER_BB, PITCHER_HITS_ALLOWED and PITCHER_ER on half lines inside the
scored range. Those counts live in a separate frozen ``..._ext_<season>.json``
artifact whose outs/K counts must equal the base artifact (same pool); if the ext
artifact is missing or disagrees, those markets stay BLOCKED.
PITCHER_HITS_WALKS_ER and EITHER_PITCHER markets are not covered.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "MLB_PITCHER_PRIOR_POOL_V1"
POOL_NAME = "league_short"
PRIOR_PSEUDO_STARTS = 4.0
MIN_OWN_STARTS = 1
MAX_OWN_STARTS = 4
BASE_MARKET_STAT = {"PITCHER_OUTS": "outs", "PITCHER_K": "strikeouts"}
EXT_SCHEMA = "MLB_PITCHER_PRIOR_POOL_EXT_V1"
EXT_MARKET_STAT = {"PITCHER_BB": "walks", "PITCHER_HITS_ALLOWED": "hits", "PITCHER_ER": "earned_runs"}
# Half lines must sit below these caps: the #1943 test scored t + 0.5 for t = 0..cap-1.
EXT_LINE_CAP = {"PITCHER_BB": 10, "PITCHER_HITS_ALLOWED": 15, "PITCHER_ER": 12}
MARKET_STAT = {**BASE_MARKET_STAT, **EXT_MARKET_STAT}
FALLBACK_MARKETS = frozenset(MARKET_STAT)
VALIDATED_BY = {**{m: "#1495" for m in BASE_MARKET_STAT}, **{m: "#1943" for m in EXT_MARKET_STAT}}
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


class PitcherPriorError(ValueError):
    pass


def artifact_path(season: int, config_dir: Path | None = None) -> Path:
    return Path(config_dir or CONFIG_DIR) / f"mlb_pitcher_prior_{POOL_NAME}_{int(season)}.json"


def ext_artifact_path(season: int, config_dir: Path | None = None) -> Path:
    return Path(config_dir or CONFIG_DIR) / f"mlb_pitcher_prior_{POOL_NAME}_ext_{int(season)}.json"


def validate_artifact(raw: Mapping[str, Any], *, schema: str = SCHEMA, stats: tuple[str, ...] = tuple(BASE_MARKET_STAT.values())) -> dict[str, Any]:
    if raw.get("schema") != schema or raw.get("pool") != POOL_NAME:
        raise PitcherPriorError("prior artifact schema/pool mismatch")
    counts = raw.get("counts")
    if not isinstance(counts, Mapping):
        raise PitcherPriorError("prior artifact counts missing")
    clean: dict[str, dict[int, int]] = {}
    for stat in stats:
        table = counts.get(stat)
        if not isinstance(table, Mapping) or not table:
            raise PitcherPriorError(f"prior artifact counts.{stat} missing")
        out: dict[int, int] = {}
        for k, v in table.items():
            value, n = int(k), int(v)
            if value < 0 or n < 0 or (stat == "outs" and value > 27):
                raise PitcherPriorError(f"prior artifact counts.{stat} invalid entry {k}:{v}")
            if n:
                out[value] = n
        if sum(out.values()) < 100:
            raise PitcherPriorError(f"prior artifact counts.{stat} too small")
        clean[stat] = out
    return {"season": int(raw["season"]), "counts": clean,
            "sha256": hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def validate_ext_artifact(raw: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    """BB/H/ER pool; its outs/K counts must equal the base artifact (same starts)."""
    ext = validate_artifact(raw, schema=EXT_SCHEMA, stats=tuple(BASE_MARKET_STAT.values()) + tuple(EXT_MARKET_STAT.values()))
    if ext["season"] != int(base["season"]):
        raise PitcherPriorError("ext prior artifact season differs from base artifact")
    for stat in BASE_MARKET_STAT.values():
        if ext["counts"][stat] != base["counts"][stat]:
            raise PitcherPriorError(f"ext prior artifact counts.{stat} differ from base artifact (not the same pool)")
    totals = {sum(ext["counts"][stat].values()) for stat in ext["counts"]}
    if len(totals) != 1:
        raise PitcherPriorError("ext prior artifact stat totals differ")
    return ext


@lru_cache(maxsize=8)
def _load(path: str) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    return validate_artifact(json.loads(p.read_text(encoding="utf-8")))


@lru_cache(maxsize=8)
def _load_ext(path: str, base_path: str) -> dict[str, Any] | None:
    p = Path(path)
    base = _load(base_path)
    if base is None or not p.exists():
        return None
    return validate_ext_artifact(json.loads(p.read_text(encoding="utf-8")), base)


def prior_for(target_date: date, config_dir: Path | None = None, *, market: str = "PITCHER_OUTS") -> dict[str, Any] | None:
    """Frozen prior for the season before ``target_date`` covering ``market`` (None if not shipped)."""
    season = target_date.year - 1
    if market in EXT_MARKET_STAT:
        return _load_ext(str(ext_artifact_path(season, config_dir)), str(artifact_path(season, config_dir)))
    return _load(str(artifact_path(season, config_dir)))


def fallback_features(own_pool: list[dict[str, int]], market: str, prior: Mapping[str, Any]) -> dict[str, Any]:
    if market not in FALLBACK_MARKETS:
        raise PitcherPriorError(f"prior fallback not validated for {market}")
    if not MIN_OWN_STARTS <= len(own_pool) <= MAX_OWN_STARTS:
        raise PitcherPriorError(f"prior fallback needs {MIN_OWN_STARTS}..{MAX_OWN_STARTS} own starts, got {len(own_pool)}")
    stat = MARKET_STAT[market]
    if stat not in (prior.get("counts") or {}):
        raise PitcherPriorError(f"prior artifact has no {stat} counts for {market}")
    return {
        "history_pool": list(own_pool),
        "prior_fallback": {
            "pool": POOL_NAME, "season": int(prior["season"]), "market": market,
            "pseudo_starts": PRIOR_PSEUDO_STARTS,
            "counts": {str(k): int(v) for k, v in sorted(prior["counts"][stat].items())},
            "artifact_sha256": prior["sha256"],
        },
    }


_NOTE_LABEL = {"PITCHER_BB": "Pitcher BB", "PITCHER_HITS_ALLOWED": "Pitcher Hits Allowed", "PITCHER_ER": "Pitcher ER"}


def fallback_notes(payload: Mapping[str, Any], names: Mapping[str, str] | None = None) -> list[str]:
    """One card note per pitcher priced by the few-starts fallback (presentation only)."""
    results: list[Any] = list(payload.get("results") or [])
    for game in payload.get("games") or []:
        if isinstance(game, Mapping):
            results.extend(game.get("results") or [])
    seen: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in results:
        if not isinstance(row, Mapping):
            continue
        fb = (row.get("empirical_evidence") or {}).get("prior_fallback") if isinstance(row.get("empirical_evidence"), Mapping) else None
        if isinstance(fb, Mapping):
            seen.setdefault((str(row.get("entity_id")), str(row.get("market"))), fb)
    notes = []
    for (entity, market), fb in sorted(seen.items()):
        who = (names or {}).get(entity) or entity
        label = _NOTE_LABEL.get(market) or market.replace('_', ' ').title()
        notes.append(f"FEW-STARTS PRIOR FALLBACK {who} {label}: {fb.get('own_starts')} own starts + "
                     f"{fb.get('pseudo_starts'):g} prior pseudo-starts ({fb.get('pool')} {fb.get('season')}, validated {VALIDATED_BY.get(market, '#1495')}). LEAN max.")
    return notes
