"""NFL prop engines v1 — research engines for the registered NFL player-prop
families that resolved NO_ENGINE on the canonical coverage authority
(owner directive, Oct 20 2026: any model that has no engine gets one built).

Scope: the families registered in ``config/nfl_family_registry_v2.json``
(PR #2371) that had no engine under the Part 2 / Part 2B / anytime-TD
adjudication.  Built here (10): pass_plus_rush_yards, rush_plus_rec_yards,
targets, two_plus_td, fg_made, kicking_points, xp_made, player_sacks,
tackles_assists, player_interceptions.

NOT built here, with the authority recorded in
``research/nfl_prop_engines_20261020/REPORT.md``:

* passing_yards / rushing_yards / rush_yards (alias) / receiving_yards /
  receptions — the frozen Part 2 evaluator is their engine.
* rush_attempts / attempts / completions / passing_tds — Part 2B (PR #2415).
* anytime_td — the v1 engine on branch feat/nfl-atd-engine-v1-20261018.
* interceptions — ruled OUT of Part 2B scope by the owner; the pricer
  refuses it (MARKET_OUT_OF_SCOPE_2B).  Not built.
* first_td — resolves NO_DATA (NO_VERIFIED_FIRST_SCORING_ATTRIBUTION),
  not NO_ENGINE; the gap is data, not an engine.
* longest_completion / longest_rush / longest_reception — no per-game
  longest-play outcome exists in any file of the sanctioned nflverse
  snapshot (game logs carry sums and counts, never a max), so a game-log
  engine would have to fabricate its outcome.  Not built; the gap and
  the data that would close it are recorded in the report.

Construction: a deliberate mirror of the frozen Part 2 evaluator
(``research/nfl_props_part2_20261018/eval_nfl_props_calibration_v1.py``),
the same way Part 2B extended it — point-in-time nflverse game logs,
role-gated qualification (>= 3 prior games, role-mean threshold),
league pool of qualified players' earlier outcomes (prior-season
fallback), shrinkage ``mu = (sum(prior) + K * pool_mean) / (n + K)``
with K = 3.0, one pooled coefficient of variation per family, gamma
CDF for yardage stats and Poisson / negative-binomial CDF for counts.
No construction here is new; only the stat, role gate, and CV differ
per family, each declared in ``FAMILIES``.

Data: the pinned nflverse snapshot (ps_*.csv.gz weekly player stats,
sp_*.csv.gz 2025 stats-player format), regular season only.  Kicking
and defensive outcome columns exist only in the sp format; a file whose
header lacks a family's columns contributes NO rows to that family
(never zero-filled rows — absence of a column is absence of data).

two_plus_td outcome: rushing_tds + receiving_tds, mirroring the
anytime-TD v1 engine's rush/rec construction; special-teams and
fumble-return TDs are excluded from the outcome exactly as that engine
treats them (their measured share was 0.23% of player-games).

Governance: these engines are research only.  Registering an engine
pointer changes no family's registration state, eligibility, or
validation status; every family here stays REGISTERED_RESEARCH_ONLY /
NOT_VALIDATED, eligible=false, promotable=false, and BLOCKED on the
canonical coverage path until separately admitted.
"""
from __future__ import annotations

import csv
import gzip
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

K = 3.0
GRID_LO, GRID_HI = -60, 700
MIN_PRIOR_GAMES = 3

# Raw columns read when present in a source file's header.  The ps
# format carries the offensive block only; the sp format adds kicking
# and defensive blocks.
RAW_COLUMNS = (
    "attempts", "passing_yards", "passing_tds", "interceptions",
    "carries", "rushing_yards", "rushing_tds",
    "targets", "receptions", "receiving_yards", "receiving_tds",
    "special_teams_tds",
    "fg_made", "fg_att", "pat_made", "pat_att",
    "def_sacks", "def_interceptions", "def_tackles_solo",
    "def_tackle_assists",
)


