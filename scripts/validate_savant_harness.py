"""Harness validation for Statcast (Savant) features — research only.

Compares, out-of-sample and chronological:
  A. xK% (pitch-outcome decomposition, zero intercept, fit on train) vs raw
     K% for pitcher strikeout propensity — Poisson log-loss on actual
     strikeouts per start in the test window.
  B. Savant-augmented team run means vs box-score-only run means for
     ML + fixed-line TOTAL — Brier / log-loss via the backtest harness
     (sportsedge/backtest, imported from ~/workspace/sportsedge-backtest;
     NOT copied in).

Windows (2026 MLB season):
  TRAIN features: 2026-09-01 .. 2026-09-15  (Statcast, strictly prior)
  TEST games:     2026-09-16 .. 2026-09-30  (priced + settled)

Point-in-time discipline: every Savant input to a test-game price comes from
the train window only. Box-score trailing-20 means use completed games
strictly before each test game's date.

Network: 2 batched statcast_search CSVs + a few MLB StatsAPI schedule pulls,
all cached under .scratch-savant/. Nothing here runs in unit tests.

Writes:
  sportsedge/savant_xk_weights_v1.json   (fitted weights + provenance)
  research_notes/savant_validation_20261011.md  (verdict)
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import math
import os
import sys
import time
import types
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

WORKTREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(WORKTREE, ".scratch-savant")
BT_DIR = os.path.expanduser("~/workspace/sportsedge-backtest/sportsedge/backtest")

sys.path.insert(0, WORKTREE)
from sportsedge.mlb_savant_features import (  # noqa: E402
    MIN_PITCHES_PITCHER,
    SCHEMA_VERSION,
    STRIKEOUT_EVENTS,
    SavantFeatureError,
    aggregate_statcast,
    fit_xk_weights,
    parse_statcast_csv,
    pitch_count_history,
    pitch_outcome_rates,
    project_pitch_count,
    record_statcast_fixture,
    team_batter_quality,
)
from sportsedge.mlb_hr_prop_model import (  # noqa: E402
    batter_platoon_power,
    hr_prop_projection,
    league_platoon_hr_rates,
    load_component_park_hr,
)

# Import the harness by file path (never copied into this repo).
_pkg = types.ModuleType("bt_backtest")
_pkg.__path__ = [BT_DIR]
sys.modules["bt_backtest"] = _pkg


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(
        f"bt_backtest.{mod}", os.path.join(BT_DIR, mod + ".py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


bt_splits = _load("splits")
bt_runner = _load("runner")
bt_metrics = _load("metrics")

TRAIN_START = date(2026, 8, 1)  # 46-day train: HR model gates need 50+ PA / 150+ BF
TRAIN_END = date(2026, 9, 15)
TEST_START = date(2026, 9, 16)
TEST_END = date(2026, 9, 30)
BOX_TRAIL_START = date(2026, 8, 12)

SAVANT_BASE = "https://baseballsavant.mlb.com/statcast_search/csv"
STATSAPI = "https://statsapi.mlb.com/api/v1"

UA = {"User-Agent": "SportsEdge-Statcast/1.0 (research validation; batched)"}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={**UA, "Referer": "https://baseballsavant.mlb.com/"}
                                 if "baseballsavant" in url else UA)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


CHUNK_DAYS = 3  # de-facto 25k-row cap: keep each request well under it


def _statcast_chunk(start: date, end: date) -> list[dict]:
    url = (f"{SAVANT_BASE}?all=true&type=details"
           f"&game_date_gt={start.isoformat()}&game_date_lt={end.isoformat()}"
           f"&player_type=batter")
    print(f"  GET {url}")
    raw = _get(url).decode("utf-8", errors="replace")
    rows = parse_statcast_csv(raw)  # fail-closed: schema + truncation check
    print(f"  chunk {start.isoformat()}..{end.isoformat()}: {len(rows)} rows")
    time.sleep(2.0)  # rate discipline
    return rows


def statcast_csv(start: date, end: date) -> str:
    """Batched statcast_search CSVs for a window, chunked (cached).

    The endpoint silently truncates at 25,000 rows, so a long window is
    pulled as consecutive 3-day batched chunks (still never per-game).
    Returns the COMBINED raw CSV text.
    """
    path = os.path.join(
        SCRATCH, f"statcast_{start.isoformat()}_{end.isoformat()}.csv")
    if os.path.exists(path):
        print(f"  cache hit: {path}")
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    cur = start
    chunks: list[list[dict]] = []
    header: list[str] | None = None
    while cur <= end:
        cend = min(end, cur + timedelta(days=CHUNK_DAYS - 1))
        rows = _statcast_chunk(cur, cend)
        if header is None:
            header = list(rows[0].keys())
        chunks.append(rows)
        cur = cend + timedelta(days=1)
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    total = 0
    for rows in chunks:
        w.writerows(rows)
        total += len(rows)
    raw = buf.getvalue()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(raw)
    print(f"  saved {total} pitch rows -> {path}")
    return raw


def statsapi_schedule(start: date, end: date) -> dict:
    path = os.path.join(
        SCRATCH, f"schedule_{start.isoformat()}_{end.isoformat()}.json")
    if os.path.exists(path):
        print(f"  cache hit: {path}")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    url = (f"{STATSAPI}/schedule?sportId=1&startDate={start.isoformat()}"
           f"&endDate={end.isoformat()}&hydrate=team,linescore")
    print(f"  GET {url}")
    payload = json.loads(_get(url).decode("utf-8"))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    time.sleep(1.0)
    return payload


def _game_teams_map(schedule: dict) -> dict[str, tuple[int, int]]:
    out = {}
    for d in schedule.get("dates", []):
        for g in d.get("games", []):
            try:
                out[str(g["gamePk"])] = (
                    int(g["teams"]["away"]["team"]["id"]),
                    int(g["teams"]["home"]["team"]["id"]))
            except (KeyError, TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# A. xK% vs raw K%
# ---------------------------------------------------------------------------

def validation_a(train_rows, test_rows):
    print("== A. xK% vs raw K% ==")
    # Train: per-pitcher decomposition + observed K/pitch.
    by_pitcher: dict[str, list] = defaultdict(list)
    for r in train_rows:
        by_pitcher[str(r.get("pitcher"))].append(r)
    examples = []
    train_info: dict[str, dict] = {}
    for pid, rows in by_pitcher.items():
        if len(rows) < 200:
            continue
        decomp = pitch_outcome_rates(rows, pid)
        if decomp.get("status") != "AVAILABLE":
            continue
        k = sum(1 for r in rows
                if str(r.get("events") or "").strip() in STRIKEOUT_EVENTS)
        examples.append({"rates": decomp["rates"],
                         "k_per_pitch": k / len(rows),
                         "pitches": len(rows)})
        train_info[pid] = {"rates": decomp["rates"],
                           "raw_k_per_pitch": k / len(rows),
                           "pitches": len(rows),
                           "rows": rows}
    print(f"  train pitchers (>=200 pitches): {len(examples)}")
    fit = fit_xk_weights(examples)
    weights = fit["weights"]
    print(f"  fitted weights: {weights}  R2(zero-int)={fit['weighted_r2_zero_intercept']}")

    # Persist the validated weights artifact with provenance.
    artifact_path = os.path.join(WORKTREE, "sportsedge", "savant_xk_weights_v1.json")
    artifact = {
        "weights": weights,
        "method": fit["method"],
        "fit_window": {"start": TRAIN_START.isoformat(), "end": TRAIN_END.isoformat()},
        "n_examples": fit["n_examples"],
        "total_pitches": fit["total_pitches"],
        "weighted_r2_zero_intercept": fit["weighted_r2_zero_intercept"],
        "schema_version": SCHEMA_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "FIT_PENDING_VALIDATION",
    }
    with open(artifact_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2, sort_keys=True)
    print(f"  weights artifact (pending validation): {artifact_path}")

    # Test: per-start projections from TRAIN-only info; actual K from test.
    starts: dict[tuple[str, str], list] = defaultdict(list)
    for r in test_rows:
        starts[(str(r.get("pitcher")), str(r.get("game_pk")))].append(r)
    ll_xk, ll_raw, n = 0.0, 0.0, 0
    details = []
    for (pid, gpk), rows in sorted(starts.items()):
        info = train_info.get(pid)
        if info is None:
            continue
        hist = pitch_count_history(info["rows"], pid)
        proj = project_pitch_count(hist)
        if proj.get("status") != "AVAILABLE":
            continue
        ep = proj["expected_pitches"]
        xk = sum(info["rates"][k] * weights[k]
                 for k in ("called_strike", "whiff", "foul", "in_play"))
        lam_xk = ep * xk
        lam_raw = ep * info["raw_k_per_pitch"]
        if lam_xk <= 0 or lam_raw <= 0:
            continue
        actual_k = sum(1 for r in rows
                       if str(r.get("events") or "").strip() in STRIKEOUT_EVENTS)
        ll_xk += _poisson_logloss(lam_xk, actual_k)
        ll_raw += _poisson_logloss(lam_raw, actual_k)
        n += 1
        details.append({"pitcher": pid, "game_pk": gpk, "actual_k": actual_k,
                        "lam_xk": round(lam_xk, 3), "lam_raw": round(lam_raw, 3)})
    result = {
        "n_starts": n,
        "mean_poisson_logloss_xk": round(ll_xk / n, 5) if n else None,
        "mean_poisson_logloss_raw_k": round(ll_raw / n, 5) if n else None,
        "delta_xk_minus_raw": round(ll_xk / n - ll_raw / n, 5) if n else None,
        "verdict": ("XK_WINS" if n and ll_xk < ll_raw else
                    "RAW_WINS" if n else "NO_DATA"),
    }
    print(f"  n_starts={n}  xk={result['mean_poisson_logloss_xk']}  "
          f"raw={result['mean_poisson_logloss_raw_k']}  "
          f"delta={result['delta_xk_minus_raw']}  -> {result['verdict']}")
    # Stamp the artifact with the validation outcome.
    artifact["status"] = ("VALIDATED_OUT_OF_SAMPLE" if result["verdict"] == "XK_WINS"
                          else "VALIDATION_FAILED")
    artifact["validation"] = {k: v for k, v in result.items() if k != "verdict"}
    artifact["validation"]["verdict"] = result["verdict"]
    with open(artifact_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2, sort_keys=True)
    return result, details


def _poisson_logloss(lam: float, k: int) -> float:
    return lam - k * math.log(lam) + math.lgamma(k + 1)


# ---------------------------------------------------------------------------
# B. Savant-augmented vs box-score-only (ML + fixed-line TOTAL, harness)
# ---------------------------------------------------------------------------

HFA_RUNS = 0.12          # DECLARED, not fit
WIN_PROB_SIGMA = 4.0     # DECLARED sd of run differential
TOTAL_LINE = 8.5         # fixed line (no market data available)
TOTAL_SIGMA = 4.5        # DECLARED sd of game total
PA_PER_GAME = 38
BF_PER_START = 22
WOBA_SCALE = 1.21


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _clip(p: float) -> float:
    return min(0.99, max(0.01, p))


def validation_b(train_rows, test_rows, train_sched, test_sched, trail_sched):
    print("== B. savant-augmented vs box-score-only ==")
    game_teams = _game_teams_map(train_sched)
    tq = team_batter_quality(train_rows, game_teams)
    team_xwoba = {t: v["team_xwoba"] for t, v in tq.get("teams", {}).items()
                  if v.get("status") == "AVAILABLE"}
    # League xwOBA + pitcher xwOBA-against from the train aggregation.
    now = datetime.now(timezone.utc)
    batters, pitchers = aggregate_statcast(
        train_rows, start_date=TRAIN_START, end_date=TRAIN_END, retrieved_at=now)
    lg_vals = [float(r["xwoba_contact"]) for r in batters
               if r.get("xwoba_contact") is not None]
    lg = sum(lg_vals) / len(lg_vals)
    pit_xwoba = {str(r["entity_id"]): float(r["xwoba_contact"])
                 for r in pitchers if r.get("xwoba_contact") is not None}
    print(f"  league xwOBA(train)={lg:.4f}  teams={len(team_xwoba)}  "
          f"pitchers={len(pit_xwoba)}")

    # Trailing-20 box-score runs per team per date (strictly prior games).
    completed: dict[int, list] = defaultdict(list)  # team -> [(date, rs, ra)]
    for d in trail_sched.get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("codedGameState") != "F":
                continue
            try:
                gd = date.fromisoformat(d["date"])
                a = g["teams"]["away"]; h = g["teams"]["home"]
                aid = int(a["team"]["id"]); hid = int(h["team"]["id"])
                ars = int(a["score"]); hrs = int(h["score"])
            except (KeyError, TypeError, ValueError):
                continue
            completed[aid].append((gd, ars, hrs))
            completed[hid].append((gd, hrs, ars))
    for t in completed:
        completed[t].sort()

    def trailing20(team: int, before: date):
        games = [g for g in completed.get(team, []) if g[0] < before][-20:]
        if len(games) < 10:
            return None
        return (sum(g[1] for g in games) / len(games),
                sum(g[2] for g in games) / len(games))

    # Test CSV team map + actual-starter fallback.
    test_teams = _game_teams_map(test_sched)
    starter_pitches: dict[tuple[str, str], int] = defaultdict(int)
    pitcher_game_team: dict[tuple[str, str], int] = {}
    for r in test_rows:
        gpk_r = str(r.get("game_pk"))
        pid_r = str(r.get("pitcher"))
        starter_pitches[(gpk_r, pid_r)] += 1
        # The pitcher's team is the fielding team: opposite of the batting
        # team resolved via inning_topbot.
        teams = test_teams.get(gpk_r)
        if teams:
            topbot = str(r.get("inning_topbot") or "").strip()
            if topbot == "Top":
                pitcher_game_team.setdefault((gpk_r, pid_r), teams[1])
            elif topbot == "Bot":
                pitcher_game_team.setdefault((gpk_r, pid_r), teams[0])

    fixtures = []
    skipped = defaultdict(int)
    for d in test_sched.get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("codedGameState") != "F":
                skipped["not_final"] += 1
                continue
            try:
                gd = date.fromisoformat(d["date"])
                a = g["teams"]["away"]; h = g["teams"]["home"]
                aid = int(a["team"]["id"]); hid = int(h["team"]["id"])
                ars = int(a["score"]); hrs = int(h["score"])
                kickoff = g["gameDate"]
            except (KeyError, TypeError, ValueError):
                skipped["malformed"] += 1
                continue
            t20h = trailing20(hid, gd); t20a = trailing20(aid, gd)
            if t20h is None or t20a is None:
                skipped["no_trailing20"] += 1
                continue
            # Probable pitchers: schedule payload first, else actual-starter
            # fallback (documented caveat: uses post-game identity, but the
            # quality signal itself is strictly train-window).
            hp = _probable(g, "home"); ap = _probable(g, "away")
            gpk = str(g["gamePk"])
            caveat = []
            if hp is None:
                hp = _fallback_starter(gpk, hid, starter_pitches,
                                       pitcher_game_team)
                caveat.append("home_starter_fallback")
            if ap is None:
                ap = _fallback_starter(gpk, aid, starter_pitches,
                                       pitcher_game_team)
                caveat.append("away_starter_fallback")
            fixtures.append({
                "fixture_id": f"mlb-{gpk}", "kickoff": kickoff,
                "as_of": gd.isoformat() + "T00:00:00+00:00",
                "home_id": hid, "away_id": aid,
                "home_score": hrs, "away_score": ars,
                "home_rs20": t20h[0], "home_ra20": t20h[1],
                "away_rs20": t20a[0], "away_ra20": t20a[1],
                "home_xwoba": team_xwoba.get(str(hid)),
                "away_xwoba": team_xwoba.get(str(aid)),
                "home_pit_xwoba": pit_xwoba.get(str(hp)) if hp else None,
                "away_pit_xwoba": pit_xwoba.get(str(ap)) if ap else None,
                "home_pid": hp, "away_pid": ap,
                "caveats": caveat,
            })
    print(f"  fixtures={len(fixtures)} skipped={dict(skipped)}")

    def price_fn(model, fixture, as_of, train):
        hrs20, hra20 = fixture["home_rs20"], fixture["home_ra20"]
        ars20, ara20 = fixture["away_rs20"], fixture["away_ra20"]
        mh = (hrs20 + ara20) / 2 + HFA_RUNS
        ma = (ars20 + hra20) / 2
        if model == "savant_augmented":
            lgx = lg
            hx, ax = fixture["home_xwoba"], fixture["away_xwoba"]
            if hx is not None:
                mh += ((hx - lgx) / WOBA_SCALE) * PA_PER_GAME
            if ax is not None:
                ma += ((ax - lgx) / WOBA_SCALE) * PA_PER_GAME
            hpx, apx = fixture["home_pit_xwoba"], fixture["away_pit_xwoba"]
            if hpx is not None:  # home starter suppresses away scoring
                ma += ((hpx - lgx) / WOBA_SCALE) * BF_PER_START
            if apx is not None:
                mh += ((apx - lgx) / WOBA_SCALE) * BF_PER_START
        elif model != "boxscore_only":
            raise ValueError("unknown model " + model)
        p_home = _clip(_phi((mh - ma) / WIN_PROB_SIGMA))
        p_over = _clip(1.0 - _phi((TOTAL_LINE - (mh + ma)) / TOTAL_SIGMA))
        return [
            {"market": "ML", "selection": "HOME", "model_p": p_home},
            {"market": f"TOTAL_{TOTAL_LINE}", "selection": "OVER",
             "model_p": p_over},
        ]

    def settle_fn(fixture, market, selection, line):
        hs, aws = fixture["home_score"], fixture["away_score"]
        if market == "ML":
            return 1.0 if hs > aws else 0.0
        total = hs + aws
        if total > TOTAL_LINE:
            return 1.0
        if total < TOTAL_LINE:
            return 0.0
        return 0.5

    models = ["boxscore_only", "savant_augmented"]
    split = bt_splits.Split(train=[], test=fixtures)
    result = bt_runner.run_backtest(
        fixtures=fixtures, splits=[split], models=models,
        price_fn=price_fn, settle_fn=settle_fn, market_baseline=None)
    by_model_market: dict[tuple[str, str], list] = defaultdict(list)
    for model, recs in result["records"].items():
        for r in recs:
            by_model_market[(model, r["market"])].append(r)
    summary = {}
    for (model, market), recs in sorted(by_model_market.items()):
        s = bt_metrics.summarize(recs)
        summary[f"{model}/{market}"] = {
            "n": s["n"], "brier": round(s["brier"], 5),
            "log_loss": round(s["log_loss"], 5)}
    for k, v in summary.items():
        print(f"  {k}: n={v['n']} brier={v['brier']} logloss={v['log_loss']}")
    print(f"  market baseline: {result['baseline']['status']} (no odds data)")
    verdicts = {}
    for market in ("ML", f"TOTAL_{TOTAL_LINE}"):
        b = summary[f"boxscore_only/{market}"]
        s = summary[f"savant_augmented/{market}"]
        verdicts[market] = {
            "brier_delta_savant_minus_box": round(s["brier"] - b["brier"], 5),
            "logloss_delta_savant_minus_box": round(s["log_loss"] - b["log_loss"], 5),
            "verdict": ("SAVANT_WINS" if s["brier"] < b["brier"]
                        and s["log_loss"] < b["log_loss"]
                        else "SPLIT" if (s["brier"] - b["brier"])
                        * (s["log_loss"] - b["log_loss"]) < 0
                        else "BOX_WINS"),
        }
        print(f"  {market}: {verdicts[market]}")
    return {"summary": summary, "verdicts": verdicts,
            "baseline_status": result["baseline"]["status"],
            "n_fixtures": len(fixtures), "fixtures": fixtures}


def _probable(game: dict, side: str):
    try:
        return int(game["teams"][side].get("probablePitcher", {}).get("id"))
    except (KeyError, TypeError, ValueError):
        return None


def _fallback_starter(gpk: str, team_id: int, starter_pitches: dict,
                      pitcher_game_team: dict) -> int | None:
    # Actual starter = most pitches thrown FOR THAT TEAM in the game
    # (post-game identity; the pitcher-quality signal remains train-window).
    cands = sorted(
        ((p, n) for (g, p), n in starter_pitches.items()
         if g == gpk and pitcher_game_team.get((g, p)) == team_id),
        key=lambda x: -x[1])
    if not cands:
        return None
    try:
        return int(cands[0][0])
    except (TypeError, ValueError):
        return None



PARK_FACTORS_PATH = os.path.expanduser(
    "~/workspace/sportsedge-freefactors/data/component_park_factors_2022_2024.json")


def validation_c(train_rows, test_rows, test_sched, game_pitchers):
    """C. HR prop model vs naive batter-HR-rate baseline (Brier/log-loss).

    Per batter-game in the test window: model P(>=1 HR) from the regressed
    platoon + pitcher + park model vs naive (train HR/PA * 4.2). Actual =
    batter homered in the game. Scored with harness metrics.
    """
    print("== C. HR model vs naive batter-HR-rate ==")
    try:
        park_factors = load_component_park_hr(PARK_FACTORS_PATH)
    except Exception as exc:
        print(f"  park factors unavailable: {exc}")
        return {"status": "BLOCKED", "reason": f"HR_PARK_FACTORS_UNAVAILABLE:{exc}"}
    lgm = league_platoon_hr_rates(train_rows)
    league_matchups = lgm.get("matchups") if lgm.get("status") == "AVAILABLE" else {}
    # train per-batter / per-pitcher rows, hands (precomputed once)
    by_batter = defaultdict(list)
    by_pitcher = defaultdict(list)
    batter_stands: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    pitcher_hands: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in train_rows:
        by_batter[str(r.get("batter"))].append(r)
        by_pitcher[str(r.get("pitcher"))].append(r)
        st = str(r.get("stand") or "").strip().upper()
        if st in ("L", "R", "S"):
            batter_stands[str(r.get("batter"))][st] += 1
        ph = str(r.get("p_throws") or "").strip().upper()
        if ph in ("L", "R"):
            pitcher_hands[str(r.get("pitcher"))][ph] += 1
    _tot_pa = _tot_hr = 0
    for r in train_rows:
        ev = str(r.get("events") or "").strip()
        if ev:
            _tot_pa += 1
            if ev == "home_run":
                _tot_hr += 1
    league_hr_pa = _tot_hr / _tot_pa if _tot_pa else 0.0
    batter_hand = {b: max(v, key=v.get) for b, v in batter_stands.items() if v}
    pitcher_hand = {p: max(v, key=v.get) for p, v in pitcher_hands.items() if v}
    # test: batter-game HR outcomes
    game_hr: dict[tuple[str, str], int] = defaultdict(int)
    for r in test_rows:
        if str(r.get("events") or "").strip() == "home_run":
            game_hr[(str(r.get("batter")), str(r.get("game_pk")))] = 1
    # naive baseline train HR/PA per batter
    naive_rate = {}
    for b, rows in by_batter.items():
        pa = sum(1 for r in rows if str(r.get("events") or "").strip())
        hr_n = sum(1 for r in rows if str(r.get("events") or "").strip() == "home_run")
        if pa >= 50:
            naive_rate[b] = hr_n / pa if pa else 0.0

    model_recs, base_recs = [], []
    skipped = defaultdict(int)
    for d in test_sched.get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("codedGameState") != "F":
                continue
            gpk = str(g["gamePk"])
            try:
                home_name = g["teams"]["home"]["team"]["name"]
            except (KeyError, TypeError):
                skipped["no_home_name"] += 1
                continue
            if home_name not in park_factors:
                skipped["park_factor_missing"] += 1
                continue
            info = game_pitchers.get(gpk)
            if not info:
                skipped["no_pitcher_info"] += 1
                continue
            # batters who appeared for either team in this game (test rows)
            batters = {str(r.get("batter")) for r in test_rows
                       if str(r.get("game_pk")) == gpk}
            for b in batters:
                if b not in naive_rate:
                    skipped["batter_history_insufficient"] += 1
                    continue
                bh = batter_hand.get(b)
                if bh not in ("L", "R", "S"):
                    skipped["batter_hand_unknown"] += 1
                    continue
                # matchup: the starter the batter most likely faced
                # (PA-share by batting side in the test game).
                opp = _opp_starter(b, gpk, test_rows, info, pitcher_hand)
                if opp is None:
                    skipped["pitcher_hand_unknown"] += 1
                    continue
                pid, ph = opp
                proj = hr_prop_projection(
                    batter_id=b, batter_hand=bh, pitcher_id=pid,
                    pitcher_hand=ph, home_team_name=home_name,
                    pitch_rows=by_batter[b] + by_pitcher[str(pid)],
                    park_hr_factors=park_factors,
                    league_matchups=league_matchups,
                    league_hr_per_pa=league_hr_pa)
                if proj.get("status") != "AVAILABLE":
                    skipped["model_blocked:" + str(proj.get("reason"))] += 1
                    continue
                lam_base = 4.2 * naive_rate[b]
                p_base = 1.0 - math.exp(-lam_base) if lam_base > 0 else 0.0
                y = 1.0 if game_hr.get((b, gpk)) else 0.0
                model_recs.append({"model_p": proj["p_ge1_hr"], "outcome": y})
                base_recs.append({"model_p": min(0.99, max(0.01, p_base)),
                                  "outcome": y})
    out = {"status": "AVAILABLE" if model_recs else "NO_DATA",
           "n_batter_games": len(model_recs),
           "skipped": dict(skipped)}
    if model_recs:
        sm = bt_metrics.summarize(model_recs)
        sb = bt_metrics.summarize(base_recs)
        out["model"] = {"brier": round(sm["brier"], 5),
                        "log_loss": round(sm["log_loss"], 5),
                        "mean_p": round(sm["mean_p"], 4),
                        "base_rate": round(sm["base_rate"], 4)}
        out["naive_baseline"] = {"brier": round(sb["brier"], 5),
                                 "log_loss": round(sb["log_loss"], 5)}
        out["brier_delta_model_minus_base"] = round(sm["brier"] - sb["brier"], 5)
        out["logloss_delta_model_minus_base"] = round(sm["log_loss"] - sb["log_loss"], 5)
        out["verdict"] = ("MODEL_WINS" if sm["brier"] < sb["brier"]
                          and sm["log_loss"] < sb["log_loss"]
                          else "SPLIT" if (sm["brier"] - sb["brier"])
                          * (sm["log_loss"] - sb["log_loss"]) < 0
                          else "BASELINE_WINS")
        print(f"  n={len(model_recs)} model brier={out['model']['brier']} "
              f"ll={out['model']['log_loss']} | base brier={out['naive_baseline']['brier']} "
              f"ll={out['naive_baseline']['log_loss']} -> {out['verdict']}")
        print(f"  skipped: {dict(skipped)}")
    return out


def _opp_starter(batter, gpk, test_rows, info, pitcher_hand):
    """(pitcher_id, hand) of the starter the batter most likely faced.

    Each of the batter's test-game PA is resolved to the batting side via
    inning_topbot; the side with the PA majority is his team, so he faced
    the OTHER team's starter. Returns None when the starter's hand is
    unverified (fail-closed, matching the model's BLOCKED behavior).
    """
    away_pa = home_pa = 0
    for r in test_rows:
        if str(r.get("batter")) != batter or str(r.get("game_pk")) != gpk:
            continue
        if not str(r.get("events") or "").strip():
            continue
        topbot = str(r.get("inning_topbot") or "").strip()
        if topbot == "Top":
            away_pa += 1
        elif topbot == "Bot":
            home_pa += 1
    if away_pa == 0 and home_pa == 0:
        return None
    # Batter likely bats for the side with more of his PA -> faced the other
    # team's starter.
    pid = info["home_pid"] if away_pa >= home_pa else info["away_pid"]
    if pid is None:
        return None
    ph = pitcher_hand.get(str(pid))
    if ph not in ("L", "R"):
        return None
    return pid, ph

def _read_combined_cached(start: date, end: date) -> list[dict]:
    """Read a combined chunk-cache file WITHOUT the single-response cap check.

    Each chunk was schema- and truncation-checked individually at download
    time by _statcast_chunk; the combined file legitimately exceeds the
    25,000-row single-response cap.
    """
    import csv as _csv
    path = os.path.join(
        SCRATCH, f"statcast_{start.isoformat()}_{end.isoformat()}.csv")
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(_csv.DictReader(fh))
    if not rows:
        raise SavantFeatureError("SAVANT_NO_ROWS")
    missing = {"game_date", "batter", "pitcher", "events", "description"} - set(rows[0])
    if missing:
        raise SavantFeatureError("SAVANT_SCHEMA_UNEXPECTED:missing=" + ",".join(sorted(missing)))
    return rows


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    print("downloading statcast windows...")
    statcast_csv(TRAIN_START, TRAIN_END)  # chunked, cached
    statcast_csv(TEST_START, TEST_END)
    train_rows = _read_combined_cached(TRAIN_START, TRAIN_END)
    test_rows = _read_combined_cached(TEST_START, TEST_END)
    print(f"train rows={len(train_rows)} test rows={len(test_rows)}")
    print("downloading schedules...")
    train_sched = statsapi_schedule(TRAIN_START, TRAIN_END)
    test_sched = statsapi_schedule(TEST_START, TEST_END)
    trail_sched = statsapi_schedule(BOX_TRAIL_START, TEST_END)

    res_a, details_a = validation_a(train_rows, test_rows)
    res_b = validation_b(train_rows, test_rows, train_sched, test_sched,
                         trail_sched)
    game_pitchers = {}
    for fx in res_b.get("fixtures", []):
        gpk = str(fx["fixture_id"]).replace("mlb-", "")
        game_pitchers[gpk] = {
            "home_pid": fx.get("home_pid"), "away_pid": fx.get("away_pid")}
    res_c = validation_c(train_rows, test_rows, test_sched, game_pitchers)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "windows": {
            "train": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
            "test": [TEST_START.isoformat(), TEST_END.isoformat()],
        },
        "validation_a_xk_vs_raw_k": res_a,
        "validation_b_savant_vs_boxscore": {k: v for k, v in res_b.items()
                                            if k != "fixtures"},
        "validation_c_hr_model_vs_naive": res_c,
        "notes": [
            "No market baseline: no odds data; baseline leg MISSING by design.",
            "Books-shade-overs observation NOT used anywhere (eval-only).",
            "Starter fallback (actual most-pitches arm) used when schedule "
            "probablePitcher missing; quality signal strictly train-window.",
        ],
    }
    out = os.path.join(WORKTREE, "research_notes",
                       "savant_validation_20261011.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print(f"report -> {out}")
    # Markdown verdict
    md = _render_markdown(report)
    md_path = os.path.join(WORKTREE, "research_notes",
                           "savant_validation_20261011.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"markdown -> {md_path}")


def _render_markdown(report: dict) -> str:
    a = report["validation_a_xk_vs_raw_k"]
    b = report["validation_b_savant_vs_boxscore"]
    lines = [
        "# Savant feature validation — 2026-10-11",
        "",
        f"Generated {report['generated_at']}. Research only.",
        "",
        "Train (features): 2026-09-01..2026-09-15. Test (priced): 2026-09-16..2026-09-30.",
        "All Savant inputs strictly prior to each test game (no lookahead).",
        "Market baseline: MISSING (no odds data) — comparisons are model-vs-model.",
        "",
        "## A. xK% vs raw K% (pitcher strikeout propensity)",
        "",
        f"- Test starts: {a['n_starts']}",
        f"- Mean Poisson log-loss: xK% {a['mean_poisson_logloss_xk']} vs raw K% {a['mean_poisson_logloss_raw_k']}",
        f"- Delta (xK − raw): {a['delta_xk_minus_raw']} (negative favors xK%)",
        f"- Verdict: **{a['verdict']}**",
        "",
        "## B. Savant-augmented vs box-score-only (ML + TOTAL 8.5)",
        "",
    ]
    for k, v in b["summary"].items():
        lines.append(f"- {k}: n={v['n']} brier={v['brier']} log_loss={v['log_loss']}")
    lines.append("")
    for market, v in b["verdicts"].items():
        lines.append(
            f"- {market}: brier Δ {v['brier_delta_savant_minus_box']}, "
            f"log-loss Δ {v['logloss_delta_savant_minus_box']} → **{v['verdict']}**")
    c = report["validation_c_hr_model_vs_naive"]
    lines += ["", "## C. HR prop model vs naive batter-HR-rate baseline", ""]
    if c.get("status") == "AVAILABLE":
        lines.append(f"- Batter-games: {c['n_batter_games']}")
        lines.append(f"- Model: brier {c['model']['brier']}, log-loss {c['model']['log_loss']}, "
                     f"mean P(HR) {c['model']['mean_p']}, base rate {c['model']['base_rate']}")
        lines.append(f"- Naive: brier {c['naive_baseline']['brier']}, log-loss {c['naive_baseline']['log_loss']}")
        lines.append(f"- Δ brier {c['brier_delta_model_minus_base']}, "
                     f"Δ log-loss {c['logloss_delta_model_minus_base']} → **{c['verdict']}**")
    else:
        lines.append(f"- {c.get('status')}: {c.get('reason')}")
    lines += [
        "",
        "## Caveats",
        "- Declared constants (not fit): HFA 0.12 runs, win-prob σ 4.0, total σ 4.5,",
        "  38 PA/game, 22 BF/start, wOBA→runs scale 1.21. Paired comparison, so",
        "  the delta isolates the Savant signal.",
        "- Probable-pitcher fallback: actual most-pitches arm when the schedule",
        "  payload lacks probablePitcher (post-game identity; quality signal",
        "  itself is train-window only).",
        "- Books-shade-overs observation used NOWHERE (evaluation-side only).",
        "",
        "Standing bar: nothing ships as production-ready unless it wins",
        "out-of-sample on BOTH Brier and log-loss.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
