"""NFL kicking probability engine (research): FG made, PAT made,
kicking points -- from free nflverse play-by-play.

Markets (matrix N43/N44/N45): FG_MADE (field goals made O/U),
XP_MADE (extra points made O/U), KICKING_POINTS (FG*3 + XP O/U).
Kicker identity is fixture-stable (one kicker attempts essentially
all of a team's kicks in a game), so -- unlike the N17-N36 volume
props -- this family does not need the held participation/role
basis; its inputs are the kicker's own verified kicking record.

Architecture (empirical, strictly point-in-time; every game row
used has kickoff strictly before the priced game's kickoff):

    FG attempts/game   trailing per-game attempt counts for the
                       kicker, shrunk toward the league count
                       distribution (counts + M * league) /
                       (n + M) -- the program's proven count-
                       distribution construction.
    Attempt distance   trailing attempt mix over distance bands,
    mix                shrunk toward the league mix.
    Make rate by band  kicker's trailing makes/attempts per band,
                       empirical-Bayes shrunk toward the declared
                       league band rate (prior strength 20 att).
    FG made count      sum over attempt counts of
                       P(attempts) * Binomial(attempts, p_bar),
                       p_bar = mix-weighted band make rate.
    PAT attempts/game  trailing per-game PAT attempt counts for
                       the kicker's team kicking record, shrunk
                       the same way; make rate shrunk toward the
                       league PAT rate (prior strength 30 att).
    Kicking points     convolution of 3*FG_made and XP_made.

Declared approximations (honest accounting, harness decides):
- Within a game, attempts are treated as independent Bernoulli
  draws at the mix-weighted make rate; the distance mix is the
  trailing mix, not conditioned on the opponent or game script.
- Kicking points convolves FG and XP as independent, although
  both scale with team scoring output; the shared team-output
  factor is NOT modeled in v1. The trailing raw kicking-points
  distribution is returned alongside as a diagnostic readout.

League priors below are declared constants (long-run modern-era
league aggregates, rounded; documented a priori, not tuned on any
evaluation window -- the harness may replace them).

Fail-closed: missing kicker identity, missing kickoffs, fewer
than MIN_GAMES strictly-prior kicker games, or a window with zero
FG attempts all raise NflKickingError with a reason code.

GOVERNANCE: this engine is research only. The canonical path
still terminates NFL props at GOVERNANCE_NO_ENGINE
(config/football_prop_engine_surface.json declares NO_ENGINE for
NFL props until an independently validated probability engine is
promoted); nothing here changes that surface or any card row.
Research only. No betting authority, no staking.
"""
from __future__ import annotations

import gzip
import io
import math
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.request import Request, urlopen

ENGINE_ID = "NFL_KICKING_EMPIRICAL"
ENGINE_VERSION = "nfl_kicking_empirical_v1_20261015"

NFLVERSE_RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
NFLVERSE_GAMES_CSV = (
    "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
)
USER_AGENT = "SportsEdge/1.0"

SOURCE_URLS = {
    "pbp": NFLVERSE_RELEASE + "/pbp/play_by_play_{season}.csv.gz",
    "games": NFLVERSE_GAMES_CSV,
}

# Model gates / hyper-parameters (documented a priori).
MIN_GAMES = 5            # minimum strictly-prior games for the kicker
TRAILING_GAMES_K = 16    # trailing window (kicker games)
COUNT_SHRINK_M = 8.0     # pseudo-games of league count distribution
MIX_SHRINK_ATT = 15.0    # pseudo-attempts of league distance mix
BAND_SHRINK_ATT = 20.0   # pseudo-attempts of league band make rate
PAT_SHRINK_ATT = 30.0    # pseudo-attempts of league PAT make rate

# Distance bands (attempt kick distance, yards): (lo, hi, league
# make rate, league attempt-mix share). Declared long-run priors.
DISTANCE_BANDS = (
    (0, 29, 0.972, 0.16),
    (30, 39, 0.905, 0.30),
    (40, 49, 0.798, 0.30),
    (50, 59, 0.652, 0.20),
    (60, 999, 0.420, 0.04),
)
LEAGUE_PAT_MAKE_RATE = 0.950

