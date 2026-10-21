"""MLB plate-appearance engine v1 — the M49 construction as a priced engine.

Implements, unchanged, the candidate construction specified in
SPEC_M49_PA.md (SportsEdge backtest program, Oct 17 2026, MLB lane
item 4; spec SHA-256
2e2cb70d69607f9320dc9b6cd3b19e1fd71c98c4281515affe93e81eede3f84f,
recorded in that program's specs/SPEC_HASHES.txt before any M49 score
was computed).  The Oct 17 construction test scored that construction
BEATS_BASELINE at construction level (paired log-score deltas vs both
baselines, ISO-week block bootstrap, 2025 pool); this module is the
engine build the spec named as its follow-on.  No construction here
is new: same six-category partition, same shrinkage, same gates.

Construction (spec sections 1-2):
* Data: the stage-1 PBP pool (research/mlb-pbp-pool-20261016) — one
  row per plate appearance from MLB StatsAPI play-by-play, keyed by
  StatsAPI person IDs.  The pool files live in workspace storage
  (~/workspace/sportsedge/mlb_pbp_pool_20261016/) with SHA-256 pins in
  MANIFEST.json recorded on that branch; they are consumed as a data
  source, never committed here.
* PIT rule (the pool's own rule, adopted verbatim by the spec): pool
  game G feeds target T only if ``G.game_completed_date <
  T.game_date`` (America/New_York calendar dates, strict).  Histories
  are same-season only.  Same-date games never feed a target,
  doubleheaders included.
* Categories over ``outcome_class`` (spec partition, exhaustive):
  K, BB_HBP, SINGLE, XBH, HR, OTHER.
* Eligibility: the batter needs >= 50 strictly-prior same-season PAs;
  below that the pricer refuses with a named code, never a shrunk
  guess at a thinner history.
* Candidate: the batter's empirical category counts shrunk toward
  the expanding league climatology with fixed strength k = 50 PAs:
  p(c) = (count_b(c) + 50 * p_L(c)) / (n_b + 50), where p_L is the
  league's strictly-prior same-season category frequency.

Markets (sportsedge.mlb_plate_appearance_gates):
* PLATE_APPEARANCE_RESULT — the six-category distribution itself
  (the 1st-PA-result form).
* PLATE_APPEARANCE_ON_BASE — P(reached) with reached := category in
  {BB_HBP, SINGLE, XBH, HR} (the spec's declared binary; OTHER
  therefore includes reach-on-error and fielder's-choice PAs —
  disclosed, not hidden).
* PLATE_APPEARANCE_GROUPED_RESULT — REFUSED by this engine with
  PLATE_APPEARANCE_GROUPED_PARTITION_UNVERIFIED.  DraftKings' exact
  3-way partition of PA outcomes is not in the catalog evidence (the
  gate's second blocker, PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED),
  and the engine will not invent one.  Any verified partition is a
  deterministic coarsening of the priced distribution; pricing the
  grouped form waits for that verification.

The spec's construction uses the batter's own history and the league
climatology only.  The pool also carries pitcher identity (so the
opposing starter's first-PA-faced history the gate's detail names is
derivable from the same pool), but the proven construction does not
condition on it, and this engine adds no such term — adding one
would be a substitute model, not this construction.

Governance: research only.  This module prices nothing on any card
path and changes no family's registration, eligibility, or the
PLATE_APPEARANCE_PBP_POOL_UNBUILT gate state — the gate lift, and
the selection-set verification, are separate owner-ruled steps.
Engine rows carry research_only / no-authority stamps in the gate
module's idiom.
"""
from __future__ import annotations

import gzip
import json
import re
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ENGINE_ID = "mlb_plate_appearance_engine_v1"
CONSTRUCTION_ID = "M49_PA_SHRUNK_EMPIRICAL_K50"
SPEC_SHA256 = "2e2cb70d69607f9320dc9b6cd3b19e1fd71c98c4281515affe93e81eede3f84f"
PIT_RULE = "pool game G feeds target T only if G.game_completed_date < T.game_date"

K_SHRINK = 50
MIN_PRIOR_PA = 50

CATEGORIES = ("K", "BB_HBP", "SINGLE", "XBH", "HR", "OTHER")
CATEGORY_OF = {
    "STRIKEOUT": "K",
    "WALK": "BB_HBP", "INTENT_WALK": "BB_HBP", "HIT_BY_PITCH": "BB_HBP",
    "HIT_SINGLE": "SINGLE",
    "HIT_DOUBLE": "XBH", "HIT_TRIPLE": "XBH",
    "HOME_RUN": "HR",
    "OUT_IN_PLAY": "OTHER", "SAC_FLY": "OTHER", "SAC_BUNT": "OTHER",
    "REACH_ON_ERROR": "OTHER", "FIELDERS_CHOICE": "OTHER",
    "INTERFERENCE": "OTHER",
}
REACHED_CATEGORIES = frozenset({"BB_HBP", "SINGLE", "XBH", "HR"})

