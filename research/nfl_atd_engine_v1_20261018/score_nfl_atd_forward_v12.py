"""NFL anytime-TD forward scorer v1.2 (separate version for a LATER freeze;
v1.1 score_nfl_atd_forward.py is frozen and untouched) -- ported from v1.1 (#2399 locked Rules 4-6; DRAFT pending
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
import atd_provenance_v12 as pv   # t236: v1.2's own records area

CLOSE_WINDOW = timedelta(minutes=60)
MIN_WEEKS, MIN_PICKED, MIN_GAMES = 4, 150, 40
DRIFT_FLAG = 0.02
MAX_PICKED_CLV_MISSING = 0.20  # > 20% of picked rows CLV_MISSING -> INSUFFICIENT_CLOSE_DATA
VERDICT_PATH = pv.VERDICT_PATH      # fixed: on pv.RECORDS_BRANCH only
# Written only under the env-only test switch; never the binding path.
NONBINDING_VERDICT_PATH = f"{pv.ROOT}/TEST_NONBINDING_VERDICT.json"
Z95 = 1.959963984540054


def _utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)   # t236: whole seconds


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


def verify_verdict(api) -> dict:
    """A pushed verdict counts only if (1) FREEZE.json exists, the verdict's
    pricer/scorer shas equal FREEZE's and so do the locally running ones, and
    (2) a dry review() with now = the verdict's reviewed_at reproduces it
    exactly in canonical JSON. Otherwise VERDICT_UNVERIFIED (fail-closed:
    the fixed path is then used, so a forged verdict blocks the review)."""
    _review_env_guard()
    try:
        p = pv.prove_record(api, VERDICT_PATH)
    except pv.ProvenanceFailed as e:
        if e.code == "RECORD_NOT_ON_BRANCH":
            return {"counts": False, "code": "NO_VERDICT"}
        return {"counts": False, "code": "VERDICT_UNVERIFIED", "detail": e.code}

    def no(detail):
        return {"counts": False, "code": "VERDICT_UNVERIFIED", "detail": detail}
    try:
        v = json.loads(p["content"])
        fz = pv.load_freeze(api)
    except pv.ProvenanceFailed as e:
        return no(e.code)
    except ValueError:
        return no("verdict unreadable")
    if not isinstance(v, dict) or v.get("binding") is not True:
        return no("not binding")
    loc = local_shas()
    for k in pv.FREEZE_KEYS:
        if v.get(k) != fz[k] or loc[k] != fz[k]:
            return no(f"{k} != FREEZE")
    import platform
    # v1.2: the interpreter check is explicit and fail-closed (a missing or
    # different python_version never verifies); the platform string is
    # recorded but excluded from the comparison (_strip_volatile).
    if not isinstance(v.get("python_version"), str) or v["python_version"] != platform.python_version():
        return no("interpreter mismatch")
    try:
        from datetime import datetime
        again = review(v["slate_ids"], records_worktree=None, api=api, _dry=True,
                       _now=datetime.fromisoformat(v["reviewed_at"]))
    except Exception as e:            # any failure to re-derive -> unverified
        return no(f"re-derivation failed: {type(e).__name__}")
    if pv.canonical_json(_strip_volatile(again)) != pv.canonical_json(_strip_volatile(v)):
        return no("re-derived verdict differs")
    return {"counts": True, "code": None}


def _strip_proof_source(o):
    """proof_source (live vs stored) may change as activity ages; the proof
    itself must still succeed via either source, so only the label is dropped."""
    if isinstance(o, dict):
        return {k: _strip_proof_source(x) for k, x in o.items() if k != "proof_source"}
    if isinstance(o, list):
        return [_strip_proof_source(x) for x in o]
    return o


def _strip_volatile(v):
    """v1.2: proof_source labels anywhere, and the top-level platform string
    only. python_version is NOT stripped (checked above and compared)."""
    o = _strip_proof_source(v)
    return {k: x for k, x in o.items() if k != "platform"} if isinstance(o, dict) else o


def verdict_counts(api) -> bool:
    return verify_verdict(api)["counts"]


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


def _rows(st):
    """Priced rows with kickoff REPLACED by the schedule-recomputed kickoff
    (load_slate), so close windows never use the run record's claim."""
    return [dict(r, kickoff=st["kickoffs"][r["game_id"]]) if r.get("status") == "PRICED" else r
            for r in st["record"]["rows"]]


def _games(loaded):
    return {r["game_id"]: {"kickoff": st["kickoffs"][r["game_id"]], "season": st["season"],
                           "week": r["week"]}
            for st in loaded for r in st["record"]["rows"] if r.get("status") == "PRICED"}


