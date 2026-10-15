"""Unvalidated Total Hits construction from aligned endogenous game paths.

This is a research readout, not a replacement for the production refusal gates.
All hitter counts at index i belong to the SAME simulated game. No independent
marginal convolution, new fit, odds input, or validation claim is introduced.
The caller supplies the original game and seed to bind lineup identity; this
checks internal consistency, not source authenticity or snapshot tamper proof.
The simulator currently models fixed nine-player lineups, not substitutions.
"""
from math import isfinite

from sportsedge.dfs.mlb_joint_paths import (
    MLB_JOINT_PATH_VERSION, MlbGamePathInput, MlbJointPathResult,
)
from sportsedge.source_lineage import canonical_json_sha256

HIT_FIELDS = ("singles", "doubles", "triples", "home_runs")


def _count(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or value < 0 or int(value) != value):
        raise ValueError("TOTAL_HITS_COUNT_INVALID")
    return int(value)


def read_joint_total_hits(result: MlbJointPathResult, *, game: MlbGamePathInput,
                          seed: int, market: str, side: str, line: float,
                          team: str | None = None) -> dict:
    if market not in {"GAME_TOTAL_HITS", "TEAM_TOTAL_HITS"}:
        raise ValueError("TOTAL_HITS_MARKET_UNSUPPORTED")
    if (side not in {"OVER", "UNDER"} or isinstance(line, bool)
            or not isinstance(line, (int, float)) or not isfinite(line) or line < 0):
        raise ValueError("TOTAL_HITS_SIDE_OR_LINE_INVALID")
    if ((market == "GAME_TOTAL_HITS" and team is not None)
            or (market == "TEAM_TOTAL_HITS" and team not in {game.away.team, game.home.team})):
        raise ValueError("TOTAL_HITS_TEAM_INVALID")
    n = result.path_count
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("TOTAL_HITS_PATH_COUNT_INVALID")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("TOTAL_HITS_SEED_INVALID")
    expected_id = canonical_json_sha256({
        "version": MLB_JOINT_PATH_VERSION, "game": game.identity(),
        "path_count": n, "seed": seed,
    })
    snapshot = result.snapshot
    if (result.path_set_id != expected_id or snapshot.get("path_set_id") != expected_id
            or snapshot.get("path_count") != n or snapshot.get("game_id") != game.game_id
            or snapshot.get("rules_mode") != game.rules_mode
            or snapshot.get("version") != MLB_JOINT_PATH_VERSION):
        raise ValueError("TOTAL_HITS_PATH_IDENTITY_MISMATCH")
    expected = {h.player_id: t.team for t in (game.away, game.home) for h in t.lineup}
    pitchers = {game.away.starter_player_id, game.home.starter_player_id}
    rows = snapshot.get("players")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("TOTAL_HITS_PLAYER_SET_INVALID")
    ids = [r.get("player_id") for r in rows]
    if (any(not isinstance(pid, str) for pid in ids) or len(set(ids)) != len(ids)
            or set(ids) != set(expected) | pitchers):
        raise ValueError("TOTAL_HITS_PLAYER_SET_INVALID")
    totals = {game.away.team: [0] * n, game.home.team: [0] * n}
    for row in rows:
        pid = row["player_id"]
        if row.get("path_set_id") != expected_id:
            raise ValueError("TOTAL_HITS_PLAYER_PATH_MISMATCH")
        if pid not in expected:
            continue  # Never count starter hits-allowed as additional team hits.
        if row.get("team") != expected[pid]:
            raise ValueError("TOTAL_HITS_PLAYER_TEAM_MISMATCH")
        samples = row.get("samples")
        if not isinstance(samples, list) or len(samples) != n:
            raise ValueError("TOTAL_HITS_SAMPLES_MISSING")
        for i, sample in enumerate(samples):
            if not isinstance(sample, dict):
                raise ValueError("TOTAL_HITS_SAMPLE_INVALID")
            hits = sum(_count(sample.get(key)) for key in HIT_FIELDS)
            if hits > _count(sample.get("plate_appearances")):
                raise ValueError("TOTAL_HITS_EXCEEDS_PA")
            totals[expected[pid]][i] += hits
    values = (totals[team] if team is not None else
              [a + h for a, h in zip(totals[game.away.team], totals[game.home.team])])
    counts = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    readout = {
        "market": market, "side": side, "line": line, "team": team,
        "research_p": sum(v > line if side == "OVER" else v < line for v in values) / n,
        "push_p": sum(v == line for v in values) / n,
        "count_pmf": {k: v / n for k, v in sorted(counts.items())},
        "path_set_id": expected_id, "path_count": n,
        "validation_status": "UNVALIDATED_RESEARCH",
        "source_authenticity_verified": False, "production_ready": False,
        "promotion_authority": False, "official_authority": False,
        "model_p_authority": False,
        "limitations": ["FIXED_LINEUPS_NO_SUBSTITUTIONS", "OOS_AND_FORWARD_VALIDATION_REQUIRED"],
    }
    readout["readout_sha256"] = canonical_json_sha256(readout)
    return readout
