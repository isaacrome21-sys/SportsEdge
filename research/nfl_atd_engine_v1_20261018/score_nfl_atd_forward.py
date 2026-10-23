"""NFL anytime-TD forward scorer v1.1 (#2399 locked Rules 4-6; DRAFT pending
owner freeze of PREREG_NFL_ATD_ENGINE_V1_1).

Rule 4  CLV = raw implied(close Yes) - raw implied(entry Yes); close = last
        Yes capture strictly before kickoff and no more than 60 min before
        it; else CLV_MISSING (NO_CLOSE_ROW | CLOSE_STALE). No de-vig.
Rule 5  per-game cut drift = mean CLV over every CLV-scored row in the game
        (picked and passed); clv_adj = clv - drift. BEATS_MARKET also needs
        mean picked clv_adj > 0. Games with |drift| > DRIFT_FLAG are flagged.
Rule 6  review gates: >= 4 distinct weeks AND >= 150 graded picked rows AND
        >= 40 distinct games (a minimum, per the clarification memo). One
        review only, at the first slate close where all gates are met; that
        accumulated sample is the sample of record. Game-clustered CIs.
INSUFFICIENT_CLOSE_DATA if > 20% of picked rows are CLV_MISSING (owner).
Multiple-testing correction is a program-level PLAY rule, not applied here.
Nothing here can open PLAY: output is RESEARCH_ONLY.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import timedelta
from pathlib import Path

import atd_engine as eng

CLOSE_WINDOW = timedelta(minutes=60)
MIN_WEEKS, MIN_PICKED, MIN_GAMES = 4, 150, 40
DRIFT_FLAG = 0.02
MAX_PICKED_CLV_MISSING = 0.20  # > 20% of picked rows CLV_MISSING -> INSUFFICIENT_CLOSE_DATA
VERDICT_FILE = "NFL_ATD_V1_1_VERDICT.json"
Z95 = 1.959963984540054


class ReviewAlreadyRecorded(Exception):
    pass


def implied(price) -> float:
    p = eng.parse_american(price)
    if p is None:
        raise ValueError(f"invalid price {price!r}")
    return eng.raw_implied(p)


def find_close(captures, game_id, pid, kickoff):
    """Captures and settlements match on (game_id, player_id). The close is
    the LATEST capture strictly before kickoff; if its price is invalid the
    row is CLOSE_LATEST_INVALID (no fallback to an earlier capture)."""
    ko = eng.parse_timestamp(kickoff)
    before = []
    for c in captures:
        if c.get("player_id") != pid or c.get("game_id") != game_id:
            continue
        try:
            t = eng.parse_timestamp(c.get("captured_at"))
        except ValueError:
            continue
        if t is None or t >= ko:
            continue
        before.append((t, c))
    if not before:
        return "NO_CLOSE_ROW"
    t, c = max(before, key=lambda x: x[0])
    if ko - t > CLOSE_WINDOW:
        return "CLOSE_STALE"
    if eng.parse_american(c.get("yes_price")) is None:
        return "CLOSE_LATEST_INVALID"
    return c


def score_row(row, captures, settlements):
    """settlements: {(game_id, player_id): 0 | 1}."""
    if row.get("status") != "PRICED":
        return None
    pid, gid = row["player_id"], row["game_id"]
    out = {"player_id": pid, "selection": row["selection"],
           "game_id": gid, "week": row["week"],
           "raw_implied": row["raw_implied"]}
    close = find_close(captures, gid, pid, row["kickoff"])
    if isinstance(close, str):
        out.update(clv=None, clv_status="CLV_MISSING", clv_reason=close)
    else:
        out.update(clv=implied(close["yes_price"]) - row["raw_implied"],
                   clv_status="OK", close_price=close["yes_price"])
    s = settlements.get((gid, pid))
    if s in (0, 1) and not isinstance(s, bool):
        out.update(outcome=s, outcome_status="SETTLED")
    else:
        out.update(outcome=None, outcome_status="UNSETTLED")
    return out


def cut_drift_adjust(rows):
    """Rule 5 (owner-confirmed): drift_g = mean CLV over all CLV-scored rows
    of game g, picked and passed; clv_adj = clv - drift_g. NOTE: in a game
    whose scored rows are all picked, the picked clv_adj sums to 0 for that
    game by construction, so such games add nothing to mean clv_adj."""
    games = {}
    for r in rows:
        if r.get("clv_status") == "OK":
            games.setdefault(r["game_id"], []).append(r["clv"])
    info = {g: {"drift": sum(v) / len(v), "n": len(v)} for g, v in games.items()}
    for g in info:
        info[g]["drifted"] = abs(info[g]["drift"]) > DRIFT_FLAG
    for r in rows:
        if r.get("clv_status") == "OK":
            r["clv_adj"] = r["clv"] - info[r["game_id"]]["drift"]
    return info


def clustered_mean_ci(rows, key):
    ys = [(r["game_id"], r[key]) for r in rows]
    n = len(ys)
    if n == 0:
        return None, (None, None)
    m = sum(y for _, y in ys) / n
    sums = {}
    for g, y in ys:
        sums[g] = sums.get(g, 0.0) + (y - m)
    G = len(sums)
    if G < 2:
        return m, (None, None)
    var = G / (G - 1) * sum(e * e for e in sums.values()) / (n * n)
    se = math.sqrt(var)
    return m, (m - Z95 * se, m + Z95 * se)


def _gates(rows):
    graded = [r for r in rows if r.get("outcome_status") == "SETTLED"]
    picked = [r for r in graded if r["selection"] == "YES"]
    return ({r["week"] for r in graded}, picked, {r["game_id"] for r in graded})


def inputs_sha256(slates) -> str:
    return hashlib.sha256(json.dumps(slates, sort_keys=True, default=str)
                          .encode()).hexdigest()


def review(slates, *, records_dir):
    """Single review. The verdict file in records_dir is checked BEFORE any
    review and written create-only (O_EXCL); if it exists the scorer refuses,
    whatever slates are passed."""
    path = Path(records_dir) / VERDICT_FILE
    if path.exists():
        raise ReviewAlreadyRecorded(str(path))
    acc, used = [], []
    for s in slates:
        used.append(s)
        acc.extend(dict(r) for r in s["rows"])
        weeks, picked, games = _gates(acc)
        if len(weeks) >= MIN_WEEKS and len(picked) >= MIN_PICKED and len(games) >= MIN_GAMES:
            v = _verdict(acc, s["slate_id"])
            v["inputs_sha256"] = inputs_sha256(used)
            v["n_slates"] = len(used)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            except FileExistsError:
                raise ReviewAlreadyRecorded(str(path))
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps(v, indent=1, sort_keys=True) + "\n")
            return v
    weeks, picked, games = _gates(acc)
    return {"status": "NO_REVIEW_GATES_NOT_MET", "n_weeks": len(weeks),
            "n_picked": len(picked), "n_games": len(games),
            "status_label": "RESEARCH_ONLY", "promotable": False}


def _verdict(rows, slate_id):
    rows = [r for r in rows if r.get("outcome_status") == "SETTLED"]
    drift = cut_drift_adjust(rows)
    weeks, picked, games = _gates(rows)
    passed = [r for r in rows if r["selection"] == "PASS"]
    pk = [r for r in picked if r["clv_status"] == "OK"]
    ps = [r for r in passed if r["clv_status"] == "OK"]
    m, ci = clustered_mean_ci(pk, "clv")
    m_adj, ci_adj = clustered_mean_ci(pk, "clv_adj")
    m_pass = sum(r["clv"] for r in ps) / len(ps) if ps else None
    missing_frac = (len(picked) - len(pk)) / len(picked)
    beats = (ci[0] is not None and ci[0] > 0 and m_adj is not None and m_adj > 0
             and (m_pass is None or m > m_pass))
    return {"status": "REVIEWED", "review_slate": slate_id,
            "verdict": ("INSUFFICIENT_CLOSE_DATA" if missing_frac > MAX_PICKED_CLV_MISSING
                        else "BEATS_MARKET" if beats else "DOES_NOT_BEAT_MARKET"),
            "picked_clv_missing_frac": missing_frac,
            "n_weeks": len(weeks), "n_picked": len(picked), "n_games": len(games),
            "n_picked_clv_missing": len(picked) - len(pk),
            "clv_picked_mean": m, "clv_picked_ci95": list(ci),
            "clv_adj_picked_mean": m_adj, "clv_adj_picked_ci95": list(ci_adj),
            "clv_passed_mean": m_pass,
            "picked_hit_rate": sum(r["outcome"] for r in picked) / len(picked),
            "picked_mean_implied": sum(r["raw_implied"] for r in picked) / len(picked),
            "games_cut_drift_flagged": sorted(g for g, d in drift.items() if d["drifted"]),
            "status_label": "RESEARCH_ONLY", "promotable": False}