def _f(v):
    # A column existing in the CSV header is not evidence that every row
    # contains an observed value. Treat blanks, malformed cells, and nonfinite
    # values as missing rather than manufacturing zero-stat games that bias
    # research usage/pool means downward. An explicit numeric 0 stays zero.
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        value = float(v)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _derive(row: dict) -> dict:
    """Derived per-game stats; None propagates (a derived stat exists
    only when every input was present in the source file)."""
    def both(a, b):
        return None if row.get(a) is None or row.get(b) is None \
            else row[a] + row[b]
    row["pass_plus_rush_yards"] = both("passing_yards", "rushing_yards")
    row["rush_plus_rec_yards"] = both("rushing_yards", "receiving_yards")
    row["carries_plus_targets"] = both("carries", "targets")
    row["touchdowns_scored"] = both("rushing_tds", "receiving_tds")
    row["kick_attempts"] = both("fg_att", "pat_att")
    row["def_tackles_total"] = both("def_tackles_solo", "def_tackle_assists")
    fg, pat = row.get("fg_made"), row.get("pat_made")
    row["kicking_points"] = None if fg is None or pat is None \
        else 3.0 * fg + pat
    return row


# Per-family construction.  cv is the screened pooled constant (see
# research/nfl_prop_engines_20261020/screen_results_v1.json); cv_source
# names the vintage it was screened on.
FAMILIES = {
    "pass_plus_rush_yards": {
        "market": "PASS_RUSH_YDS", "stat": "pass_plus_rush_yards",
        "role": "attempts", "thr": 20.0, "qb": True, "count": False,
        "cv": 0.3394648769258099, "cv_source": "SCREEN_TRAIN_2018_2019",
        "offer_forms": ["TWO_SIDED_OU"],
    },
    "rush_plus_rec_yards": {
        "market": "RUSH_REC_YDS", "stat": "rush_plus_rec_yards",
        "role": "carries_plus_targets", "thr": 8.0, "qb": False,
        "count": False,
        "cv": 0.61546264843949, "cv_source": "SCREEN_TRAIN_2018_2019",
        "offer_forms": ["TWO_SIDED_OU"],
    },
    "targets": {
        "market": "TARGETS", "stat": "targets",
        "role": "targets", "thr": 4.0, "qb": False, "count": True,
        "cv": 0.5154214950660674, "cv_source": "SCREEN_TRAIN_2018_2019",
        "offer_forms": ["TWO_SIDED_OU"],
    },
    "two_plus_td": {
        "market": "TWO_PLUS_TD", "stat": "touchdowns_scored",
        "role": "carries_plus_targets", "thr": 4.0, "qb": False,
        "count": True,
        "cv": 2.0900151188652436, "cv_source": "SCREEN_TRAIN_2018_2019",
        "offer_forms": ["YES_ONLY"], "yes_line": 1.5,
    },
    "fg_made": {
        "market": "FG_MADE", "stat": "fg_made",
        "role": "fg_att", "thr": 1.0, "qb": False, "count": True,
        "cv": 0.7623909456579233, "cv_source": "SCREEN_2025_PARTIAL_VINTAGE",
        "offer_forms": ["TWO_SIDED_OU", "MILESTONE_LADDER"],
    },
    "xp_made": {
        "market": "XP_MADE", "stat": "pat_made",
        "role": "pat_att", "thr": 1.0, "qb": False, "count": True,
        "cv": 0.6313842815461064, "cv_source": "SCREEN_2025_PARTIAL_VINTAGE",
        "offer_forms": ["TWO_SIDED_OU", "MILESTONE_LADDER"],
    },
    "kicking_points": {
        "market": "KICKING_POINTS", "stat": "kicking_points",
        "role": "kick_attempts", "thr": 2.0, "qb": False, "count": True,
        "cv": 0.5527661614477732, "cv_source": "SCREEN_2025_PARTIAL_VINTAGE",
        "offer_forms": ["TWO_SIDED_OU", "MILESTONE_LADDER"],
    },
    "player_sacks": {
        "market": "PLAYER_SACKS", "stat": "def_sacks",
        "role": "def_tackles_total", "thr": 2.0, "qb": False,
        "count": True,
        "cv": 3.342510697542686, "cv_source": "SCREEN_2025_PARTIAL_VINTAGE",
        "offer_forms": ["TWO_SIDED_OU"],
    },
    "tackles_assists": {
        "market": "TACKLES_ASSISTS", "stat": "def_tackles_total",
        "role": "def_tackles_total", "thr": 3.0, "qb": False,
        "count": True,
        "cv": 0.5582266415821654, "cv_source": "SCREEN_2025_PARTIAL_VINTAGE",
        "offer_forms": ["TWO_SIDED_OU"],
    },
    "player_interceptions": {
        "market": "PLAYER_INTERCEPTIONS", "stat": "def_interceptions",
        "role": "def_tackles_total", "thr": 3.0, "qb": False,
        "count": True,
        "cv": 5.087225461942819, "cv_source": "SCREEN_2025_PARTIAL_VINTAGE",
        "offer_forms": ["TWO_SIDED_OU"],
    },
}