def score_slate_rows(api, slate_id):
    """Score one COUNTS slate entirely from branch records."""
    _review_env_guard()
    pv.require_token(api)
    st = pv.load_slate(api, slate_id)
    if st["status"] != "COUNTS":
        return []
    rows = _rows(st)
    games = _games([st])
    closes = pv.load_closes(api, games)
    setl = pv.load_settlements(api, games, _utcnow())
    return _score_rows(rows, closes, setl["settlements"])


class ReviewEnvUntrusted(Exception):
    code = "REVIEW_ENV_UNTRUSTED"


def _review_env_problems(replayers_fn, original_fn, modules) -> list:
    import price_nfl_atd_board_v11 as pr
    out = []
    if replayers_fn is not original_fn:
        out.append("replayers_patched")
    if "fake_github_api" in modules:
        out.append("fake_module_loaded")
    try:
        keys = set(replayers_fn())
    except Exception:
        keys = None
    if keys != {pr.pricer_sha256()}:
        out.append("replayer_keys")
    return out


def _review_env_guard():
    """Refuse unless the replay registry is the untouched production one."""
    import sys
    probs = _review_env_problems(pv.replayers, pv._ORIGINAL_REPLAYERS, sys.modules)
    if probs:
        raise ReviewEnvUntrusted(f"REVIEW_ENV_UNTRUSTED: {', '.join(probs)}")


def local_shas() -> dict:
    """shas of the code running now, compared with FREEZE.json."""
    import price_nfl_atd_board_v11 as pr
    here = Path(__file__).resolve().parent

    def h(n):
        return hashlib.sha256((here / n).read_bytes()).hexdigest()
    return {"pricer_sha256": pr.pricer_sha256(), "scorer_sha256": h("score_nfl_atd_forward_v12.py"),
            "provenance_sha256": h("atd_provenance_v12.py"),
            "prereg_sha256": h("PREREG_NFL_ATD_ENGINE_V1_1_DRAFT.md")}


class ReviewFreezeMismatch(Exception):
    code = "REVIEW_FREEZE_MISMATCH"


def _require_freeze_match(api):
    """v1.2 pre-write check: refuse unless every FREEZE.json pin equals the
    hash of the code running now. A missing/unproven FREEZE raises
    pv.ProvenanceFailed (fail-closed)."""
    fz = pv.load_freeze(api)
    loc = local_shas()
    bad = [k for k in pv.FREEZE_KEYS if loc.get(k) != fz.get(k)]
    if bad:
        raise ReviewFreezeMismatch(f"REVIEW_FREEZE_MISMATCH: {bad}")


class ReviewInterpreterMismatch(Exception):
    code = "REVIEW_INTERPRETER_MISMATCH"


def _env_record() -> dict:
    import hashlib
    import platform
    import price_nfl_atd_board_v11 as pr
    return {**local_shas(),
            "python_version": platform.python_version(),
            "platform": platform.platform()}


def review(slate_ids, *, records_worktree, api, _binding=True, _dry=False, _now=None,
           _check_interpreter=False):
    """Single review, reading ONLY records on the records-branch head: each
    slate's rows/hashes from its pushed run record, close captures from
    proven closes/<sha>.json records, settlements from hash-matched
    settlement records. Refuses unless records_worktree is a checkout of the
    records branch whose origin is the SportsEdge repo, and if the verdict
    path has EVER had a commit (API). SCREEN slates are excluded. The verdict
    is staged create-only at the fixed path; it counts only once pushed."""
    _review_env_guard()                 # first: before token, worktree, API
    pv.require_token(api)
    vpath = VERDICT_PATH if _binding else NONBINDING_VERDICT_PATH
    if not _dry:   # dry mode (verdict re-derivation) writes and checks nothing local
        wt = _check_worktree(records_worktree)
        if _verdict_ever_existed(api) or (wt / VERDICT_PATH).exists() or (wt / vpath).exists():
            raise ReviewAlreadyRecorded(f"{pv.RECORDS_BRANCH}:{VERDICT_PATH}")
        _require_freeze_match(api)      # v1.2: refuse early...
    now = (_now if _now is not None else _utcnow()).replace(microsecond=0)   # v1.2
    loaded, screen = [], []
    for sid in slate_ids:
        st = pv.load_slate(api, sid, now=now)
        (loaded if st["status"] == "COUNTS" else screen).append(st if st["status"] == "COUNTS" else sid)
    if _check_interpreter:              # after load_slate, COUNTS slates only
        import platform
        bad = [st["slate_id"] for st in loaded
               if st["record"].get("python_version") != platform.python_version()]
        if bad:
            raise ReviewInterpreterMismatch(f"REVIEW_INTERPRETER_MISMATCH: {bad}")
    refusals_by_slate = {st["slate_id"]: st.get("refusals", {}) for st in loaded}
    games = _games(loaded)
    closes = pv.load_closes(api, games, now=now)
    setl = pv.load_settlements(api, games, now)
    inputs = {"run_records": [], "closes": closes["records"],
              "closes_unproven": closes["unproven_records"],
              "settlements": setl["records"], "settlements_refused": setl["refused"]}
    acc, proofs = [], {}
    for st in loaded:
        sid = st["slate_id"]
        inputs["run_records"].append(st["content"])
        proofs[sid] = st["run_proof"]
        acc += _score_rows(_rows(st), closes, setl["settlements"])
        weeks, picked, games = _gates(acc)
        if len(weeks) >= MIN_WEEKS and len(picked) >= MIN_PICKED and len(games) >= MIN_GAMES:
            v = _verdict(acc, sid)
            v.update(inputs_sha256=inputs_sha256(inputs), inputs=inputs,
                     n_unsettled=sum(r["outcome_status"] == "UNSETTLED" for r in acc),
                     n_slates=len(inputs["run_records"]), screen_slates=screen,
                     refusals_by_slate={k: refusals_by_slate[k] for k in proofs},
                     records_branch=pv.RECORDS_BRANCH, verdict_path=VERDICT_PATH,
                     run_proofs=proofs, reviewed_at=now.isoformat(), **_env_record(),
                     binding=bool(_binding), slate_ids=list(slate_ids))
            if _dry:
                return v
            _require_freeze_match(api)  # ...and again immediately before writing
            path = wt / vpath
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
            "n_unsettled": sum(r["outcome_status"] == "UNSETTLED" for r in acc),
            "screen_slates": screen, "refusals_by_slate": refusals_by_slate,
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