# Declared league per-team-game count distributions (counts 0..6,
# the last cell is 6+ folded at 6).
LEAGUE_FG_ATTEMPT_COUNTS = (0.14, 0.30, 0.28, 0.16, 0.08, 0.03, 0.01)
LEAGUE_PAT_ATTEMPT_COUNTS = (0.08, 0.22, 0.30, 0.22, 0.11, 0.05, 0.02)

MAX_COUNT = 12  # PMFs are carried to this count; residual tail
# mass is folded into the last cell so each PMF sums to 1 exactly
# (settlement-mass discipline).


class NflKickingError(ValueError):
    """Fail-closed error with a machine-readable reason code."""


# ---------------------------------------------------------------------------
# Count-distribution helpers
# ---------------------------------------------------------------------------

def _shrunk_count_pmf(counts: Sequence[int],
                      league: Sequence[float]) -> dict[int, float]:
    """(counts + M * league) / (n + M) over the observed support,
    extended with the league support; folded at MAX_COUNT."""
    n = len(counts)
    raw: dict[int, float] = {}
    for c in counts:
        raw[c] = raw.get(c, 0.0) + 1.0
    support = sorted(set(raw) | set(range(len(league))))
    pmf: dict[int, float] = {}
    for k in support:
        pmf[k] = (raw.get(k, 0.0) + COUNT_SHRINK_M * league[k]) \
            / (n + COUNT_SHRINK_M) if k < len(league) else raw.get(k, 0.0) / (n + COUNT_SHRINK_M)
    return _fold(pmf)


def _fold(pmf: Mapping[int, float],
          max_count: int = MAX_COUNT) -> dict[int, float]:
    """Fold mass above max_count into the max_count cell and
    renormalize away float dust so the PMF sums to 1."""
    out: dict[int, float] = {}
    for k, v in pmf.items():
        key = min(int(k), max_count)
        out[key] = out.get(key, 0.0) + float(v)
    total = math.fsum(out.values())
    if total <= 0:
        raise NflKickingError("KICKING_DISTRIBUTION_EMPTY")
    return {k: v / total for k, v in sorted(out.items())}


def _binomial_pmf(n: int, p: float) -> dict[int, float]:
    if n <= 0:
        return {0: 1.0}
    return {k: math.comb(n, k) * p ** k * (1.0 - p) ** (n - k)
            for k in range(n + 1)}


def _thin(count_pmf: Mapping[int, float], p: float) -> dict[int, float]:
    """Success count distribution: sum_A P(A) * Binomial(A, p)."""
    out: dict[int, float] = {}
    for a, pa in count_pmf.items():
        if pa <= 0:
            continue
        for k, v in _binomial_pmf(int(a), p).items():
            out[k] = out.get(k, 0.0) + pa * v
    return _fold(out)


def _convolve(a: Mapping[int, float], b: Mapping[int, float],
              scale_a: int = 1) -> dict[int, float]:
    out: dict[int, float] = {}
    for ka, va in a.items():
        for kb, vb in b.items():
            key = scale_a * int(ka) + int(kb)
            out[key] = out.get(key, 0.0) + va * vb
    # Points are not counts: the fold cap must cover the full
    # scaled support (3 * MAX_COUNT + MAX_COUNT) so no real mass
    # is crushed into the cap cell.
    return _fold(out, max_count=scale_a * MAX_COUNT + MAX_COUNT)


def _mean(pmf: Mapping[int, float]) -> float:
    return math.fsum(k * v for k, v in pmf.items())


def prob_over_under(pmf: Mapping[int, float],
                    line: float) -> tuple[float, float, float]:
    """(p_over, p_push, p_under) for an O/U line on the count."""
    over = math.fsum(v for k, v in pmf.items() if k > line)
    push = math.fsum(v for k, v in pmf.items() if k == line)
    under = math.fsum(v for k, v in pmf.items() if k < line)
    return over, push, under