ENGINE_ID = "NFL_PROP_ENGINES_V1"


def load_player_data(data_dir) -> dict:
    """{season: {pid: [(week, position, row)]}} regular season only,
    mirroring the Part 2 evaluator's load shape with the extended
    column set.  Columns absent from a file's header are None in its
    rows (absence of data), never 0."""
    data_dir = Path(data_dir)
    out: dict = defaultdict(lambda: defaultdict(list))
    files = sorted(data_dir.glob("ps_*.csv.gz")) + \
        sorted(data_dir.glob("sp_*.csv.gz"))
    for p in files:
        with gzip.open(p, "rt") as fh:
            reader = csv.DictReader(fh)
            present = set(reader.fieldnames or ())
            for r in reader:
                if r.get("season_type") != "REG":
                    continue
                s, w = int(r["season"]), int(r["week"])
                row = {k: (_f(r.get(k)) if k in present else None)
                       for k in RAW_COLUMNS}
                out[s][r["player_id"]].append(
                    (w, r.get("position") or "", _derive(row)))
    for s in out:
        for pid in out[s]:
            out[s][pid].sort(key=lambda t: t[0])
    return out


def family_view(data: dict, cfg: dict) -> dict:
    """Per-season player games restricted to rows carrying this
    family's stat and role (files lacking the columns contribute no
    rows).  Point-in-time order is preserved."""
    stat, role = cfg["stat"], cfg["role"]
    view: dict = {}
    for s, players in data.items():
        kept_players = {}
        for pid, games in players.items():
            kept = [g for g in games
                    if g[2].get(stat) is not None
                    and g[2].get(role) is not None]
            if kept:
                kept_players[pid] = kept
        view[s] = kept_players
    return view


def qualified_rows(season_data: dict, cfg: dict):
    """Yield (week, pid, prior_stat_values, outcome) for role-qualified
    player-weeks — the evaluator's qualification, unchanged."""
    for pid, games in season_data.items():
        for i, (w, pos, row) in enumerate(games):
            prior = games[:i]
            if len(prior) < MIN_PRIOR_GAMES:
                continue
            if cfg["qb"] and pos != "QB":
                continue
            if np.mean([g[2][cfg["role"]] for g in prior]) < cfg["thr"]:
                continue
            yield w, pid, [g[2][cfg["stat"]] for g in prior], row[cfg["stat"]]


def build(data: dict, cfg: dict) -> dict:
    """Per season: qualified rows sorted by (week, pid) — on the
    family's column-filtered view."""
    view = family_view(data, cfg)
    seasons = {}
    for s in sorted(view):
        seasons[s] = sorted(qualified_rows(view[s], cfg),
                            key=lambda t: (t[0], t[1]))
    return seasons