MARKET_RESULT = "PLATE_APPEARANCE_RESULT"
MARKET_ON_BASE = "PLATE_APPEARANCE_ON_BASE"
MARKET_GROUPED_RESULT = "PLATE_APPEARANCE_GROUPED_RESULT"
PA_MARKETS = frozenset(
    {MARKET_RESULT, MARKET_ON_BASE, MARKET_GROUPED_RESULT})

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ZERO = (0, 0, 0, 0, 0, 0)


class PlateAppearanceEngineError(ValueError):
    pass


def category_of(outcome_class: Any) -> str:
    """Spec category for a pool ``outcome_class``; fail closed on
    anything outside the declared exhaustive partition."""
    cat = CATEGORY_OF.get(outcome_class) if isinstance(
        outcome_class, str) else None
    if cat is None:
        raise PlateAppearanceEngineError(
            f"POOL_OUTCOME_CLASS_UNMAPPED:{outcome_class!r}")
    return cat


def shrunk_distribution(batter_counts: Sequence[int],
                        league_counts: Sequence[int]) -> tuple[float, ...]:
    """The M49 candidate: batter empirical shrunk toward the
    expanding league climatology with fixed strength k = 50 PAs.

    Pure construction function — the engine's pool pricer and the
    screen both call exactly this.  Probabilities are the raw
    candidate; the spec's 1e-6 floor is a scoring-only device and is
    never applied to a price."""
    if len(batter_counts) != len(CATEGORIES) or len(league_counts) != len(CATEGORIES):
        raise PlateAppearanceEngineError("DISTRIBUTION_COUNT_LENGTH_MISMATCH")
    n_b = sum(batter_counts)
    n_l = sum(league_counts)
    if n_l <= 0:
        raise PlateAppearanceEngineError("LEAGUE_COUNTS_EMPTY")
    if n_b < 0:
        raise PlateAppearanceEngineError("BATTER_COUNTS_NEGATIVE")
    out = tuple(
        (int(batter_counts[i]) + K_SHRINK * (int(league_counts[i]) / n_l))
        / (n_b + K_SHRINK)
        for i in range(len(CATEGORIES)))
    if abs(sum(out) - 1.0) > 1e-9:
        raise PlateAppearanceEngineError("PROBABILITY_MASS_NOT_CONSERVED")
    return out


