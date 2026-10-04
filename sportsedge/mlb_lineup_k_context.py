"""Production inputs for the frozen lineup-K lane validated in #1540.

Only k>=5 pitcher K half lines use this lane. Missing inputs retain opp-K.
"""
from concurrent.futures import ThreadPoolExecutor
from math import isfinite

from .mlb_lineup_k_context_research import LineupIndex
from .mlb_opp_k_context_research import team_games_from_gamelog

W = 200.0
GAMMA = 0.5
VALIDATED_IN = "#1540"


def build_payload(source, *, game_pk, player_id, target_date, opponent_id):
    """Use the research index with strictly-prior native game-log counts."""
    current = source._lineup_boxscore(game_pk)
    order = current["orders"].get(opponent_id)
    if order is None:
        raise ValueError("opponent lineup not posted")
    starts = source._pitcher_start_rows_pk(player_id=player_id, target_date=target_date)
    if not 5 <= len(starts) <= 10:
        raise ValueError("lineup-K needs 5..10 own starts")
    opp = source.opp_k_index(target_date)
    if isinstance(opp, Exception):
        raise ValueError("opponent K index unavailable") from opp
    orders = []
    for _, _, tid, pk in starts:
        if tid is None:
            raise ValueError("prior opponent missing")
        # Unknown historical lineup is D_i=1 under the frozen protocol.
        hist_order = None if pk is None else source._lineup_boxscore(pk)["orders"].get(tid)
        orders.append(hist_order)
    batters = sorted(set(order).union(*(set(o or ()) for o in orders)))
    seasons = range(min(d.year for _, d, _, _ in starts) - 1, target_date.year + 1)
    team_ids = source._mlb_team_ids(target_date.year)
    if len(set(team_ids)) != 30:
        raise ValueError("incomplete MLB team identity")
    teams = {(t, y): team_games_from_gamelog(source._memo_team_season(t, y))
             for y in seasons for t in team_ids}
    # The opp-K source already validated complete prior-season team logs.
    def batter_log(job):
        b, y = job
        payload = source._player_season(b, "hitting", y)
        if not isinstance(payload.get("stats"), list):
            raise ValueError("batter game log missing")
        return b, team_games_from_gamelog(payload)
    logs = {b: [] for b in batters}
    with ThreadPoolExecutor(max_workers=12) as pool:
        for b, rows in pool.map(batter_log, [(b, y) for b in batters for y in seasons]):
            logs[b].extend(rows)
    index = LineupIndex(teams, logs)
    def deviation(o, d, tid):
        if o is None:
            return 1.0
        return index.lineup_rel(o, d.isoformat(), d.year, W) / opp.rel(tid, d.year, d.isoformat())
    target = deviation(order, target_date, opponent_id)
    history = [deviation(o, d, tid) for o, (_, d, tid, _) in zip(orders, starts)]
    if any(not isfinite(x) or x <= 0 for x in [target, *history]):
        raise ValueError("invalid lineup index")
    return {"W": W, "gamma": GAMMA, "target_deviation": target,
            "history_deviation": history, "validated_in": VALIDATED_IN}


def adjusted_values(raw, opponent_adj):
    """Combined adjustment before clipping, identical to the tested research."""
    lane = opponent_adj.get("lineup_k_adjustment")
    target = float(opponent_adj["target_rel"])
    rels = [float(x) for x in opponent_adj["history_rel"]]
    xs = [v * (target / r) ** float(opponent_adj["beta"]) for v, r in zip(raw, rels)]
    if lane is not None:
        if lane.get("W") != W or lane.get("gamma") != GAMMA:
            raise ValueError("unvalidated lineup-K parameters")
        ds = lane.get("history_deviation")
        dt = float(lane["target_deviation"])
        if not isinstance(ds, list) or len(ds) != len(raw):
            raise ValueError("lineup-K history must align with own starts")
        ds = [float(x) for x in ds]
        if any(not isfinite(x) or x <= 0 for x in [dt, *ds]):
            raise ValueError("invalid lineup-K deviations")
        xs = [x * (dt / d) ** GAMMA for x, d in zip(xs, ds)]
    return [min(max(x, 0.0), 20.0) for x in xs]


def lineup_k_notes(payload, names=None):
    rows = list(payload.get("results") or [])
    for game in payload.get("games") or []:
        rows.extend(game.get("results") or [])
    notes = {}
    for row in rows:
        if row.get("market") != "PITCHER_K":
            continue
        ev = row.get("empirical_evidence") or {}
        entity = str(row.get("entity_id"))
        who = (names or {}).get(entity) or entity
        lane = ev.get("lineup_k_adjustment")
        if lane:
            notes[entity] = f"LINEUP-K ADJ {who} Pitcher K: confirmed lineup deviation {lane['target_deviation']:.2f}, validated {VALIDATED_IN}. LEAN max."
        elif ev.get("lineup_k_unadjusted") and entity not in notes:
            notes[entity] = f"LINEUP-K UNADJUSTED {who} Pitcher K: {ev['lineup_k_unadjusted']}; retains existing price."
    return [notes[k] for k in sorted(notes)]
