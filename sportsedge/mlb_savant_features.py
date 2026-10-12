"""Statcast-derived MLB quality features from Baseball Savant (free, official).

Source: https://baseballsavant.mlb.com/statcast_search/csv (keyless CSV download,
the sanctioned free path per Isaac's data-sources reference). No credentialed
endpoints, no aggressive polling.

SCOPE (strict): ONLY Statcast-derived features. Box-score-derived pitching
metrics (FIP/SIERA, ERA/WHIP) belong to Phase 2 and are NOT duplicated here.
This module never computes anything a box score alone could produce.

Contents:
  1. Acquisition: schema-pinned CSV parse, fixture recording, rate discipline,
     fail-closed error codes on shape change or outage.
  2. Batter quality: xwOBA, barrel rate, hard-hit rate, exit velocity + trend.
  3. Pitcher quality: xwOBA-against, hard-hit/barrel suppression, whiff/chase.
  4. xK% engine (Derek Carty / THE BAT adoption): pitch-outcome decomposition
     (called strikes / fouls / in-play / whiffs as % of pitches), zero
     intercept, non-negative weights FIT FROM DATA (never hard-coded vibes).
     Validated out-of-sample vs raw K% before production use.
  5. Pitch-count-first prop projections: project expected pitch count FIRST,
     then derive K/BB/outs from per-pitch rates (never per-inning rates).
     Poisson percentile projections (p10/p50/p90) for card rendering.
  6. Team-level quality adjustment for the factor pipeline: savant runs
     adjustment (wRAA-style, declared scale) with a factor-coverage audit.

ENTRY POINT for the factor pipeline::

    savant_game_quality(
        *, as_of, home_team_id, away_team_id,
        home_pitcher_id, away_pitcher_id,
        home_batter_ids, away_batter_ids,
        snapshot=None, opener=None,
    ) -> dict

Returns per-team quality deltas, a runs adjustment, and a coverage audit.
On any Savant failure the result is ``{"status": "MISSING", "reason": <CODE>}``
and downstream MUST fall back to box-score features — a Savant outage never
raises into the pipeline. (``*_or_raise`` variants exist for offline tooling
only.)

STABILITY ASSESSMENT (de-facto, undocumented endpoint — recorded honestly):
  - Probed 2026-10-11: HTTP 200, 119 columns, ~5s per request for a 4-day
    window. Schema core fields stable vs the fields already consumed by
    sportsedge/statcast_daily_source.py.
  - OBSERVED CAP: statcast_search/csv silently truncates at 25,000 pitch rows
    (verified twice: two 15-day windows both returned exactly 25,000 rows
    covering only the most recent days of the window). There is no warning
    flag. This module fail-closes with SAVANT_RESPONSE_TRUNCATED on any
    at-cap response; keep request windows <= 4 days (regular season) so one
    batched request holds the whole window.
  - The endpoint is UNDOCUMENTED and can change without notice. Every parse
    is schema-pinned: any unexpected shape raises a SAVANT_* code and the
    public entry degrades to MISSING with that reason. Recorded fixtures in
    tests/fixtures/savant/ guard against silent drift.
  - Rate discipline: minimum 2s between requests (module-enforced), windows
    capped at 90 days, one batched request per window (never per-game
    polling), 36h snapshot TTL. This is research-volume usage of a free
    official download surface, not scraping.

IMPLEMENTATION REFERENCE: pybaseball (MIT-style, open source) was studied as
the reference Statcast client (x_account_review.md item 4) and deliberately
NOT vendored as a dependency:
  - Adopted: date-chunked batched requests (pybaseball chunks daily; this
    module chunks <=4 days — both stay under the 25k cap), and the
    `error`-column failure detection (SAVANT_ENDPOINT_ERROR above).
  - Rejected (documented): pandas/numpy/requests/tqdm dependency weight for
    what is one CSV download (this module is stdlib-only: csv+urllib, fitting
    the zero-infra posture); requests.get(..., timeout=None) can hang forever
    (this module always times out); ThreadPoolExecutor-parallel chunk
    fetching (this module is sequential with enforced rate discipline);
    365-day default cache (this module: 36h TTL + staleness fail-closed);
    and pybaseball does NOT detect the 25k silent truncation — this module's
    SAVANT_RESPONSE_TRUNCATED fail-closed is stricter than the reference.

Research only. No betting authority.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from .statcast_daily_source import (
    StatcastSnapshot,
    StatcastSourceError,
    aggregate_statcast,
    build_statcast_url,
    fetch_daily_statcast,
)

# ---------------------------------------------------------------------------
# Fail-closed error codes
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "statcast_search_csv_v2026-10-11"

# Columns this module depends on. Any missing column -> SAVANT_SCHEMA_UNEXPECTED.
REQUIRED_COLUMNS = frozenset({
    "game_date", "game_pk", "batter", "pitcher", "events", "description",
    "inning_topbot", "pitch_number",
    "estimated_woba_using_speedangle", "launch_speed", "launch_angle",
    "launch_speed_angle", "release_speed", "zone", "stand", "p_throws",
})

MIN_PA_BATTER = 25          # minimum plate appearances for batter quality
MIN_PITCHES_PITCHER = 100   # minimum pitches for pitcher quality / xK%
MIN_STARTS_PITCH_COUNT = 3  # minimum starts for a pitch-count projection
HARD_HIT_MPH = 95.0
BARREL_SPEED_ANGLE = 6       # Savant launch_speed_angle code for barrels
WOBA_RUNS_SCALE = 1.21      # DECLARED: wOBA-scale -> runs (FanGraphs convention)
RATE_LIMIT_SECONDS = 2.0    # minimum gap between Savant requests
SNAPSHOT_TTL_SECONDS = 36 * 60 * 60
# OBSERVED DE-FACTO (2026-10-11): statcast_search/csv silently caps responses
# at 25,000 pitch rows, returning a server-chosen subset (observed: the most
# recent days of the window). A 15-day regular-season window (~65k pitches)
# therefore returns INCOMPLETE data with no warning flag. Any response at the
# cap is treated as truncated (fail-closed); keep windows <= 4 days so one
# request holds the whole window.
STATCAST_ROW_CAP = 25000

WEIGHTS_ARTIFACT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "savant_xk_weights_v1.json")

# Pitch-outcome buckets for the xK% decomposition (THE BAT-style, zero intercept).
CALLED_STRIKE_DESCS = frozenset({"called_strike"})
WHIFF_DESCS = frozenset({"swinging_strike", "swinging_strike_blocked",
                         "missed_bunt"})
FOUL_DESCS = frozenset({"foul", "foul_tip", "foul_bunt", "bunt_foul_tip"})
IN_PLAY_DESCS = frozenset({"hit_into_play"})

# Terminal events counted as a pitcher-recorded out (documented approximation:
# fielders_choice excluded as ambiguous; errors are not outs).
OUT_EVENTS = frozenset({
    "strikeout", "strikeout_double_play", "field_out", "force_out",
    "grounded_into_double_play", "double_play", "sac_bunt", "sac_fly",
})
STRIKEOUT_EVENTS = frozenset({"strikeout", "strikeout_double_play"})
WALK_EVENTS = frozenset({"walk", "intent_walk"})

_last_request_monotonic = 0.0


class SavantFeatureError(ValueError):
    """Fail-closed Statcast feature error. message is a SAVANT_* code."""


def _rate_limit() -> None:
    global _last_request_monotonic
    now = time.monotonic()
    wait = RATE_LIMIT_SECONDS - (now - _last_request_monotonic)
    if wait > 0:
        time.sleep(wait)
    _last_request_monotonic = time.monotonic()


# ---------------------------------------------------------------------------
# 1. Acquisition: schema-pinned parse + fixture recording
# ---------------------------------------------------------------------------

def parse_statcast_csv(text: str, *, source: str = "fixture") -> list[dict[str, str]]:
    """Parse a statcast_search CSV with schema pinning.

    Raises SavantFeatureError with an explicit SAVANT_* code on any shape
    change: empty body, unparsable CSV, zero rows, or missing required
    columns. Never returns partial/garbled rows silently.
    """
    raw = text or ""
    if not raw.strip():
        raise SavantFeatureError("SAVANT_EMPTY_RESPONSE")
    try:
        rows = list(csv.DictReader(io.StringIO(raw)))
    except Exception as exc:
        raise SavantFeatureError("SAVANT_CSV_PARSE_FAILED") from exc
    if not rows:
        raise SavantFeatureError("SAVANT_NO_ROWS")
    cols = set(rows[0].keys() if rows else {})
    if "error" in cols:
        # The endpoint returns failures as a CSV with an `error` column
        # (pattern confirmed via the pybaseball reference implementation).
        msg = str(rows[0].get("error") or "unknown")[:200]
        raise SavantFeatureError(f"SAVANT_ENDPOINT_ERROR:{msg}")
    if len(rows) >= STATCAST_ROW_CAP:
        # Observed de-facto cap: the endpoint silently truncates at 25,000
        # rows with no warning flag. Treat a at-cap response as incomplete
        # rather than silently modeling on a server-chosen subset.
        raise SavantFeatureError(
            f"SAVANT_RESPONSE_TRUNCATED:rows={len(rows)}")
    missing = REQUIRED_COLUMNS - set(rows[0].keys() if rows else {})
    if missing:
        raise SavantFeatureError(
            "SAVANT_SCHEMA_UNEXPECTED:missing=" + ",".join(sorted(missing)))
    return rows


def record_statcast_fixture(csv_text: str, manifest: Mapping[str, Any],
                            path: str) -> dict[str, Any]:
    """Write a raw CSV fixture plus a JSON manifest (sha256, schema version).

    Returns the manifest dict that was written. Used for regression fixtures
    and the de-facto stability record.
    """
    digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    full_manifest = {
        "schema_version": SCHEMA_VERSION,
        "sha256": digest,
        "bytes": len(csv_text.encode("utf-8")),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **dict(manifest),
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(csv_text)
    with open(path + ".manifest.json", "w", encoding="utf-8") as fh:
        json.dump(full_manifest, fh, indent=2, sort_keys=True)
    return full_manifest


def _checked_snapshot(snapshot: StatcastSnapshot) -> StatcastSnapshot:
    """Fail closed on stale or empty snapshots."""
    if not isinstance(snapshot, StatcastSnapshot):
        raise SavantFeatureError("SAVANT_SNAPSHOT_UNVERIFIED")
    try:
        retrieved = datetime.fromisoformat(str(snapshot.retrieved_at))
    except (ValueError, TypeError) as exc:
        raise SavantFeatureError("SAVANT_SNAPSHOT_TIMESTAMP_UNVERIFIED") from exc
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - retrieved).total_seconds()
    if age > SNAPSHOT_TTL_SECONDS:
        raise SavantFeatureError("SAVANT_SNAPSHOT_STALE")
    if not snapshot.batter_rows or not snapshot.pitcher_rows:
        raise SavantFeatureError("SAVANT_SNAPSHOT_INCOMPLETE")
    return snapshot


def fetch_statcast_snapshot(
    start: date, end: date, *,
    opener: Callable,
    now: datetime | None = None,
) -> StatcastSnapshot:
    """Fetch one batched statcast_search window with rate discipline.

    One request per window — never per-game polling. Raises SavantFeatureError
    (never returns partial data). Offline/research tooling only; the factor
    pipeline should pass cached snapshots into savant_game_quality instead.
    Fixture recording is done from raw CSV text via record_statcast_fixture.
    """
    _rate_limit()
    current = now or datetime.now(timezone.utc)
    try:
        snapshot = fetch_daily_statcast(
            end_date=end, days=(end - start).days + 1,
            opener=opener, now=current,
        )
    except StatcastSourceError as exc:
        raise SavantFeatureError(f"SAVANT_FETCH_FAILED:{exc}") from exc
    except ValueError as exc:
        raise SavantFeatureError(f"SAVANT_WINDOW_INVALID:{exc}") from exc
    return _checked_snapshot(snapshot)


def snapshot_from_csv_rows(rows: Sequence[Mapping[str, str]], *, start: date,
                           end: date,
                           retrieved_at: datetime | None = None) -> StatcastSnapshot:
    """Build a StatcastSnapshot from already-parsed CSV rows (offline/tests)."""
    now = retrieved_at or datetime.now(timezone.utc)
    batter_rows, pitcher_rows = aggregate_statcast(
        rows, start_date=start, end_date=end, retrieved_at=now)
    return StatcastSnapshot(
        start_date=start.isoformat(), end_date=end.isoformat(),
        retrieved_at=now.isoformat(), source="BASEBALL_SAVANT_STATCAST",
        batter_rows=tuple(batter_rows), pitcher_rows=tuple(pitcher_rows),
        raw_pitch_rows=len(rows),
    )


# ---------------------------------------------------------------------------
# 2 & 3. Statcast-only quality features (never box-score-duplicated)
# ---------------------------------------------------------------------------

def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def batter_quality_features(agg_row: Mapping[str, Any]) -> dict[str, Any]:
    """Statcast-only batter quality from an aggregated snapshot row.

    Returns {"status": "AVAILABLE", "features": {...}} or
    {"status": "MISSING", "reason": <CODE>} on small samples.
    """
    pa = int(agg_row.get("pa") or 0)
    if pa < MIN_PA_BATTER:
        return {"status": "MISSING",
                "reason": f"SAVANT_BATTER_SAMPLE_TOO_SMALL:pa={pa}",
                "entity_id": str(agg_row.get("entity_id"))}
    features = {
        "pa": pa,
        "batted_balls": int(agg_row.get("batted_balls") or 0),
        # Quality signals a box score cannot see:
        "xwoba": _finite(agg_row.get("xwoba_contact")),
        "xba": _finite(agg_row.get("xba_contact")),
        "xslg": _finite(agg_row.get("xslg_contact")),
        "barrel_rate": _finite(agg_row.get("barrel_rate")),
        "hard_hit_rate": _finite(agg_row.get("hard_hit_rate")),
        "avg_exit_velocity": _finite(agg_row.get("avg_exit_velocity")),
        "avg_launch_angle": _finite(agg_row.get("avg_launch_angle")),
        # Discipline (Statcast-verified counts, not box-score rate stats):
        "k_rate": _finite(agg_row.get("k_per_pa")),
        "bb_rate": _finite(agg_row.get("bb_per_pa")),
        "window_start": agg_row.get("window_start"),
        "window_end": agg_row.get("window_end"),
        "latest_game_date": agg_row.get("latest_game_date"),
    }
    return {"status": "AVAILABLE", "features": features,
            "entity_id": str(agg_row.get("entity_id")),
            "schema_version": SCHEMA_VERSION}


def pitcher_quality_features(agg_row: Mapping[str, Any]) -> dict[str, Any]:
    """Statcast-only pitcher quality from an aggregated snapshot row.

    Suppression signals (xwOBA-against, hard-hit/barrel suppression, whiff and
    chase rates) — the contact-quality layer box scores cannot see. Deliberately
    excludes ERA/WHIP/FIP/SIERA (Phase 2 box-score scope).
    """
    pitches = int(agg_row.get("pitches") or 0)
    if pitches < MIN_PITCHES_PITCHER:
        return {"status": "MISSING",
                "reason": f"SAVANT_PITCHER_SAMPLE_TOO_SMALL:pitches={pitches}",
                "entity_id": str(agg_row.get("entity_id"))}
    features = {
        "pitches": pitches,
        "batters_faced": int(agg_row.get("pa") or 0),
        # Contact-suppression signals:
        "xwoba_against": _finite(agg_row.get("xwoba_contact")),
        "xba_against": _finite(agg_row.get("xba_contact")),
        "xslg_against": _finite(agg_row.get("xslg_contact")),
        "barrel_rate_against": _finite(agg_row.get("barrel_rate")),
        "hard_hit_rate_against": _finite(agg_row.get("hard_hit_rate")),
        "avg_exit_velo_against": _finite(agg_row.get("avg_exit_velocity")),
        # Swing-and-miss / chase (pitch-level, not box-score K/9):
        "whiff_rate": _finite(agg_row.get("whiff_rate")),
        "chase_rate": _finite(agg_row.get("chase_rate")),
        "k_per_pa": _finite(agg_row.get("k_per_pa")),
        "bb_per_pa": _finite(agg_row.get("bb_per_pa")),
        "avg_release_speed": _finite(agg_row.get("avg_release_speed")),
        "pitcher_hand": agg_row.get("pitcher_hand"),
        "window_start": agg_row.get("window_start"),
        "window_end": agg_row.get("window_end"),
        "latest_game_date": agg_row.get("latest_game_date"),
    }
    return {"status": "AVAILABLE", "features": features,
            "entity_id": str(agg_row.get("entity_id")),
            "schema_version": SCHEMA_VERSION}


def exit_velo_trend(recent: Mapping[str, Any],
                    season: Mapping[str, Any]) -> dict[str, Any]:
    """Recent (e.g. 14d) avg exit velo minus season avg: hot/cold contact trend.

    Both inputs are batter_quality_features outputs with status AVAILABLE.
    """
    for name, payload in (("recent", recent), ("season", season)):
        if not isinstance(payload, Mapping) or payload.get("status") != "AVAILABLE":
            return {"status": "MISSING",
                    "reason": f"SAVANT_TREND_INPUT_MISSING:{name}"}
    rbb = int(recent["features"].get("batted_balls") or 0)
    if rbb < 10:
        return {"status": "MISSING",
                "reason": f"SAVANT_TREND_SAMPLE_TOO_SMALL:batted_balls={rbb}"}
    r_ev = _finite(recent["features"].get("avg_exit_velocity"))
    s_ev = _finite(season["features"].get("avg_exit_velocity"))
    if r_ev is None or s_ev is None:
        return {"status": "MISSING", "reason": "SAVANT_TREND_EXIT_VELO_UNVERIFIED"}
    return {"status": "AVAILABLE",
            "exit_velo_trend_mph": round(r_ev - s_ev, 2),
            "recent_batted_balls": rbb}


# ---------------------------------------------------------------------------
# 4. xK% engine — pitch-outcome decomposition, zero intercept, fit from data
# ---------------------------------------------------------------------------

def pitch_outcome_rates(pitch_rows: Iterable[Mapping[str, str]],
                        pitcher_id: str | int) -> dict[str, Any]:
    """Per-pitch outcome decomposition for one pitcher.

    Buckets as % of pitches (zero intercept by construction — rates, no
    constant term): called strikes, whiffs, fouls, in-play, other.
    """
    pid = str(pitcher_id)
    n = 0
    buckets = {"called_strike": 0, "whiff": 0, "foul": 0, "in_play": 0,
               "other": 0}
    for row in pitch_rows:
        if str(row.get("pitcher")) != pid:
            continue
        n += 1
        desc = str(row.get("description") or "").strip().lower()
        if desc in CALLED_STRIKE_DESCS:
            buckets["called_strike"] += 1
        elif desc in WHIFF_DESCS:
            buckets["whiff"] += 1
        elif desc in FOUL_DESCS:
            buckets["foul"] += 1
        elif desc in IN_PLAY_DESCS:
            buckets["in_play"] += 1
        else:
            buckets["other"] += 1
    if n < MIN_PITCHES_PITCHER:
        return {"status": "MISSING",
                "reason": f"SAVANT_XK_SAMPLE_TOO_SMALL:pitches={n}",
                "entity_id": pid}
    rates = {k: round(v / n, 6) for k, v in buckets.items()}
    return {"status": "AVAILABLE", "entity_id": pid, "pitches": n,
            "rates": rates}


def _nnls_zero_intercept(X: list[list[float]], y: list[float],
                         w: list[float]) -> list[float]:
    """Non-negative least squares, zero intercept (Lawson-Hanson).

    Minimizes sum_i w_i * (x_i . beta - y_i)^2 subject to beta >= 0.
    Pure Python; p is tiny (4 features).
    """
    p = len(X[0])
    beta = [0.0] * p
    passive = set()  # indices allowed to be nonzero
    # Precompute weighted Gram matrix and X'y.
    G = [[0.0] * p for _ in range(p)]
    c = [0.0] * p
    for xi, yi, wi in zip(X, y, w):
        for a in range(p):
            c[a] += wi * xi[a] * yi
            for b in range(p):
                G[a][b] += wi * xi[a] * xi[b]
    for _ in range(4 * p + 10):
        # Dual vector for active (zero) set.
        grad = [c[a] - sum(G[a][b] * beta[b] for b in range(p))
                for a in range(p)]
        candidates = [a for a in range(p) if a not in passive and grad[a] > 1e-12]
        if not candidates:
            break
        j = max(candidates, key=lambda a: grad[a])
        passive.add(j)
        # Solve least squares on the passive set.
        while True:
            idx = sorted(passive)
            q = len(idx)
            # Normal equations on passive set via Gaussian elimination.
            M = [[G[idx[a]][idx[b]] for b in range(q)] for a in range(q)]
            rhs = [c[idx[a]] for a in range(q)]
            sol = _solve_linear(M, rhs)
            if sol is None:
                passive.discard(j)
                break
            trial = dict(zip(idx, sol))
            negative = [a for a in idx if trial[a] <= 1e-12]
            if not negative:
                for a in idx:
                    beta[a] = trial[a]
                break
            # Move toward feasibility.
            alpha = min(beta[a] / (beta[a] - trial[a]) for a in negative
                        if beta[a] > trial[a])
            for a in idx:
                beta[a] += alpha * (trial[a] - beta[a])
            for a in [a for a in idx if beta[a] <= 1e-12]:
                beta[a] = 0.0
                passive.discard(a)
    return [max(0.0, b) for b in beta]


def _solve_linear(M: list[list[float]],
                  rhs: list[float]) -> list[float] | None:
    n = len(rhs)
    A = [row[:] + [rhs[i]] for i, row in enumerate(M)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) < 1e-12:
            return None
        A[col], A[piv] = A[piv], A[col]
        for r in range(n):
            if r != col and A[r][col] != 0.0:
                factor = A[r][col] / A[col][col]
                for k in range(col, n + 1):
                    A[r][k] -= factor * A[col][k]
    return [A[i][n] / A[i][i] if abs(A[i][i]) > 1e-12 else 0.0
            for i in range(n)]


def fit_xk_weights(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fit xK% weights: K/pitch ~ w . outcome_rates, zero intercept, w >= 0.

    Each example: {"rates": {"called_strike","whiff","foul","in_play"}, 
    "k_per_pitch": float, "pitches": int}. Weighted by pitches. Raises
    SavantFeatureError when fewer than 10 examples (never fit on vibes).
    """
    keys = ("called_strike", "whiff", "foul", "in_play")
    X, y, w = [], [], []
    for i, ex in enumerate(examples):
        if not isinstance(ex, Mapping):
            raise SavantFeatureError(f"SAVANT_XK_EXAMPLE_NOT_OBJECT:{i}")
        rates = ex.get("rates")
        if not isinstance(rates, Mapping):
            raise SavantFeatureError(f"SAVANT_XK_RATES_MISSING:{i}")
        try:
            vec = [float(rates[k]) for k in keys]
            target = float(ex.get("k_per_pitch"))
            weight = float(ex.get("pitches"))
        except (KeyError, TypeError, ValueError) as exc:
            raise SavantFeatureError(f"SAVANT_XK_EXAMPLE_MALFORMED:{i}") from exc
        if any(not math.isfinite(v) or v < 0 for v in vec):
            raise SavantFeatureError(f"SAVANT_XK_RATES_INVALID:{i}")
        if not math.isfinite(target) or target < 0 or target > 1:
            raise SavantFeatureError(f"SAVANT_XK_TARGET_INVALID:{i}")
        if not math.isfinite(weight) or weight <= 0:
            raise SavantFeatureError(f"SAVANT_XK_WEIGHT_INVALID:{i}")
        X.append(vec)
        y.append(target)
        w.append(weight)
    if len(X) < 10:
        raise SavantFeatureError(
            f"SAVANT_XK_TOO_FEW_EXAMPLES:n={len(X)}")
    weights = _nnls_zero_intercept(X, y, w)
    # Weighted R^2 around zero (zero-intercept model: no centering).
    num = sum(wi * (yi - sum(xi[k] * weights[k] for k in range(4))) ** 2
              for xi, yi, wi in zip(X, y, w))
    den = sum(wi * yi * yi for yi, wi in zip(y, w))
    r2 = 1.0 - num / den if den > 0 else 0.0
    return {
        "weights": {"called_strike": round(weights[0], 6),
                    "whiff": round(weights[1], 6),
                    "foul": round(weights[2], 6),
                    "in_play": round(weights[3], 6)},
        "method": "nnls_zero_intercept",
        "n_examples": len(X),
        "total_pitches": int(sum(w)),
        "weighted_r2_zero_intercept": round(r2, 6),
        "schema_version": SCHEMA_VERSION,
    }