def _checked_date(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise PlateAppearanceEngineError(f"{code}:{value!r}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise PlateAppearanceEngineError(f"{code}:{value!r}") from exc
    return value


def _checked_id(value: Any, code: str) -> int:
    # bool is an int subclass; True is not a StatsAPI person id.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlateAppearanceEngineError(f"{code}:{value!r}")
    return value


def _validate_pool_row(row: Any, index: int) -> dict[str, Any]:
    """Validate one pool row and project it to the fields the engine
    consumes.  Missing or mistyped fields fail closed — a pool row
    is never repaired by zero-filling."""
    if not isinstance(row, Mapping):
        raise PlateAppearanceEngineError(f"POOL_ROW[{index}]_NOT_OBJECT")
    try:
        batter_id = _checked_id(row.get("batter_id"),
                                f"POOL_ROW[{index}].batter_id_INVALID")
        game_id = _checked_id(row.get("game_id"),
                              f"POOL_ROW[{index}].game_id_INVALID")
        season_raw = row.get("season")
        if isinstance(season_raw, bool) or not isinstance(season_raw, int):
            raise PlateAppearanceEngineError(
                f"POOL_ROW[{index}].season_INVALID:{season_raw!r}")
        game_date = _checked_date(row.get("game_date"),
                                  f"POOL_ROW[{index}].game_date_INVALID")
        completed = _checked_date(
            row.get("game_completed_date"),
            f"POOL_ROW[{index}].game_completed_date_INVALID")
        pa_number = row.get("batter_pa_number")
        if isinstance(pa_number, bool) or not isinstance(pa_number, int) \
                or pa_number < 1:
            raise PlateAppearanceEngineError(
                f"POOL_ROW[{index}].batter_pa_number_INVALID:{pa_number!r}")
        category = category_of(row.get("outcome_class"))
    except PlateAppearanceEngineError:
        raise
    return {
        "batter_id": batter_id, "game_id": game_id, "season": season_raw,
        "game_date": game_date, "game_completed_date": completed,
        "batter_pa_number": pa_number,
        "outcome_class": row.get("outcome_class"), "category": category,
    }


def load_pool_rows(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Load and validate pool rows from .jsonl / .jsonl.gz files.

    Every row is validated and projected by ``_validate_pool_row``;
    the first bad row aborts the load with its index named."""
    rows: list[dict[str, Any]] = []
    for path in paths:
        p = Path(path)
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise PlateAppearanceEngineError(
                        f"POOL_ROW[{len(rows)}]_NOT_JSON:{p}") from exc
                rows.append(_validate_pool_row(raw, len(rows)))
    return rows


class PlateAppearancePool:
    """Point-in-time index over validated pool rows.

    Per (season, batter): the batter's games sorted by
    (game_completed_date, game_date, game_id) with per-category
    prefix counts, so a strictly-prior history is a bisect on
    completed dates — same-date games can never feed a target
    (doubleheaders included), and a suspended game feeds only
    targets after its completion date.  Per season: the same index
    pooled across batters for the expanding league climatology.
    """

    def __init__(self, rows: Sequence[Mapping[str, Any]]):
        games: dict[int, tuple[int, str, str]] = {}
        per_batter_game: dict[tuple[int, int], dict[int, Counter]] = \
            defaultdict(lambda: defaultdict(Counter))
        per_season_game: dict[int, dict[int, Counter]] = \
            defaultdict(lambda: defaultdict(Counter))
        batters_seen: set[int] = set()
        for i, row in enumerate(rows):
            r = _validate_pool_row(row, i)
            gid = r["game_id"]
            meta = (r["season"], r["game_date"], r["game_completed_date"])
            prior = games.setdefault(gid, meta)
            if prior != meta:
                raise PlateAppearanceEngineError(
                    f"POOL_GAME_METADATA_CONFLICT:{gid}")
            per_batter_game[(r["season"], r["batter_id"])][gid][
                r["category"]] += 1
            per_season_game[r["season"]][gid][r["category"]] += 1
            batters_seen.add(r["batter_id"])
        self._batters_seen = frozenset(batters_seen)
        self._seasons = frozenset(per_season_game)
        self._batter_index = {
            key: self._prefix_index(game_counts, games)
            for key, game_counts in per_batter_game.items()}
        self._league_index = {
            season: self._prefix_index(game_counts, games)
            for season, game_counts in per_season_game.items()}

    @staticmethod
    def _prefix_index(game_counts: Mapping[int, Counter],
                      games: Mapping[int, tuple[int, str, str]]):
        ordered = sorted(
            game_counts,
            key=lambda gid: (games[gid][2], games[gid][1], gid))
        completed_dates = [games[gid][2] for gid in ordered]
        prefix: list[tuple[int, ...]] = []
        running = [0] * len(CATEGORIES)
        for gid in ordered:
            counts = game_counts[gid]
            for j, cat in enumerate(CATEGORIES):
                running[j] += counts.get(cat, 0)
            prefix.append(tuple(running))
        return completed_dates, prefix

    @staticmethod
    def _prior_counts(index, target_date: str) -> tuple[int, ...]:
        completed_dates, prefix = index
        # strictly prior: games completed ON the target date never feed
        k = bisect_left(completed_dates, target_date)
        return prefix[k - 1] if k else _ZERO

    @property
    def seasons(self) -> frozenset:
        return self._seasons

    def has_batter(self, batter_id: int) -> bool:
        return batter_id in self._batters_seen

    def batter_prior_counts(self, batter_id: int, season: int,
                            target_date: str) -> tuple[int, ...]:
        index = self._batter_index.get((season, batter_id))
        if index is None:
            return _ZERO
        return self._prior_counts(index, target_date)

    def league_prior_counts(self, season: int,
                            target_date: str) -> tuple[int, ...]:
        index = self._league_index.get(season)
        if index is None:
            return _ZERO
        return self._prior_counts(index, target_date)


def resolve_batter_id(name: Any, directory: Mapping[str, Sequence[int]]) -> int:
    """Resolve a batter name to the single StatsAPI person id in an
    injected directory (the pool itself carries ids only, so the
    name layer is the caller's; ambiguity refuses, never guesses).

    ``directory`` maps display names to candidate id lists, as a
    StatsAPI people search would return them."""
    if not isinstance(name, str) or not name.strip():
        raise PlateAppearanceEngineError(f"BATTER_NAME_INVALID:{name!r}")
    wanted = " ".join(name.split()).casefold()
    candidates: list[int] = []
    for display, ids in directory.items():
        if " ".join(str(display).split()).casefold() == wanted:
            candidates.extend(int(i) for i in ids)
    candidates = sorted(set(candidates))
    if not candidates:
        raise PlateAppearanceEngineError(
            f"PLATE_APPEARANCE_BATTER_UNKNOWN:{name}")
    if len(candidates) > 1:
        raise PlateAppearanceEngineError(
            f"PLATE_APPEARANCE_BATTER_IDENTITY_AMBIGUOUS:{name}:{candidates}")
    return candidates[0]


def _base_row(market: str, batter_id: int, target_date: str,
              season: int) -> dict[str, Any]:
    return {
        "sport": "MLB",
        "market": market,
        "player_id": batter_id,
        "target_game_date": target_date,
        "season": season,
        "engine": ENGINE_ID,
        "construction": CONSTRUCTION_ID,
        "spec_sha256": SPEC_SHA256,
        "pit_rule": PIT_RULE,
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }


def price_plate_appearance(pool: PlateAppearancePool | None, *,
                           market: str, batter_id: Any,
                           target_date: Any,
                           season: int | None = None) -> dict[str, Any]:
    """Price one batter's first-plate-appearance row under M49.

    Fail-closed in the wave-1 idiom: malformed inputs (non-integer
    batter id, malformed date, unknown market) raise
    PlateAppearanceEngineError; data-state refusals return a
    NOT_PRICED row with a named reason and no probabilities.
    Probabilities are the raw candidate — the spec's 1e-6 floor is
    scoring-only and is never applied to a price."""
    m = str(market or "").strip().upper()
    if m not in PA_MARKETS:
        raise PlateAppearanceEngineError(
            f"PLATE_APPEARANCE_MARKET_UNKNOWN:{market!r}")
    bid = _checked_id(batter_id, "PLATE_APPEARANCE_BATTER_ID_INVALID")
    tdate = _checked_date(target_date, "PLATE_APPEARANCE_TARGET_DATE_INVALID")
    if season is None:
        season = int(tdate[:4])
    elif isinstance(season, bool) or not isinstance(season, int):
        raise PlateAppearanceEngineError(
            f"PLATE_APPEARANCE_SEASON_INVALID:{season!r}")
    base = _base_row(m, bid, tdate, season)
    if m == MARKET_GROUPED_RESULT:
        return {**base, "status": "NOT_PRICED",
                "reason": "PLATE_APPEARANCE_GROUPED_PARTITION_UNVERIFIED"}
    if pool is None or season not in pool.seasons:
        return {**base, "status": "NOT_PRICED",
                "reason": "PLATE_APPEARANCE_POOL_UNAVAILABLE"}
    if not pool.has_batter(bid):
        return {**base, "status": "NOT_PRICED",
                "reason": "PLATE_APPEARANCE_BATTER_NOT_IN_POOL"}
    batter_counts = pool.batter_prior_counts(bid, season, tdate)
    n_b = sum(batter_counts)
    if n_b < MIN_PRIOR_PA:
        return {**base, "status": "NOT_PRICED",
                "reason": "PLATE_APPEARANCE_INSUFFICIENT_PRIOR_PA",
                "prior_pa": n_b, "min_prior_pa": MIN_PRIOR_PA}
    league_counts = pool.league_prior_counts(season, tdate)
    n_l = sum(league_counts)
    if n_l <= 0:
        return {**base, "status": "NOT_PRICED",
                "reason": "PLATE_APPEARANCE_LEAGUE_WINDOW_EMPTY"}
    dist = shrunk_distribution(batter_counts, league_counts)
    probs = dict(zip(CATEGORIES, dist))
    p_on_base = sum(probs[c] for c in REACHED_CATEGORIES)
    out = {**base, "status": "PRICED", "reason": "SUFFICIENCY_MET",
           "prior_pa": n_b, "league_prior_pa": n_l,
           "shrink_k": K_SHRINK,
           "shrink_weight_league": K_SHRINK / (n_b + K_SHRINK),
           "batter_empirical": dict(zip(
               CATEGORIES, (c / n_b for c in batter_counts))),
           "league_climatology": dict(zip(
               CATEGORIES, (c / n_l for c in league_counts))),
           "probabilities": probs}
    if m == MARKET_ON_BASE:
        out.update(p_on_base=float(p_on_base),
                   p_not_on_base=float(1.0 - p_on_base))
    return out