def league_pool(seasons: dict, s: int, w: int):
    """Qualified outcomes from earlier weeks of the season, falling
    back to the prior season's qualified outcomes (evaluator rule)."""
    earlier = [y for (wk, _, _, y) in seasons.get(s, []) if wk < w]
    if earlier:
        return earlier
    return [y for (_, _, _, y) in seasons.get(s - 1, [])]


def mu_for(prior, pool):
    g = float(np.mean(pool))
    return (sum(prior) + K * g) / (len(prior) + K)


def candidate_cdf(mu, cv, count, grid):
    mu = max(mu, 1e-6)
    sd = cv * mu
    if count:
        var = sd * sd
        if var <= mu:
            return stats.poisson.cdf(grid, mu)
        r = mu * mu / (var - mu)
        return stats.nbinom.cdf(grid, r, r / (r + mu))
    shape = 1.0 / (cv * cv)
    return stats.gamma.cdf(grid, shape, scale=mu / shape)


def emp_cdf(values, grid):
    v = np.sort(np.asarray(values, float))
    return np.searchsorted(v, grid, side="right") / len(v)


def p_over_for(mu: float, cv: float, count: bool, line: float, grid) \
        -> float:
    """Model P(stat > line): counts take the CDF at floor(line), yards
    interpolate the CDF at the line (the Part 2 runner's rule)."""
    cdf = candidate_cdf(mu, cv, count, grid)
    if count:
        return 1.0 - float(cdf[int(math.floor(line)) - GRID_LO])
    return 1.0 - float(np.interp(line, grid, cdf))


def settlement_probabilities(mu: float, cv: float, count: bool,
                             line: float, grid) -> tuple[float, float, float]:
    """Return raw ``(over, push, under)`` settlement mass.

    Count distributions have real push mass at integer lines.  That mass
    must not be assigned to UNDER via ``1 - p_over``.  Half-lines and the
    continuous yardage construction have no point mass at the line.
    """
    cdf = candidate_cdf(mu, cv, count, grid)
    if not count:
        under = float(np.interp(line, grid, cdf))
        return 1.0 - under, 0.0, under

    threshold = int(math.floor(line))
    index = threshold - GRID_LO
    if index < 0 or index >= len(cdf):
        raise ValueError("NFL_PROP_ENGINE_LINE_OUTSIDE_MODEL_GRID")
    at_threshold = float(cdf[index])
    over = 1.0 - at_threshold
    if not float(line).is_integer():
        return over, 0.0, at_threshold
    below = 0.0 if index == 0 else float(cdf[index - 1])
    push = at_threshold - below
    return over, push, below


def fair_american(p: float):
    if p <= 0.0 or p >= 1.0:
        return None
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def _qualification(cfg: dict, priors: list):
    """(ok, reason) for a player's filtered prior games — the Part 2
    runner's qualification contract."""
    if len(priors) < MIN_PRIOR_GAMES:
        return False, f"ONLY_{len(priors)}_PRIOR_GAMES"
    if cfg["qb"] and priors[-1][1] != "QB":
        return False, "NOT_QB"
    role_mean = float(np.mean([g[2][cfg["role"]] for g in priors]))
    if role_mean < cfg["thr"]:
        return False, f"ROLE_MEAN_{role_mean:.2f}_BELOW_{cfg['thr']}"
    return True, "QUALIFIED"