def load_default_xk_weights() -> dict[str, float]:
    """Load the recorded, harness-validated xK% weights artifact.

    Raises SavantFeatureError (SAVANT_XK_WEIGHTS_UNRECORDED) when the artifact
    is absent — xK% is then MISSING, never invented.
    """
    if not os.path.exists(WEIGHTS_ARTIFACT):
        raise SavantFeatureError("SAVANT_XK_WEIGHTS_UNRECORDED")
    try:
        with open(WEIGHTS_ARTIFACT, encoding="utf-8") as fh:
            artifact = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SavantFeatureError("SAVANT_XK_WEIGHTS_ARTIFACT_UNREADABLE") from exc
    if (artifact or {}).get("status") != "VALIDATED_OUT_OF_SAMPLE":
        # Isaac's bar: xK% weights are production-usable only after beating
        # raw K% out-of-sample. Anything else -> MISSING, never silent use.
        raise SavantFeatureError("SAVANT_XK_WEIGHTS_UNVALIDATED")
    weights = (artifact or {}).get("weights")
    if not isinstance(weights, Mapping):
        raise SavantFeatureError("SAVANT_XK_WEIGHTS_ARTIFACT_MALFORMED")
    out = {}
    for k in ("called_strike", "whiff", "foul", "in_play"):
        v = _finite(weights.get(k))
        if v is None or v < 0:
            raise SavantFeatureError("SAVANT_XK_WEIGHTS_ARTIFACT_MALFORMED")
        out[k] = v
    return out