def _valid_distance(distance: Any) -> float:
    """Measured FG distance or a named refusal (never 0 / never 60+)."""
    if distance is None or isinstance(distance, bool):
        raise NflKickingError("KICKING_FG_DISTANCE_INVALID:missing")
    try:
        d = float(distance)
    except (TypeError, ValueError):
        raise NflKickingError(
            f"KICKING_FG_DISTANCE_INVALID:{distance!r}") from None
    if not math.isfinite(d) or d < 0:
        raise NflKickingError(f"KICKING_FG_DISTANCE_INVALID:{d!r}")
    return d


def _pat_count(value: Any, field: str) -> int:
    if value is None or isinstance(value, bool):
        raise NflKickingError(f"KICKING_PAT_SUPPORT_INVALID:{field}")
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise NflKickingError(
            f"KICKING_PAT_SUPPORT_INVALID:{field}") from None
    if not math.isfinite(f) or f < 0 or f != int(f):
        raise NflKickingError(f"KICKING_PAT_SUPPORT_INVALID:{field}={value!r}")
    return int(f)


def _band_index(distance: float) -> int:
    distance = _valid_distance(distance)
    for i, (lo, hi, _rate, _mix) in enumerate(DISTANCE_BANDS):
        if lo <= distance <= hi:
            return i
        if i + 1 < len(DISTANCE_BANDS) and hi < distance < DISTANCE_BANDS[i + 1][0]:
            return i + 1  # fractional yardage between integer bands
    raise NflKickingError(f"KICKING_FG_DISTANCE_INVALID:{distance!r}")


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------

