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
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import atd_engine as eng
import atd_provenance as pv

CLOSE_WINDOW = timedelta(minutes=60)
MIN_WEEKS, MIN_PICKED, MIN_GAMES = 4, 150, 40
DRIFT_FLAG = 0.02
MAX_PICKED_CLV_MISSING = 0.20  # > 20% of picked rows CLV_MISSING -> INSUFFICIENT_CLOSE_DATA
VERDICT_PATH = pv.VERDICT_PATH      # fixed: on pv.RECORDS_BRANCH only
Z95 = 1.959963984540054


def _utcnow():
    return datetime.now(timezone.utc)


class ReviewAlreadyRecorded(Exception):
    pass


class RecordsLocationRefused(Exception):
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
            t = None
        if t is None:
            # never skipped: an untimed capture could be the true close
            return "CLOSE_TIMESTAMP_INVALID"
        if t >= ko:
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


def _git(wt, *a, check=True):
    return subprocess.run(["git", *a], cwd=wt, capture_output=True, text=True,
                          check=check)


def _canonical_url(url: str) -> str:
    u = url.strip().lower()
    u = re.sub(r"^(https?://|ssh://)?(git@)?", "", u)
    u = u.replace("github.com:", "github.com/")
    return re.sub(r"(\.git)?/?$", "", u)


def _check_worktree(wt):
    wt = Path(wt)
    r = _git(wt, "symbolic-ref", "--short", "HEAD", check=False)
    if r.returncode != 0 or r.stdout.strip() != pv.RECORDS_BRANCH:
        raise RecordsLocationRefused(f"{wt} is not a checkout of {pv.RECORDS_BRANCH}")
    top = _git(wt, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(top).resolve() != wt.resolve():
        raise RecordsLocationRefused(f"{wt} is not the worktree root")
    u = _git(wt, "remote", "get-url", "origin", check=False)
    if u.returncode != 0 or _canonical_url(u.stdout) != pv.ORIGIN_CANONICAL:
        raise RecordsLocationRefused(f"origin is not {pv.ORIGIN_CANONICAL}")
    return wt


def _verdict_ever_existed(api) -> bool:
    head = pv._call(api.get_file, pv.RECORDS_BRANCH, VERDICT_PATH)
    commits = pv._call(api.file_commits, pv.RECORDS_BRANCH, VERDICT_PATH)
    if not isinstance(commits, list) or (head is not None and not isinstance(head, str)):
        raise pv.ProvenanceFailed("API_MALFORMED", "verdict lookup")
    return head is not None or len(commits) > 0


def verdict_counts(api) -> bool:
    """A verdict counts only once pushed to the records branch as a proven
    single-commit record at the fixed path."""
    try:
        pv.prove_record(api, VERDICT_PATH)
        return True
    except pv.ProvenanceFailed as e:
        if e.code == "RECORD_NOT_ON_BRANCH":
            return False
        raise


def _score_rows(rows, closes, settlements):
    out = []
    for e in rows:
        if e.get("status") != "PRICED":
            continue
        g = e["game_id"]
        if g in closes["unproven_games"] or (
                g in closes["kickoffs"] and closes["kickoffs"][g] != e["kickoff"]):
            r = score_row(e, [], settlements)
            r.update(clv=None, clv_status="CLV_MISSING", clv_reason="CLOSE_RECORD_UNPROVEN")
        else:
            r = score_row(e, closes["captures"], settlements)
        out.append(r)
    return out


def score_slate_rows(api, slate_id):
    """Score one COUNTS slate entirely from branch records."""
    st = pv.load_slate(api, slate_id)
    if st["status"] != "COUNTS":
        return []
    rows = st["record"]["rows"]
    kos = {r["game_id"]: r["kickoff"] for r in rows if r.get("status") == "PRICED"}
    closes = pv.load_closes(api)
    setl = pv.load_settlements(api, kos, _utcnow())
    return _score_rows(rows, closes, setl["settlements"])


def review(slate_ids, *, records_worktree, api):
    """Single review, reading ONLY records on the records-branch head: each
    slate's rows/hashes from its pushed run record, close captures from
    proven closes/<sha>.json records, settlements from hash-matched
    settlement records. Refuses unless records_worktree is a checkout of the
    records branch whose origin is the SportsEdge repo, and if the verdict
    path has EVER had a commit (API). SCREEN slates are excluded. The verdict
    is staged create-only at the fixed path; it counts only once pushed."""
    wt = _check_worktree(records_worktree)
    if _verdict_ever_existed(api) or (wt / VERDICT_PATH).exists():
        raise ReviewAlreadyRecorded(f"{pv.RECORDS_BRANCH}:{VERDICT_PATH}")
    now = _utcnow()
    loaded, screen = [], []
    for sid in slate_ids:
        st = pv.load_slate(api, sid)
        (loaded if st["status"] == "COUNTS" else screen).append(st if st["status"] == "COUNTS" else sid)
    kos = {r["game_id"]: r["kickoff"] for st in loaded for r in st["record"]["rows"]
           if r.get("status") == "PRICED"}
    closes = pv.load_closes(api)
    setl = pv.load_settlements(api, kos, now)
    inputs = {"run_records": [], "closes": closes["records"],
              "closes_unproven": closes["unproven_records"],
              "settlements": setl["records"], "settlements_refused": setl["refused"]}
    acc, proofs = [], {}
    for st in loaded:
        sid = st["slate_id"]
        inputs["run_records"].append(st["content"])
        proofs[sid] = st["run_proof"]
        acc += _score_rows(st["record"]["rows"], closes, setl["settlements"])
        weeks, picked, games = _gates(acc)
        if len(weeks) >= MIN_WEEKS and len(picked) >= MIN_PICKED and len(games) >= MIN_GAMES:
            v = _verdict(acc, sid)
            v.update(inputs_sha256=inputs_sha256(inputs), inputs=inputs,
                     n_slates=len(inputs["run_records"]), screen_slates=screen,
                     records_branch=pv.RECORDS_BRANCH, verdict_path=VERDICT_PATH,
                     run_proofs=proofs, reviewed_at=now.isoformat())
            path = wt / VERDICT_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            except FileExistsError:
                raise ReviewAlreadyRecorded(str(path))
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps(v, indent=1, sort_keys=True) + "\n")
            return dict(v, record_state="STAGED_NOT_COUNTED")
    weeks, picked, games = _gates(acc)
    return {"status": "NO_REVIEW_GATES_NOT_MET", "n_weeks": len(weeks),
            "n_picked": len(picked), "n_games": len(games),
            "screen_slates": screen,
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