def xk_per_pitch(rates: Mapping[str, float],
                 weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    """Expected strikeouts per pitch from the outcome decomposition.

    xK% = w_called*called% + w_whiff*whiff% + w_foul*foul% + w_inplay*inplay%.
    Zero intercept; weights default to the recorded validated artifact.
    """
    try:
        w = dict(weights) if weights is not None else load_default_xk_weights()
    except SavantFeatureError as exc:
        return {"status": "MISSING", "reason": str(exc)}
    try:
        xk = sum(float(rates[k]) * w[k]
                 for k in ("called_strike", "whiff", "foul", "in_play"))
    except (KeyError, TypeError, ValueError) as exc:
        return {"status": "MISSING",
                "reason": f"SAVANT_XK_RATES_MALFORMED:{exc}"}
    if not math.isfinite(xk) or xk < 0 or xk > 1:
        return {"status": "MISSING", "reason": "SAVANT_XK_VALUE_INVALID"}
    return {"status": "AVAILABLE", "xk_per_pitch": round(xk, 6)}


def pitcher_strikeout_features(pitch_rows: Iterable[Mapping[str, str]],
                               pitcher_id: str | int,
                               weights: Mapping[str, float] | None = None
                               ) -> dict[str, Any]:
    """xK% vs raw K% for one pitcher (both per-pitch — no per-inning rates).

    Returns the decomposition rates, xK% (model), and raw K/pitch (baseline)
    so the harness can compare them head-to-head out-of-sample.
    """
    rows = list(pitch_rows)
    pid = str(pitcher_id)
    decomp = pitch_outcome_rates(rows, pid)
    if decomp.get("status") != "AVAILABLE":
        return decomp
    xk = xk_per_pitch(decomp["rates"], weights)
    # Raw K per pitch: terminal strikeout events / pitches (same denominator).
    k_events = sum(
        1 for r in rows
        if str(r.get("pitcher")) == pid
        and str(r.get("events") or "").strip() in STRIKEOUT_EVENTS
    )
    raw_k_per_pitch = k_events / decomp["pitches"] if decomp["pitches"] else None
    result = {"status": "AVAILABLE", "entity_id": pid,
              "pitches": decomp["pitches"], "rates": decomp["rates"],
              "raw_k_per_pitch": (round(raw_k_per_pitch, 6)
                                  if raw_k_per_pitch is not None else None)}
    if xk.get("status") == "AVAILABLE":
        result["xk_per_pitch"] = xk["xk_per_pitch"]
    else:
        result["xk_status"] = "MISSING"
        result["xk_reason"] = xk.get("reason")
    return result


# ---------------------------------------------------------------------------
# 5. Pitch-count-first prop projections + percentile projections
# ---------------------------------------------------------------------------

def pitch_count_history(pitch_rows: Iterable[Mapping[str, str]],
                        pitcher_id: str | int) -> dict[str, Any]:
    """Actual pitches per outing for one pitcher, chronological.

    Counts pitch rows grouped by game_pk — Statcast gives exact pitch counts,
    no box-score estimation. Outings with <10 pitches are excluded (relief
    fragments would corrupt a starter projection).
    """
    pid = str(pitcher_id)
    per_game: dict[str, dict[str, Any]] = {}
    for row in pitch_rows:
        if str(row.get("pitcher")) != pid:
            continue
        gpk = str(row.get("game_pk") or "").strip()
        if not gpk:
            continue
        cell = per_game.setdefault(gpk, {"pitches": 0, "game_date": None})
        cell["pitches"] += 1
        gd = str(row.get("game_date") or "").strip() or None
        if gd and (cell["game_date"] is None or gd > cell["game_date"]):
            cell["game_date"] = gd
    outings = sorted(
        (c for c in per_game.values() if c["pitches"] >= 10),
        key=lambda c: c["game_date"] or "",
    )
    if len(outings) < MIN_STARTS_PITCH_COUNT:
        return {"status": "MISSING",
                "reason": f"SAVANT_PITCH_COUNT_TOO_FEW_STARTS:n={len(outings)}",
                "entity_id": pid}
    return {"status": "AVAILABLE", "entity_id": pid,
            "outings": [{"game_date": c["game_date"], "pitches": c["pitches"]}
                        for c in outings]}


def project_pitch_count(pitch_count_hist: Mapping[str, Any]) -> dict[str, Any]:
    """Expected pitch count FIRST: mean of prior outings (pitch-count-first).

    All downstream K/BB/outs projections derive from per-pitch rates against
    this count — never from per-inning rates.
    """
    if not isinstance(pitch_count_hist, Mapping) \
            or pitch_count_hist.get("status") != "AVAILABLE":
        return {"status": "MISSING",
                "reason": "SAVANT_PITCH_COUNT_HISTORY_MISSING"}
    outings = pitch_count_hist.get("outings") or []
    counts = [o["pitches"] for o in outings
              if isinstance(o, Mapping) and isinstance(o.get("pitches"), int)]
    if len(counts) < MIN_STARTS_PITCH_COUNT:
        return {"status": "MISSING",
                "reason": f"SAVANT_PITCH_COUNT_TOO_FEW_STARTS:n={len(counts)}"}
    mean = sum(counts) / len(counts)
    return {"status": "AVAILABLE",
            "expected_pitches": round(mean, 2),
            "n_starts": len(counts),
            "min_pitches": min(counts), "max_pitches": max(counts)}


def per_pitch_event_rates(pitch_rows: Iterable[Mapping[str, str]],
                          pitcher_id: str | int) -> dict[str, Any]:
    """Per-pitch K / BB / out rates for one pitcher (zero intercept by nature).

    K per pitch = strikeout terminal events / pitches; BB per pitch = walk
    events / pitches; out per pitch = OUT_EVENTS / pitches. Same denominator
    the pitch-count projection multiplies against.
    """
    pid = str(pitcher_id)
    n = k = bb = outs = 0
    for row in pitch_rows:
        if str(row.get("pitcher")) != pid:
            continue
        n += 1
        event = str(row.get("events") or "").strip()
        if event in STRIKEOUT_EVENTS:
            k += 1
        if event in WALK_EVENTS:
            bb += 1
        if event in OUT_EVENTS:
            outs += 1
    if n < MIN_PITCHES_PITCHER:
        return {"status": "MISSING",
                "reason": f"SAVANT_PER_PITCH_SAMPLE_TOO_SMALL:pitches={n}",
                "entity_id": pid}
    return {"status": "AVAILABLE", "entity_id": pid, "pitches": n,
            "k_per_pitch": round(k / n, 6),
            "bb_per_pitch": round(bb / n, 6),
            "out_per_pitch": round(outs / n, 6)}


def poisson_quantiles(lam: float,
                      quantiles: Sequence[float] = (0.10, 0.50, 0.90)
                      ) -> dict[str, int]:
    """Exact Poisson quantiles (documented approximation for prop counts).

    A Poisson with mean = E[pitches] * per-pitch rate models the count;
    treating the pitch count as fixed at its expectation is declared here —
    the projection carries count uncertainty, not pitch-count uncertainty.
    """
    lam_f = _finite(lam)
    if lam_f is None or lam_f < 0:
        raise SavantFeatureError("SAVANT_POISSON_LAMBDA_INVALID")
    if lam_f == 0:
        # Degenerate Poisson(0): all mass at 0. Valid, not an error.
        return {f"p{int(round(float(q) * 100))}": 0 for q in quantiles}
    out: dict[str, int] = {}
    for q in quantiles:
        qf = float(q)
        if not 0.0 < qf < 1.0:
            raise SavantFeatureError("SAVANT_QUANTILE_INVALID")
        # Exact CDF accumulation from k=0.
        term = math.exp(-lam_f)  # P(X=0)
        cdf = term
        k = 0
        while cdf < qf:
            k += 1
            term *= lam_f / k
            cdf += term
            if k > 10_000:
                raise SavantFeatureError("SAVANT_QUANTILE_NONCONVERGENT")
        out[f"p{int(round(qf * 100))}"] = k
    return out


def pitcher_prop_projection(*, expected_pitches: float,
                            k_per_pitch: float | None = None,
                            xk_per_pitch: float | None = None,
                            bb_per_pitch: float | None = None,
                            out_per_pitch: float | None = None,
                            k_source: str = "xk") -> dict[str, Any]:
    """Pitch-count-first prop projections with percentile bands.

    Projects E[pitches] FIRST, then mean = E[pitches] * per-pitch rate for
    K/BB/outs. ``k_source`` selects "xk" (decomposition) or "raw" (raw K%).
    Emits p10/p50/p90 percentile projections — the concrete uncertainty
    implementation for MLB prop outputs; card renderers display the
    ``percentiles`` block.

    NOTE (evaluation-side intelligence only, NEVER a pricing input): the
    observation that books shade pitcher props to overs must not enter any
    projection here.
    """
    ep = _finite(expected_pitches)
    if ep is None or ep <= 0:
        return {"status": "MISSING", "reason": "SAVANT_EXPECTED_PITCHES_INVALID"}
    k_rate = xk_per_pitch if k_source == "xk" else k_per_pitch
    if k_source not in ("xk", "raw"):
        return {"status": "MISSING", "reason": "SAVANT_K_SOURCE_INVALID"}
    k_rate = _finite(k_rate)
    bb_rate = _finite(bb_per_pitch)
    out_rate = _finite(out_per_pitch)
    if k_rate is None or not 0 <= k_rate <= 1:
        return {"status": "MISSING", "reason": "SAVANT_K_RATE_UNVERIFIED"}
    projections: dict[str, Any] = {
        "status": "AVAILABLE",
        "expected_pitches": round(ep, 2),
        "k_source": k_source,
        "engine": "savant_pitch_count_first_v1",
        "schema_version": SCHEMA_VERSION,
    }
    try:
        k_mean = ep * k_rate
        projections["PITCHER_K"] = {
            "mean": round(k_mean, 3),
            "percentiles": poisson_quantiles(k_mean),
        }
    except SavantFeatureError as exc:
        return {"status": "MISSING", "reason": str(exc)}
    if bb_rate is not None and 0 <= bb_rate <= 1:
        bb_mean = ep * bb_rate
        projections["PITCHER_BB"] = {
            "mean": round(bb_mean, 3),
            "percentiles": poisson_quantiles(bb_mean),
        }
    if out_rate is not None and 0 <= out_rate <= 1:
        out_mean = ep * out_rate
        projections["PITCHER_OUTS"] = {
            "mean": round(out_mean, 3),
            "percentiles": poisson_quantiles(out_mean),
        }
    return projections


def attach_prop_percentiles(priced_row: dict[str, Any],
                            projection: Mapping[str, Any] | None) -> dict[str, Any]:
    """Attach a percentile block to a priced prop row for card rendering.

    No-op (row unchanged) when the projection is missing/invalid — Savant
    outages never break card output. Card renderers should display
    ``row["percentiles"]`` = {"market","mean","p10","p50","p90"} when present.
    """
    if not isinstance(priced_row, dict):
        return priced_row
    if not isinstance(projection, Mapping) \
            or projection.get("status") != "AVAILABLE":
        return priced_row
    market = str(priced_row.get("market") or "").upper()
    block = projection.get(market)
    if not isinstance(block, Mapping):
        return priced_row
    pct = block.get("percentiles")
    if not isinstance(pct, Mapping):
        return priced_row
    priced_row["percentiles"] = {
        "market": market,
        "mean": block.get("mean"),
        "p10": pct.get("p10"), "p50": pct.get("p50"), "p90": pct.get("p90"),
        "engine": projection.get("engine"),
    }
    return priced_row


# ---------------------------------------------------------------------------
# 6. Team-level quality adjustment — factor-pipeline entry point
# ---------------------------------------------------------------------------

def league_average_xwoba(snapshot: StatcastSnapshot,
                         role: str = "BATTER") -> dict[str, Any]:
    """League-average xwOBA from a snapshot (the baseline quality is measured
    against). Computed from the same window — no external priors."""
    rows = snapshot.batter_rows if role == "BATTER" else snapshot.pitcher_rows
    vals = [float(r["xwoba_contact"]) for r in rows
            if r.get("xwoba_contact") is not None]
    if len(vals) < 50:
        return {"status": "MISSING",
                "reason": f"SAVANT_LEAGUE_AVG_SAMPLE_TOO_SMALL:n={len(vals)}"}
    return {"status": "AVAILABLE",
            "league_xwoba": round(sum(vals) / len(vals), 4),
            "n_entities": len(vals)}


def team_batter_quality(pitch_rows: Iterable[Mapping[str, str]],
                        game_teams: Mapping[str, Sequence[int]],
                        batter_ids: Sequence[str | int] | None = None,
                        min_pa: int = MIN_PA_BATTER) -> dict[str, Any]:
    """PA-weighted team xwOBA from pitch-level data (no box scores).

    ``game_teams``: game_pk -> (away_team_id, home_team_id). The batting team
    for each pitch is resolved via ``inning_topbot`` (Top=away bats,
    Bot=home bats). When ``batter_ids`` is given, only those batters count
    (e.g. a projected lineup); otherwise all batters observed for the team.
    """
    wanted = {str(b) for b in batter_ids} if batter_ids else None
    pa_woba: dict[str, float] = {}
    pa_count: dict[str, int] = {}
    for row in pitch_rows:
        if wanted is not None and str(row.get("batter")) not in wanted:
            continue
        event = str(row.get("events") or "").strip()
        if not event:
            continue  # not a terminal PA pitch
        xw = _finite(row.get("estimated_woba_using_speedangle"))
        if xw is None:
            continue
        gpk = str(row.get("game_pk") or "").strip()
        teams = game_teams.get(gpk)
        if not teams or len(teams) != 2:
            continue
        topbot = str(row.get("inning_topbot") or "").strip()
        if topbot == "Top":
            team = str(teams[0])
        elif topbot == "Bot":
            team = str(teams[1])
        else:
            continue
        pa_woba[team] = pa_woba.get(team, 0.0) + xw
        pa_count[team] = pa_count.get(team, 0) + 1
    out = {}
    for team, total in pa_woba.items():
        n = pa_count[team]
        if n < min_pa:
            out[team] = {"status": "MISSING",
                         "reason": f"SAVANT_TEAM_PA_TOO_SMALL:pa={n}"}
        else:
            out[team] = {"status": "AVAILABLE", "team_xwoba": round(total / n, 4),
                         "pa": n}
    if not out:
        return {"status": "MISSING", "reason": "SAVANT_TEAM_QUALITY_NO_PA"}
    return {"status": "AVAILABLE", "teams": out}


def savant_runs_adjustment(*, team_xwoba: float, league_xwoba: float,
                           pa: int, pitcher_xwoba_against: float | None = None,
                           pitcher_batters_faced: int = 0) -> dict[str, Any]:
    """Convert Statcast quality deltas to a runs adjustment (wRAA-style).

    runs ≈ ((xwOBA − lgxwOBA) / WOBA_RUNS_SCALE) × PA — the standard linear-
    weights identity on the wOBA scale (WOBA_RUNS_SCALE=1.21 declared, not
    fit). Pitcher suppression enters symmetrically as runs prevented.
    Positive = more runs expected for the pitcher's opponent... (sign
    convention documented in the return: batting runs ADDED to the team's own
    expected score; pitcher suppression SUBTRACTED from the opponent's).
    """
    for name, val in (("team_xwoba", team_xwoba), ("league_xwoba", league_xwoba)):
        v = _finite(val)
        if v is None or not 0.150 <= v <= 0.550:
            return {"status": "MISSING",
                    "reason": f"SAVANT_XWOBA_RANGE_INVALID:{name}"}
    if not isinstance(pa, int) or pa <= 0:
        return {"status": "MISSING", "reason": "SAVANT_PA_INVALID"}
    batting_runs = ((float(team_xwoba) - float(league_xwoba))
                    / WOBA_RUNS_SCALE) * pa
    pitching_runs = 0.0
    if pitcher_xwoba_against is not None:
        px = _finite(pitcher_xwoba_against)
        if px is None or not 0.150 <= px <= 0.550:
            return {"status": "MISSING",
                    "reason": "SAVANT_PITCHER_XWOBA_RANGE_INVALID"}
        if not isinstance(pitcher_batters_faced, int) or pitcher_batters_faced < 0:
            return {"status": "MISSING", "reason": "SAVANT_BF_INVALID"}
        # Suppression vs league: negative when the pitcher suppresses quality.
        pitching_runs = ((px - float(league_xwoba)) / WOBA_RUNS_SCALE) \
            * pitcher_batters_faced
    return {"status": "AVAILABLE",
            "batting_runs_added": round(batting_runs, 3),
            "pitching_runs_allowed_vs_avg": round(pitching_runs, 3),
            "woba_runs_scale": WOBA_RUNS_SCALE}


def savant_game_quality(*, as_of: datetime,
                        home_team_id: int | str, away_team_id: int | str,
                        home_pitcher_id: int | str | None,
                        away_pitcher_id: int | str | None,
                        home_batter_ids: Sequence[int | str] | None = None,
                        away_batter_ids: Sequence[int | str] | None = None,
                        snapshot: StatcastSnapshot | None = None,
                        opener: Callable | None = None,
                        window_days: int = 30) -> dict[str, Any]:
    """Factor-pipeline entry point: Statcast quality for one game.

    Parameters
    ----------
    as_of: timezone-aware datetime; only data with game_date < as_of's date
        is used (strictly prior — no lookahead).
    home_team_id / away_team_id: MLB StatsAPI team ids.
    home_pitcher_id / away_pitcher_id: probable-starter MLBAM ids (None when
        unverified — the pitcher lane is then MISSING, not invented).
    home_batter_ids / away_batter_ids: projected lineup MLBAM ids (None ->
        team-level quality is MISSING; the game is never priced on an
        invented lineup).
    snapshot: a StatcastSnapshot with window_end strictly before as_of's
        date. When None, one is fetched (offline/research use; the live
        pipeline should pass a cached snapshot).
    opener: urllib-compatible opener for the fetch path (tests).

    Returns a dict with:
      status: "AVAILABLE" | "PARTIAL" | "MISSING"
      reason: SAVANT_* code when not AVAILABLE
      as_of, window_start, window_end
      teams: {home: {...}, away: {...}} each with batter_quality,
          pitcher_quality, runs_adjustment (or MISSING with reason)
      coverage_audit: {"verified_used": [...], "missing": [...]}
      schema_version

    PARTIAL means at least one lane resolved; downstream uses what is
    verified and falls back to box-score features for the rest.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise SavantFeatureError("SAVANT_AS_OF_TIMEZONE_REQUIRED")
    if not isinstance(window_days, int) or not 7 <= window_days <= 90:
        raise SavantFeatureError("SAVANT_WINDOW_DAYS_INVALID")

    def missing(reason: str) -> dict[str, Any]:
        return {
            "status": "MISSING", "reason": reason,
            "as_of": as_of.isoformat(), "schema_version": SCHEMA_VERSION,
            "coverage_audit": {"verified_used": [], "missing": [reason]},
        }

    snap = snapshot
    if snap is None:
        if opener is None:
            return missing("SAVANT_NO_SNAPSHOT_AND_NO_OPENER")
        end = as_of.astimezone(timezone.utc).date() - timedelta(days=1)
        start = end - timedelta(days=window_days - 1)
        try:
            snap = fetch_statcast_snapshot(start, end, opener=opener, now=as_of)
        except SavantFeatureError as exc:
            return missing(str(exc))
    try:
        snap = _checked_snapshot(snap)
    except SavantFeatureError as exc:
        return missing(str(exc))

    window_end = date.fromisoformat(snap.end_date)
    if window_end >= as_of.astimezone(timezone.utc).date():
        return missing("SAVANT_SNAPSHOT_LOOKAHEAD_RISK")

    league = league_average_xwoba(snap, role="BATTER")
    lg = league["league_xwoba"] if league.get("status") == "AVAILABLE" else None

    by_batter = {str(r["entity_id"]): r for r in snap.batter_rows}
    by_pitcher = {str(r["entity_id"]): r for r in snap.pitcher_rows}
    verified_used: list[str] = []
    missing_reasons: list[str] = []
    teams: dict[str, Any] = {}

    for side, team_id, pitcher_id, batter_ids in (
            ("home", home_team_id, home_pitcher_id, home_batter_ids),
            ("away", away_team_id, away_pitcher_id, away_batter_ids)):
        lane: dict[str, Any] = {"team_id": str(team_id)}
        # --- batter lane: PA-weighted xwOBA over the given lineup ids ---
        if batter_ids:
            quals = []
            for bid in batter_ids:
                row = by_batter.get(str(bid))
                if row is None:
                    continue
                q = batter_quality_features(row)
                if q.get("status") == "AVAILABLE":
                    quals.append(q["features"])
            if quals:
                total_pa = sum(q["pa"] for q in quals)
                xws = [q["xwoba"] for q in quals if q["xwoba"] is not None]
                if xws and total_pa > 0:
                    lineup_xwoba = sum(
                        q["xwoba"] * q["pa"] for q in quals
                        if q["xwoba"] is not None) / total_pa
                    lane["batter_quality"] = {
                        "status": "AVAILABLE",
                        "lineup_xwoba": round(lineup_xwoba, 4),
                        "lineup_pa": total_pa,
                        "batters_resolved": len(quals),
                        "batters_requested": len(list(batter_ids)),
                    }
                    verified_used.append(f"savant_batter_xwoba:{side}")
                else:
                    lane["batter_quality"] = {
                        "status": "MISSING",
                        "reason": "SAVANT_LINEUP_XWOBA_UNVERIFIED"}
                    missing_reasons.append(f"savant_batter_xwoba:{side}")
            else:
                lane["batter_quality"] = {
                    "status": "MISSING",
                    "reason": "SAVANT_LINEUP_UNRESOLVED"}
                missing_reasons.append(f"savant_batter_xwoba:{side}")
        else:
            lane["batter_quality"] = {
                "status": "MISSING",
                "reason": "SAVANT_LINEUP_IDS_NOT_SUPPLIED"}
            missing_reasons.append(f"savant_batter_xwoba:{side}")
        # --- pitcher lane ---
        if pitcher_id is not None:
            prow = by_pitcher.get(str(pitcher_id))
            if prow is None:
                lane["pitcher_quality"] = {
                    "status": "MISSING",
                    "reason": "SAVANT_PITCHER_NOT_IN_SNAPSHOT"}
                missing_reasons.append(f"savant_pitcher_quality:{side}")
            else:
                pq = pitcher_quality_features(prow)
                if pq.get("status") == "AVAILABLE":
                    lane["pitcher_quality"] = {
                        "status": "AVAILABLE", **pq["features"]}
                    verified_used.append(f"savant_pitcher_quality:{side}")
                else:
                    lane["pitcher_quality"] = {
                        "status": "MISSING", "reason": pq.get("reason")}
                    missing_reasons.append(f"savant_pitcher_quality:{side}")
        else:
            lane["pitcher_quality"] = {
                "status": "MISSING",
                "reason": "SAVANT_PROBABLE_PITCHER_UNVERIFIED"}
            missing_reasons.append(f"savant_pitcher_quality:{side}")
        # --- runs adjustment lane ---
        bq = lane["batter_quality"]
        pq = lane["pitcher_quality"]
        if lg is not None and bq.get("status") == "AVAILABLE":
            pa_est = int(bq["lineup_pa"])
            px = pq.get("xwoba_against") if pq.get("status") == "AVAILABLE" else None
            bf = int(pq.get("batters_faced") or 0) if pq.get("status") == "AVAILABLE" else 0
            adj = savant_runs_adjustment(
                team_xwoba=float(bq["lineup_xwoba"]), league_xwoba=float(lg),
                pa=pa_est,
                pitcher_xwoba_against=(float(px) if px is not None else None),
                pitcher_batters_faced=bf)
            if adj.get("status") == "AVAILABLE":
                lane["runs_adjustment"] = adj
                verified_used.append(f"savant_runs_adjustment:{side}")
            else:
                lane["runs_adjustment"] = {
                    "status": "MISSING", "reason": adj.get("reason")}
                missing_reasons.append(f"savant_runs_adjustment:{side}")
        else:
            lane["runs_adjustment"] = {
                "status": "MISSING",
                "reason": "SAVANT_RUNS_ADJUSTMENT_INPUTS_UNVERIFIED"}
            missing_reasons.append(f"savant_runs_adjustment:{side}")
        teams[side] = lane

    if verified_used and not missing_reasons:
        status = "AVAILABLE"
    elif verified_used:
        status = "PARTIAL"
    else:
        return missing("SAVANT_ALL_LANES_MISSING")
    return {
        "status": status,
        "as_of": as_of.isoformat(),
        "window_start": snap.start_date,
        "window_end": snap.end_date,
        "league_xwoba": lg,
        "teams": teams,
        "coverage_audit": {"verified_used": verified_used,
                           "missing": missing_reasons},
        "schema_version": SCHEMA_VERSION,
    }


__all__ = [
    "SCHEMA_VERSION",
    "SavantFeatureError",
    "parse_statcast_csv",
    "record_statcast_fixture",
    "fetch_statcast_snapshot",
    "snapshot_from_csv_rows",
    "batter_quality_features",
    "pitcher_quality_features",
    "exit_velo_trend",
    "pitch_outcome_rates",
    "fit_xk_weights",
    "load_default_xk_weights",
    "xk_per_pitch",
    "pitcher_strikeout_features",
    "pitch_count_history",
    "project_pitch_count",
    "per_pitch_event_rates",
    "poisson_quantiles",
    "pitcher_prop_projection",
    "attach_prop_percentiles",
    "league_average_xwoba",
    "team_batter_quality",
    "savant_runs_adjustment",
    "savant_game_quality",
]