def _price_with_built(family: str, cfg: dict, view: dict, seasons: dict,
                      player_id: str, line: float, season: int,
                      week: int, offer_form: str, grid) -> dict:
    priors = [g for g in view.get(season, {}).get(player_id, [])
              if g[0] < week]
    base = {"family": family, "market": cfg["market"],
            "player_id": player_id, "season": season, "week": week,
            "line": float(line), "engine": f"{ENGINE_ID}:{family}",
            "games_logged": len(priors)}
    ok, why = _qualification(cfg, priors)
    if not ok:
        return {**base, "status": "NOT_QUALIFIED", "reason": why}
    pool = league_pool(seasons, season, week)
    if not pool:
        return {**base, "status": "NOT_PRICED", "reason": "EMPTY_LEAGUE_POOL"}
    if cfg["cv"] is None:
        return {**base, "status": "NOT_PRICED", "reason": "CV_NOT_SCREENED"}
    prior_values = [float(g[2][cfg["stat"]]) for g in priors]
    mu = float(mu_for(prior_values, pool))
    p_over, p_push, p_under = settlement_probabilities(
        mu, float(cfg["cv"]), cfg["count"], float(line), grid)
    out = {**base, "status": "PRICED", "reason": "QUALIFIED",
           "mu": mu, "cv": float(cfg["cv"]), "cv_source": cfg["cv_source"],
           "shrink_weight": float(K / (len(priors) + K)),
           "pool_mean": float(np.mean(pool)),
           "prior_values": prior_values}
    if offer_form == "YES_ONLY":
        out.update(p_yes=p_over, fair_yes_american=fair_american(p_over))
    else:
        resolved = p_over + p_under
        if resolved <= 0.0:
            return {**base, "status": "NOT_PRICED",
                    "reason": "NO_RESOLVED_OUTCOME_MASS"}
        fair_over = p_over / resolved
        fair_under = p_under / resolved
        out.update(
            p_over=p_over,
            p_push=p_push,
            p_under=p_under,
            fair_over_american=fair_american(fair_over),
            fair_under_american=fair_american(fair_under),
            fair_probability_basis="CONDITIONAL_ON_NON_PUSH",
        )
    return out


def _family_cfg(family: str, offer_form: str):
    cfg = FAMILIES.get(str(family or ""))
    if cfg is None:
        raise ValueError(f"NFL_PROP_ENGINE_FAMILY_UNKNOWN:{family}")
    if offer_form not in cfg["offer_forms"]:
        raise ValueError(
            f"NFL_PROP_ENGINE_OFFER_FORM_UNSUPPORTED:{family}:{offer_form}")
    return cfg


def price_nfl_prop(family: str, player_id: str, line: float,
                   data_by_season: dict, season: int, week: int,
                   offer_form: str = "TWO_SIDED_OU") -> dict:
    """Price one registered NFL prop row with the family's v1 engine.

    Fail-closed, mirroring the Part 2 forward runner's row contract:
    unqualified players and empty pools return a NOT_QUALIFIED /
    NOT_PRICED row with a named reason, never a probability.  For the
    YES_ONLY family (two_plus_td) the line is fixed at the family's
    yes_line (P(stat >= 2) is P(stat > 1.5)) and the result carries
    p_yes instead of p_over/p_under.
    """
    cfg = _family_cfg(family, offer_form)
    if offer_form == "YES_ONLY":
        line = float(cfg["yes_line"])
    grid = np.arange(GRID_LO, GRID_HI + 1, dtype=float)
    view = family_view(data_by_season, cfg)
    seasons = build(data_by_season, cfg)
    return _price_with_built(family, cfg, view, seasons, player_id,
                             float(line), season, week, offer_form, grid)


def price_rows(family: str, rows, data_by_season: dict, season: int,
               week: int) -> list:
    """Batch entry for the phone runner's composition step: rows are
    dicts with player_id, line and optional offer_form.  The family's
    qualified seasons are built once for the whole batch."""
    if str(family or "") not in FAMILIES:
        raise ValueError(f"NFL_PROP_ENGINE_FAMILY_UNKNOWN:{family}")
    grid = np.arange(GRID_LO, GRID_HI + 1, dtype=float)
    view = family_view(data_by_season, FAMILIES[family])
    seasons = build(data_by_season, FAMILIES[family])
    out = []
    for r in rows:
        offer_form = r.get("offer_form", "TWO_SIDED_OU")
        cfg = _family_cfg(family, offer_form)
        line = float(cfg["yes_line"]) if offer_form == "YES_ONLY" \
            else float(r["line"])
        out.append(_price_with_built(family, cfg, view, seasons,
                                     r["player_id"], line, season, week,
                                     offer_form, grid))
    return out