def estimate_kicking(games: Iterable[Mapping[str, Any]], *,
                     kicker_id: str, kickoff: datetime) -> dict[str, Any]:
    """Research probability distributions for one kicker-game.

    ``games`` are per-game kicking records for the kicker:
    {game_id, kickoff (datetime), fg_attempts: [(distance, made)],
    pat_attempts: int, pat_makes: int}. Only rows with kickoff
    strictly before ``kickoff`` are used (strict PIT).
    """
    kid = str(kicker_id or "").strip()
    if not kid:
        raise NflKickingError("KICKING_IDENTITY_REQUIRED")
    if kickoff.tzinfo is None:
        raise NflKickingError("KICKING_KICKOFF_TIMEZONE_REQUIRED")
    rows: list[Mapping[str, Any]] = []
    seen_games: set[str] = set()
    for g in games:
        gkid = str(g.get("kicker_id") or "").strip()
        if gkid != kid:
            raise NflKickingError(
                f"KICKING_HISTORY_PLAYER_MISMATCH:{kid}:got={gkid or None}")
        gid = str(g.get("game_id") or "").strip()
        if not gid:
            raise NflKickingError("KICKING_HISTORY_GAME_ID_MISSING")
        if gid in seen_games:
            raise NflKickingError(f"KICKING_HISTORY_DUPLICATE_GAME:{gid}")
        seen_games.add(gid)
        pa = _pat_count(g.get("pat_attempts"), "pat_attempts")
        pm = _pat_count(g.get("pat_makes"), "pat_makes")
        if pm > pa:
            raise NflKickingError(
                f"KICKING_PAT_SUPPORT_INVALID:{gid}:makes={pm}>attempts={pa}")
        gk = g.get("kickoff")
        if gk is None:
            raise NflKickingError("KICKING_HISTORY_KICKOFF_MISSING")
        if gk < kickoff:
            rows.append(g)
    rows.sort(key=lambda g: g["kickoff"])
    rows = rows[-TRAILING_GAMES_K:]
    if len(rows) < MIN_GAMES:
        raise NflKickingError(
            f"KICKING_HISTORY_INSUFFICIENT:{kid}:n={len(rows)}")

    fg_counts = [len(g.get("fg_attempts") or ()) for g in rows]
    if sum(fg_counts) <= 0:
        raise NflKickingError(f"KICKING_NO_FG_ATTEMPTS:{kid}")
    pat_counts = [int(g.get("pat_attempts") or 0) for g in rows]

    # Distance mix + band make rates (empirical-Bayes shrinkage).
    band_att = [0] * len(DISTANCE_BANDS)
    band_made = [0] * len(DISTANCE_BANDS)
    for g in rows:
        for dist, made in (g.get("fg_attempts") or ()):
            b = _band_index(float(dist))
            band_att[b] += 1
            band_made[b] += 1 if made else 0
    total_att = sum(band_att)
    mix: list[float] = []
    rates: list[float] = []
    for i, (_lo, _hi, lg_rate, lg_mix) in enumerate(DISTANCE_BANDS):
        mix.append((band_att[i] + MIX_SHRINK_ATT * lg_mix)
                   / (total_att + MIX_SHRINK_ATT))
        rates.append((band_made[i] + BAND_SHRINK_ATT * lg_rate)
                     / (band_att[i] + BAND_SHRINK_ATT))
    mix_total = math.fsum(mix)
    mix = [m / mix_total for m in mix]
    p_bar = math.fsum(m * r for m, r in zip(mix, rates))

    pat_att_total = sum(pat_counts)
    pat_made_total = sum(int(g.get("pat_makes") or 0) for g in rows)
    p_pat = (pat_made_total + PAT_SHRINK_ATT * LEAGUE_PAT_MAKE_RATE) \
        / (pat_att_total + PAT_SHRINK_ATT)

    fg_attempt_pmf = _shrunk_count_pmf(fg_counts, LEAGUE_FG_ATTEMPT_COUNTS)
    pat_attempt_pmf = _shrunk_count_pmf(pat_counts,
                                        LEAGUE_PAT_ATTEMPT_COUNTS)
    fg_made_pmf = _thin(fg_attempt_pmf, p_bar)
    xp_made_pmf = _thin(pat_attempt_pmf, p_pat)
    kicking_points_pmf = _convolve(fg_made_pmf, xp_made_pmf, scale_a=3)

    # Diagnostic: the trailing raw kicking-points distribution
    # (unshrunk), the baseline any challenger must beat.
    raw_kp: dict[int, float] = {}
    for g in rows:
        kp = 3 * sum(1 for _d, m in (g.get("fg_attempts") or ()) if m) \
            + int(g.get("pat_makes") or 0)
        raw_kp[kp] = raw_kp.get(kp, 0.0) + 1.0 / len(rows)

    return {
        "status": "RESEARCH_ONLY",
        "engine": ENGINE_ID,
        "engine_version": ENGINE_VERSION,
        "validation_status": "NOT_VALIDATED",
        "governance": "NOT_ADMITTED_CANONICAL_PATH_GOVERNANCE_NO_ENGINE",
        "kicker_id": kid,
        "as_of_kickoff": kickoff.isoformat(),
        "games_used": len(rows),
        "fg_attempts_used": total_att,
        "band_make_rates": {
            f"{lo}-{hi if hi < 999 else '+'}": round(r, 4)
            for (lo, hi, _lr, _lm), r in zip(DISTANCE_BANDS, rates)},
        "p_attempt_make": p_bar,
        "p_pat_make": p_pat,
        "fg_made": {"mean": _mean(fg_made_pmf), "pmf": fg_made_pmf},
        "xp_made": {"mean": _mean(xp_made_pmf), "pmf": xp_made_pmf},
        "kicking_points": {
            "mean": _mean(kicking_points_pmf),
            "pmf": kicking_points_pmf,
            "trailing_raw_pmf_diagnostic": _fold(
                raw_kp, max_count=4 * MAX_COUNT),
        },
    }


# ---------------------------------------------------------------------------
# nflverse play-by-play history source
# ---------------------------------------------------------------------------

PBP_COLUMNS = (
    "game_id", "kicker_player_id", "kicker_player_name", "posteam",
    "field_goal_attempt", "field_goal_result", "kick_distance",
    "extra_point_attempt", "extra_point_result",
)
GAMES_COLUMNS = ("game_id", "gameday", "gametime")


