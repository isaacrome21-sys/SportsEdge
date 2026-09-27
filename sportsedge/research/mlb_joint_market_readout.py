"""Unvalidated research readouts from the same aligned MLB game/player paths.

No registry, promotion, pricing or staking integration. Unsupported markets fail
closed; notably a zero stolen-base placeholder is never a probability model.
"""
from math import isfinite

from sportsedge.dfs.mlb_joint_paths import MlbJointPathResult
from sportsedge.game_distribution_readout import read_game_probability
from sportsedge.source_lineage import canonical_json_sha256


PLAYER_FIELDS = {
    "HITS": ("singles", "doubles", "triples", "home_runs"),
    "HOME_RUNS": ("home_runs",), "SINGLES": ("singles",),
    "DOUBLES": ("doubles",), "TRIPLES": ("triples",),
    "RUNS": ("runs",), "RBI": ("rbi",), "BATTER_BB": ("walks",),
    "BATTER_K": ("strikeouts",),
    "EXTRA_BASE_HITS": ("doubles", "triples", "home_runs"),
    "RUNS_RBIS": ("runs", "rbi"),
    "HITS_RUNS_RBIS": ("singles", "doubles", "triples", "home_runs", "runs", "rbi"),
    "PITCHER_K": ("strikeouts",), "PITCHER_HITS_ALLOWED": ("hits_allowed",),
    "PITCHER_BB": ("walks_allowed",), "PITCHER_ER": ("earned_runs",),
    "PITCHER_OUTS": ("outs",),
    "PITCHER_HITS_WALKS_ER": ("hits_allowed", "walks_allowed", "earned_runs"),
    "TOTAL_BASES": ("singles", "doubles", "triples", "home_runs"),
}


def _count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("MLB_JOINT_COUNT_INVALID")
    if not isfinite(value) or value < 0 or int(value) != value:
        raise ValueError("MLB_JOINT_COUNT_INVALID")
    return int(value)


def read_joint_research_probability(
    result: MlbJointPathResult, *, market: str, side: str,
    line: float | None = None, player_id: str | None = None,
) -> dict:
    market, side = market.upper(), side.upper()
    snapshot = result.snapshot
    n = result.path_count
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("MLB_JOINT_PATH_COUNT_INVALID")
    if snapshot.get("path_set_id") != result.path_set_id or snapshot.get("path_count") != n:
        raise ValueError("MLB_JOINT_PATH_IDENTITY_MISMATCH")
    if market in {"MONEYLINE", "RUN_LINE", "TOTALS"}:
        rows = snapshot.get("game_samples")
        if not isinstance(rows, list) or len(rows) != n:
            raise ValueError("MLB_JOINT_GAME_SAMPLES_MISSING")
        counts = {}
        for row in rows:
            away, home = _count(row.get("away_runs")), _count(row.get("home_runs"))
            if away == home:
                raise ValueError("MLB_JOINT_UNRESOLVED_GAME")
            key = f"{away},{home}"
            counts[key] = counts.get(key, 0) + 1
        pmf = {key: count / n for key, count in counts.items()}
        distribution = {"joint_score_pmf": pmf, "result_sha256": canonical_json_sha256({
            "path_set_id": result.path_set_id, "joint_score_pmf": pmf,
        })}
        readout = read_game_probability(distribution, market=market, side=side, line=line)
        win_p, push_p = readout.probability, readout.push_probability
    else:
        if market not in PLAYER_FIELDS:
            raise ValueError(f"MLB_JOINT_MARKET_UNSUPPORTED:{market}")
        if side not in {"OVER", "UNDER"} or isinstance(line, bool) or not isinstance(line, (int, float)) or not isfinite(line) or line < 0:
            raise ValueError("MLB_JOINT_PROP_SIDE_OR_LINE_INVALID")
        matches = [row for row in snapshot.get("players", []) if row.get("player_id") == player_id]
        if len(matches) != 1 or matches[0].get("path_set_id") != result.path_set_id:
            raise ValueError("MLB_JOINT_PLAYER_IDENTITY_MISMATCH")
        samples = matches[0].get("samples")
        if not isinstance(samples, list) or len(samples) != n:
            raise ValueError("MLB_JOINT_PLAYER_SAMPLES_MISSING")
        # Role binding prevents a hitter's strikeouts being priced as pitcher Ks.
        role_marker = "starter_exit_batters_faced" if market.startswith("PITCHER_") else "plate_appearances"
        values = []
        for sample in samples:
            _count(sample.get(role_marker))
            fields = [_count(sample.get(key)) for key in PLAYER_FIELDS[market]]
            values.append(sum(value * weight for value, weight in zip(fields, (1, 2, 3, 4)))
                          if market == "TOTAL_BASES" else sum(fields))
        win_p = sum(value > line if side == "OVER" else value < line for value in values) / n
        push_p = sum(value == line for value in values) / n
    return {
        "market": market, "side": side, "line": line, "player_id": player_id,
        "research_p": win_p, "push_p": push_p,
        "path_set_id": result.path_set_id, "path_count": n,
        "rules_mode": snapshot.get("rules_mode"),
        "model_p_authority": False, "truth_gate_authority": False,
        "promotion_authority": False, "official_authority": False,
        "label": "NOT Model_P · NOT Truth Gate · NOT OFFICIAL",
    }