def main(argv=None) -> int:
    """CLI (binding review): python3 score_nfl_atd_forward.py
    --records-worktree DIR SLATE_ID... Runs review() in this fresh process.
    GITHUB_TOKEN is read from the environment by GitHubAPI and never printed.
    Prints one JSON line {verdict_path, refusal, binding}. Refuses
    (REVIEW_INTERPRETER_MISMATCH) unless every COUNTS slate's run record
    python_version equals this interpreter's (checked after load_slate).
    Pushes nothing. Test switch (environment only): ATD_TEST_FAKE_STATE=<FakeGitHub JSON>
    (+ optional ATD_TEST_NOW) patches the fake in; the verdict is then
    written NON-BINDING to NONBINDING_VERDICT_PATH and the CLI refuses with
    REVIEW_NOT_BINDING_TEST_SWITCH."""
    import argparse
    import platform
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--records-worktree", required=True)
    ap.add_argument("slate_ids", nargs="+")
    args = ap.parse_args(argv)

    def emit(refusal, verdict_path=None, binding=False, rc=2):
        print(json.dumps({"verdict_path": verdict_path, "refusal": refusal,
                          "binding": binding}))
        return rc

    fake_state = os.environ.get("ATD_TEST_FAKE_STATE")
    binding = not fake_state
    try:
        if fake_state:
            from unittest import mock
            import fake_github_api as fk
            api = fk.FakeGitHub.from_json(Path(fake_state).read_text())
            mock.patch.object(pv, "replayers", fk.fake_replayers).start()
            mock.patch.object(sys.modules[__name__], "_review_env_guard", lambda: None).start()
            if os.environ.get("ATD_TEST_NOW"):
                from datetime import datetime
                t = datetime.fromisoformat(os.environ["ATD_TEST_NOW"])
                mock.patch.object(sys.modules[__name__], "_utcnow", lambda: t).start()
        else:
            api = pv.GitHubAPI()
        mod = sys.modules[__name__]
        v = mod.review(args.slate_ids, records_worktree=args.records_worktree, api=api,
                       _binding=binding, _check_interpreter=True)
    except ReviewInterpreterMismatch:
        return emit("REVIEW_INTERPRETER_MISMATCH")
    except ReviewFreezeMismatch:
        return emit("REVIEW_FREEZE_MISMATCH")
    except pv.ProvenanceFailed as e:
        return emit(e.code)
    except ReviewEnvUntrusted:
        return emit("REVIEW_ENV_UNTRUSTED")
    except ReviewAlreadyRecorded:
        return emit("REVIEW_ALREADY_RECORDED")
    except RecordsLocationRefused:
        return emit("RECORDS_LOCATION_REFUSED")
    if v.get("record_state") != "STAGED_NOT_COUNTED":
        return emit(v.get("status", "NO_REVIEW_GATES_NOT_MET"))
    vf = str(Path(args.records_worktree) / (VERDICT_PATH if binding else NONBINDING_VERDICT_PATH))
    if not binding:
        return emit("REVIEW_NOT_BINDING_TEST_SWITCH", vf, False, rc=3)
    return emit(None, vf, True, rc=0)


if __name__ == "__main__":
    raise SystemExit(main())