def build_kicking_games(pbp: Any, games: Any) -> list[dict[str, Any]]:
    """Per-(game, kicker) kicking records from nflverse frames.

    ``pbp`` / ``games`` are pandas DataFrames with at least
    PBP_COLUMNS / GAMES_COLUMNS. Kickoff = gameday + gametime (ET)
    converted to UTC, mirroring the sibling TD source's PIT basis.
    Blocked kicks count as attempts, not makes.
    """
    import pandas as pd  # local: core above is dependency-light

    missing = [c for c in PBP_COLUMNS if c not in pbp.columns]
    if missing:
        raise NflKickingError(f"KICKING_PBP_SCHEMA_MISSING:{missing}")
    missing = [c for c in GAMES_COLUMNS if c not in games.columns]
    if missing:
        raise NflKickingError(f"KICKING_GAMES_SCHEMA_MISSING:{missing}")

    g = games.copy()
    g["kickoff"] = pd.to_datetime(
        g["gameday"].astype(str) + " " + g["gametime"].astype(str),
        errors="coerce", format="mixed")
    g = g.dropna(subset=["kickoff"])
    g["kickoff"] = g["kickoff"].dt.tz_localize(
        "America/New_York").dt.tz_convert("UTC")
    kickoff_by_game = dict(zip(g["game_id"].astype(str), g["kickoff"]))

    kicks = pbp[pbp["kicker_player_id"].notna()].copy()
    for col in ("field_goal_attempt", "extra_point_attempt"):
        kicks[col] = pd.to_numeric(kicks[col], errors="coerce").fillna(0)
    # Only FG/PAT plays define a kicking record: kickoff-only
    # appearances must not fabricate 0-attempt games.
    kicks = kicks[(kicks["field_goal_attempt"] == 1)
                  | (kicks["extra_point_attempt"] == 1)]
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in kicks.itertuples(index=False):
        gid = str(row.game_id)
        ko = kickoff_by_game.get(gid)
        if ko is None:
            continue
        key = (gid, str(row.kicker_player_id))
        rec = out.setdefault(key, {
            "game_id": gid, "kickoff": ko.to_pydatetime(),
            "kicker_id": key[1],
            "kicker_name": str(row.kicker_player_name),
            "team": str(row.posteam),
            "fg_attempts": [], "pat_attempts": 0, "pat_makes": 0,
        })
        if int(row.field_goal_attempt or 0) == 1:
            dist = _valid_distance(row.kick_distance)
            rec["fg_attempts"].append((
                dist,
                str(row.field_goal_result).strip().lower() == "made"))
        if int(row.extra_point_attempt or 0) == 1:
            rec["pat_attempts"] += 1
            if str(row.extra_point_result).strip().lower() == "good":
                rec["pat_makes"] += 1
    return sorted(out.values(), key=lambda r: r["kickoff"])


def _fetch_csv(url: str, *, gzip_encoded: bool = False) -> Any:
    import pandas as pd

    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp:  # noqa: S310 (declared source)
        raw = resp.read()
    if gzip_encoded:
        raw = gzip.decompress(raw)
    return pd.read_csv(io.BytesIO(raw), low_memory=False)


class NflKickingPublicSource:
    """Free nflverse source for kicking history (no API keys)."""

    def __init__(self, fetcher: Callable[[str, bool], Any] | None = None):
        self._fetcher = fetcher or (
            lambda url, gz: _fetch_csv(url, gzip_encoded=gz))

    def games_for(self, seasons: Sequence[int], *,
                  kicker_id: str) -> list[dict[str, Any]]:
        games = self._fetcher(SOURCE_URLS["games"], False)
        records: list[dict[str, Any]] = []
        for season in seasons:
            pbp = self._fetcher(
                SOURCE_URLS["pbp"].format(season=season), True)
            records.extend(build_kicking_games(pbp, games))
        kid = str(kicker_id).strip()
        return [r for r in records if r["kicker_id"] == kid]
