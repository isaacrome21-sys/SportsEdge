"""NBA props V2 — closure evidence for the owner's two review
checklist items (Isaac's disposition, Oct 26, 2026).

Run: python3 -m pytest tests/test_nba_props_v2_review_items_20261026.py

ITEM 1 — the §9.2 Run B two-row discrepancy, reproduced and
bounded. Pricing the Oct 25 PM captures against the full Oct 26
research store gives 556 INSUFFICIENT_PRIOR_GAMES / 26
PLAYER_NOT_IN_STORE; against the history-truncated Oct 25-slate
dry-run store, 554 / 28. These tests reproduce both count pairs
from the saved artifacts with one parameterized code path (the
proof drivers' row-building logic), diff the two runs row by row,
and prove the discrepancy is exactly the OVER/UNDER rows of one
capture entry — token 'Black' (ORL@NYK, points, line 8.5) — whose
full-store resolution target, Anthony Black (player 4712849), has
his SOLE store presence in game 401909863 on the slate date itself
(2026-10-25) and 0 prior games strictly before it. They then prove
the class cannot change counted eligibility (force the resolution
both ways: refused identically) and cannot silently drop a player
(every unresolved name yields explicit PLAYER_NOT_IN_STORE rows;
outputs == inputs in both runs).

ITEM 2 — the supplement fetch path, unexercised by the live dry
runs, covered by a deterministic regression: slate_build.fetch is
replaced with a fixture dispatcher (no network). The summary
fixture is SYNTHETIC, built to the transform's expected schema —
no recorded Oct 25 summary response survives in the workspace
(the build-time /tmp copies are gone). The machinery's home suite
(goal workspace test_slate_build.py) carries the same regression;
this copy binds it to the branch for review.

Item 1 tests are artifact-backed (goal-workspace stores + the
operative captures) and skip if those artifacts are absent.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsedge import nba_phone_prop_pricing as pricing  # noqa: E402

HF = Path("/home/hatch/workspace/goals/nba-readiness-and-backtest-harness"
          "/hidden_files")
FULL_STORE_DIR = HF / "nba_prop_store_20261026"
TRUNC_STORE_DIR = HF / "nba_prop_store_slate_dryrun_20261025"
CAPTURES = Path("/home/hatch/workspace/sportsedge/"
                "operative_run_20261025_runit_pm/captures_all.json")
RAW_BOARD = Path("/home/hatch/workspace/sportsedge/"
                 "nba_props_ledger_20261021/RAW_BOARD.json")
ARTIFACTS_PRESENT = all(p.exists() for p in (
    FULL_STORE_DIR, TRUNC_STORE_DIR, CAPTURES, RAW_BOARD))
artifact_test = pytest.mark.skipif(
    not ARTIFACTS_PRESENT,
    reason="goal-workspace proof artifacts not present on this machine")

SLATE_BUILD_DIR = FULL_STORE_DIR
if SLATE_BUILD_DIR.exists():
    sys.path.insert(0, str(SLATE_BUILD_DIR))
slate_build = pytest.importorskip(
    "slate_build", reason="per-slate machinery not present")

FIXTURE_TEAMS = {
    "LA Lakers @ UTA Jazz": ("LAL", "UTAH"),
    "IND Pacers @ BKN Nets": ("IND", "BKN"),
    "ORL Magic @ NY Knicks": ("ORL", "NY"),
    "TOR Raptors @ MIN Timberwolves": ("TOR", "MIN"),
    "LA Clippers @ OKC Thunder": ("LAC", "OKC"),
    "DET Pistons @ PHI 76ers": ("DET", "PHI"),
    "MEM Grizzlies @ SAC Kings": ("MEM", "SAC"),
}
MARKETS = {"props_points": "PLAYER_POINTS",
           "props_rebounds": "PLAYER_REBOUNDS",
           "props_assists": "PLAYER_ASSISTS",
           "props_pra": "PLAYER_PRA"}
NOW_A = datetime.fromisoformat("2026-10-21T18:03:05-05:00")
NOW_B = datetime.fromisoformat("2026-10-25T16:14:00-05:00")
AB_ID = "4712849"          # Anthony Black
AB_GAME = "401909863"      # ORL@NYK, 2026-10-25 — the slate game itself


def _build_rows_b(store_dir):
    """The proof drivers' Run B row building, verbatim logic."""
    pull = list(csv.DictReader(open(
        store_dir / "nba_player_games_2026-27.csv")))
    latest_team, name_by_id = {}, {}
    for r in pull:
        latest_team[r["PLAYER_ID"]] = r["TEAM_ABBREVIATION"]
        name_by_id[r["PLAYER_ID"]] = r["PLAYER_NAME"]

    def expand(token, teams):
        t = token.replace(".", "").strip().lower()
        cands = set()
        for pid, nm in name_by_id.items():
            if latest_team.get(pid) not in teams:
                continue
            n = nm.replace(".", "").lower()
            if t == n.split()[-1] or n.endswith(" " + t) or t == n:
                cands.add(nm)
        return cands

    cap = json.load(open(CAPTURES))
    rows_b, meta, unresolved = [], [], []
    for g in cap["games"]:
        if g.get("league") != "NBA":
            continue
        teams = FIXTURE_TEAMS[g["game"]]
        commence = f"2026-10-25T{g['tip_ct']}:00-05:00"
        qcap = f"2026-10-25T{g['captured_ct'].split('-')[0]}:00-05:00"
        for key, market in MARKETS.items():
            for entry in g.get(key) or []:
                token, line, over, under = (entry[0], entry[1],
                                            entry[2], entry[3])
                cands = expand(str(token), teams)
                if len(cands) == 1:
                    pname = next(iter(cands))
                else:
                    pname = str(token)
                    unresolved.append((g["game"], str(token)))
                for side, odds in (("OVER", over), ("UNDER", under)):
                    rows_b.append({
                        "sport": "NBA", "market": market,
                        "player_name": pname, "line": line, "side": side,
                        "odds": odds, "book": "draftkings",
                        "commence_time": commence,
                        "quote_captured_at": qcap})
                    meta.append({"game": g["game"], "market_key": key,
                                 "token": str(token), "side": side,
                                 "pname": pname})
    return rows_b, meta, unresolved


def _counts(outputs):
    return dict(collections.Counter(
        o.get("blocker") if o.get("status") == "NO_MODEL_OR_MARKET"
        else "PRICED" for o in outputs))


@pytest.fixture(scope="module")
def runs():
    out = {}
    raw = json.load(open(RAW_BOARD))
    for tag, sdir in (("FULL", FULL_STORE_DIR), ("TRUNC", TRUNC_STORE_DIR)):
        store, receipt = pricing.load_store_from_dir(str(sdir))
        assert receipt["status"] == "NBA_PROP_STORE_LOADED"
        out_a, _ = pricing.phone_nba_prop_rows(raw, now=NOW_A, store=store)
        rows_b, meta, unresolved = _build_rows_b(sdir)
        out_b, _ = pricing.phone_nba_prop_rows(
            rows_b, now=NOW_B, store=store)
        out[tag] = {"store": store, "counts_a": _counts(out_a),
                    "rows_b": rows_b, "meta": meta, "out_b": out_b,
                    "counts_b": _counts(out_b), "unresolved": unresolved}
    return out


# ---------- item 1(a): reproduction ----------

@artifact_test
def test_runb_counts_reproduce_on_both_stores(runs):
    assert runs["FULL"]["counts_b"] == {
        "NBA_PROP_INSUFFICIENT_PRIOR_GAMES": 556,
        "NBA_PROP_PLAYER_NOT_IN_STORE": 26}
    assert runs["TRUNC"]["counts_b"] == {
        "NBA_PROP_INSUFFICIENT_PRIOR_GAMES": 554,
        "NBA_PROP_PLAYER_NOT_IN_STORE": 28}
    for tag in ("FULL", "TRUNC"):
        assert len(runs[tag]["rows_b"]) == 582
        assert len(runs[tag]["out_b"]) == 582  # outputs == inputs


@artifact_test
def test_runa_counts_identical_on_both_stores(runs):
    expected = {"NBA_PROP_INSUFFICIENT_PRIOR_GAMES": 1130,
                "NBA_PROP_PLAYER_NOT_IN_STORE": 12}
    assert runs["FULL"]["counts_a"] == expected
    assert runs["TRUNC"]["counts_a"] == expected


@artifact_test
def test_runb_diff_is_exactly_the_two_black_point_rows(runs):
    f, t = runs["FULL"], runs["TRUNC"]
    diffs = []
    for i, (of, ot) in enumerate(zip(f["out_b"], t["out_b"])):
        bf = (of.get("blocker") if of.get("status") == "NO_MODEL_OR_MARKET"
              else "PRICED")
        bt = (ot.get("blocker") if ot.get("status") == "NO_MODEL_OR_MARKET"
              else "PRICED")
        if bf != bt or f["meta"][i]["pname"] != t["meta"][i]["pname"]:
            diffs.append((f["meta"][i], bf, bt))
    assert len(diffs) == 2
    assert {d[0]["side"] for d in diffs} == {"OVER", "UNDER"}
    for meta, bf, bt in diffs:
        assert meta["game"] == "ORL Magic @ NY Knicks"
        assert meta["market_key"] == "props_points"
        assert meta["token"] == "Black"
        assert meta["pname"] == "Anthony Black"        # FULL resolution
        assert bf == "NBA_PROP_INSUFFICIENT_PRIOR_GAMES"
        assert bt == "NBA_PROP_PLAYER_NOT_IN_STORE"
    trunc_names = {m["pname"] for m in
                   (t["meta"][i] for i in range(len(t["meta"])))}
    assert "Black" in trunc_names  # raw token used in the TRUNC build
    # the only resolution difference between the two builds
    assert sorted(set(runs["TRUNC"]["unresolved"]) -
                  set(runs["FULL"]["unresolved"])) == [
                      ("ORL Magic @ NY Knicks", "Black")]
    assert sorted(set(runs["FULL"]["unresolved"]) -
                  set(runs["TRUNC"]["unresolved"])) == []


@artifact_test
def test_anthony_black_sole_presence_is_the_slate_game(runs):
    pull_full = list(csv.DictReader(open(
        FULL_STORE_DIR / "nba_player_games_2026-27.csv")))
    dates_full = {r["GAME_ID"]: r["GAME_DATE"] for r in csv.DictReader(
        open(FULL_STORE_DIR / "game_dates.csv"))}
    ab_rows = [r for r in pull_full if r["PLAYER_ID"] == AB_ID]
    assert len(ab_rows) == 1
    assert ab_rows[0]["GAME_ID"] == AB_GAME
    assert ab_rows[0]["TEAM_ABBREVIATION"] == "ORL"
    assert dates_full[AB_GAME] == "2026-10-25"  # the slate date itself
    pull_trunc = list(csv.DictReader(open(
        TRUNC_STORE_DIR / "nba_player_games_2026-27.csv")))
    assert [r for r in pull_trunc if r["PLAYER_ID"] == AB_ID] == []
    assert AB_ID not in set(runs["TRUNC"]["store"].player_ids())
    # the other Black is team-filtered out of this fixture in BOTH
    # stores (latest team SAC), so he is not part of the discrepancy
    for pull in (pull_full, pull_trunc):
        lb = [r for r in pull if r["PLAYER_ID"] == "4395650"]
        assert lb and lb[-1]["TEAM_ABBREVIATION"] == "SAC"
    # and even in the FULL store he has zero priors before the slate
    store = runs["FULL"]["store"]
    assert store.player_prior_values(AB_ID, "points",
                                     date(2026, 10, 25)) == []
    probe = store.price(AB_ID, "points", 8.5, date(2026, 10, 25))
    assert probe["status"] != "PRICED"
    assert probe["reason"] == "NBA_PROP_INSUFFICIENT_PRIOR_GAMES"
    assert probe["n_prior"] == 0


# ---------- item 1(c): no silent drop ----------

@artifact_test
def test_unresolved_names_yield_explicit_refusal_rows(runs):
    for tag in ("FULL", "TRUNC"):
        r = runs[tag]
        # every unresolved capture occurrence maps to input rows that
        # carry the raw token, and every such row is an explicit
        # PLAYER_NOT_IN_STORE refusal in the output — nothing dropped
        raw_rows = [i for i, m in enumerate(r["meta"])
                    if (m["game"], m["token"]) in
                    [tuple(u) for u in r["unresolved"]]
                    and m["pname"] == m["token"]]
        assert len(raw_rows) == 2 * len(r["unresolved"])
        for i in raw_rows:
            o = r["out_b"][i]
            assert o["status"] == "NO_MODEL_OR_MARKET"
            assert o["blocker"] == "NBA_PROP_PLAYER_NOT_IN_STORE"
            assert o["player_name"] == r["meta"][i]["token"]
        # and those are ALL the not-in-store rows of the run
        assert r["counts_b"]["NBA_PROP_PLAYER_NOT_IN_STORE"] == \
            len(raw_rows)
    # the two 'Black' rows specifically, in the TRUNC run
    t = runs["TRUNC"]
    black = [i for i, m in enumerate(t["meta"])
             if m["game"] == "ORL Magic @ NY Knicks"
             and m["token"] == "Black"]
    assert len(black) == 2
    for i in black:
        assert t["out_b"][i]["blocker"] == \
            "NBA_PROP_PLAYER_NOT_IN_STORE"
        assert t["out_b"][i]["player_name"] == "Black"


# ---------- item 1(b): counted eligibility is invariant ----------

def _black_rows(pname):
    return [{"sport": "NBA", "market": "PLAYER_POINTS",
             "player_name": pname, "line": 8.5, "side": side,
             "odds": odds, "book": "draftkings",
             "commence_time": "2026-10-25T18:30:00-05:00",
             "quote_captured_at": "2026-10-25T15:22:00-05:00"}
            for side, odds in (("OVER", -129), ("UNDER", 101))]


def _synthetic_store_with_slate_game(tmp_path):
    """TRUNC store + ONLY Anthony Black's Oct 25 game added — the
    most favorable (incorrect) history a counted Oct 25 build could
    be handed, short of the full store."""
    dst = tmp_path / "store_plus_slate_game"
    dst.mkdir()
    for name in ("nba_player_games_2026-27.csv", "game_dates.csv",
                 "positions.csv"):
        shutil.copy(TRUNC_STORE_DIR / name, dst / name)
    ab_row = next(r for r in csv.DictReader(open(
        FULL_STORE_DIR / "nba_player_games_2026-27.csv"))
        if r["PLAYER_ID"] == AB_ID)
    with open(dst / "nba_player_games_2026-27.csv", "a", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ab_row.keys()))
        w.writerow(ab_row)
    with open(dst / "game_dates.csv", "a", newline="",
              encoding="utf-8") as fh:
        csv.writer(fh).writerow([AB_GAME, "2026-10-25"])
    ab_pos = next(r for r in csv.DictReader(open(
        FULL_STORE_DIR / "positions.csv")) if r["PLAYER_ID"] == AB_ID)
    with open(dst / "positions.csv", "a", newline="",
              encoding="utf-8") as fh:
        csv.writer(fh).writerow([AB_ID, ab_pos["POSITION"]])
    store, receipt = pricing.load_store_from_dir(str(dst))
    assert receipt["status"] == "NBA_PROP_STORE_LOADED"
    return store


@artifact_test
def test_forced_resolution_both_ways_same_eligibility(runs, tmp_path):
    variants = {}
    # (i) unresolved token against the truncated store
    out, _ = pricing.phone_nba_prop_rows(
        _black_rows("Black"), now=NOW_B, store=runs["TRUNC"]["store"])
    variants["token_vs_trunc"] = out
    # (ii) force-resolved name against the truncated store
    out, _ = pricing.phone_nba_prop_rows(
        _black_rows("Anthony Black"), now=NOW_B,
        store=runs["TRUNC"]["store"])
    variants["name_vs_trunc"] = out
    # (iii) force-resolved name against the full store (what the
    # research proof actually did)
    out, _ = pricing.phone_nba_prop_rows(
        _black_rows("Anthony Black"), now=NOW_B,
        store=runs["FULL"]["store"])
    variants["name_vs_full"] = out
    # (iv) force-resolved name against a store whose history
    # (incorrectly, for a counted build) includes the slate game
    synth = _synthetic_store_with_slate_game(tmp_path)
    out, _ = pricing.phone_nba_prop_rows(
        _black_rows("Anthony Black"), now=NOW_B, store=synth)
    variants["name_vs_synth"] = out
    probe = synth.price(AB_ID, "points", 8.5, date(2026, 10, 25))
    assert probe["reason"] == "NBA_PROP_INSUFFICIENT_PRIOR_GAMES"
    assert probe["n_prior"] == 0  # the slate game is not a prior
    expected = {"token_vs_trunc": "NBA_PROP_PLAYER_NOT_IN_STORE",
                "name_vs_trunc": "NBA_PROP_PLAYER_NOT_IN_STORE",
                "name_vs_full": "NBA_PROP_INSUFFICIENT_PRIOR_GAMES",
                "name_vs_synth": "NBA_PROP_INSUFFICIENT_PRIOR_GAMES"}
    for tag, outputs in variants.items():
        assert len(outputs) == 2
        for o in outputs:
            # refused in every variant — counted eligibility (a
            # priced row) is identical: none, however the name is
            # resolved and whatever history the store carries
            assert o["status"] == "NO_MODEL_OR_MARKET", (tag, o)
            assert o["blocker"] == expected[tag], (tag, o)


# ---------- item 2: supplement path regression (deterministic) ----------
# Fixtures are SYNTHETIC (see module docstring). Fixture slate:
# season start 2026-10-21, slate date 2026-10-23; game 9001 in the
# asset, game 9002 scheduled but asset-missing -> supplemented.

FIXED_FETCHED_AT = "2026-10-23T10:00:00Z"
FIXTURE_PRICING = "2026-10-23T17:00:00Z"
ASSET_CSV = (
    "game_date,athlete_id,athlete_display_name,team_abbreviation,"
    "game_id,minutes,points,rebounds,assists,did_not_play,"
    "season_type,athlete_position_abbreviation\n"
    "2026-10-21,101,Alpha One,AAA,9001,30,20,5,4,false,2,G\n"
    "2026-10-21,201,Beta One,BBB,9001,28,12,7,3,false,2,F\n"
).encode()
SUMMARY_9002 = {
    "boxscore": {"players": [
        {"team": {"abbreviation": "AAA"},
         "statistics": [{"labels": ["MIN", "FG", "PTS", "REB", "AST"],
                         "athletes": [
                             {"athlete": {"id": "102",
                                          "displayName": "Alpha Two",
                                          "position": {
                                              "abbreviation": "F"}},
                              "stats": ["24", "5-9", "15", "6", "2"]},
                             {"athlete": {"id": "103",
                                          "displayName": "Alpha Three",
                                          "position": {
                                              "abbreviation": "C"}},
                              "didNotPlay": True, "stats": []}]}]},
        {"team": {"abbreviation": "BBB"},
         "statistics": [{"labels": ["MIN", "FG", "PTS", "REB", "AST"],
                         "athletes": [
                             {"athlete": {"id": "202",
                                          "displayName": "Beta Two",
                                          "position": {
                                              "abbreviation": "G"}},
                              "stats": ["31", "7-12", "22", "4",
                                        "9"]}]}]},
    ]}}
SUMMARY_9002_BYTES = json.dumps(SUMMARY_9002).encode()
SCOREBOARD_21 = json.dumps({"events": [{"id": "9001"}]}).encode()
SCOREBOARD_22 = json.dumps({"events": [{"id": "9002"}]}).encode()
TEAMS_DOC = json.dumps({"sports": [{"leagues": [{"teams": [
    {"team": {"id": "1"}}, {"team": {"id": "2"}}]}]}]}).encode()
ROSTER_1 = json.dumps({"athletes": [
    {"id": "101", "position": {"abbreviation": "G"}},
    {"id": "102", "position": {"abbreviation": "F"}},
    {"id": "103", "position": {"abbreviation": "C"}}]}).encode()
ROSTER_2 = json.dumps({"athletes": [
    {"id": "201", "position": {"abbreviation": "F"}},
    {"id": "202", "position": {"abbreviation": "G"}}]}).encode()


def _fixture_fetch(summary_mode="ok"):
    def fake(url):
        if url == slate_build.ASSET_URL:
            return ASSET_CSV, FIXED_FETCHED_AT
        if url == slate_build.ASSET_API_URL:
            return b'{"assets": []}', FIXED_FETCHED_AT
        if url == slate_build.SCOREBOARD_URL.format(yyyymmdd="20261021"):
            return SCOREBOARD_21, FIXED_FETCHED_AT
        if url == slate_build.SCOREBOARD_URL.format(yyyymmdd="20261022"):
            return SCOREBOARD_22, FIXED_FETCHED_AT
        if url == slate_build.SUMMARY_URL.format(event_id="9002"):
            if summary_mode == "missing":
                raise OSError("fixture: summary fetch failed")
            if summary_mode == "malformed":
                return b"{not json", FIXED_FETCHED_AT
            if summary_mode == "bad_shape":
                return b"{}", FIXED_FETCHED_AT
            return SUMMARY_9002_BYTES, FIXED_FETCHED_AT
        if url == slate_build.TEAMS_URL:
            return TEAMS_DOC, FIXED_FETCHED_AT
        if url == slate_build.ROSTER_URL.format(team_id="1"):
            return ROSTER_1, FIXED_FETCHED_AT
        if url == slate_build.ROSTER_URL.format(team_id="2"):
            return ROSTER_2, FIXED_FETCHED_AT
        raise AssertionError(f"unexpected URL in fixture fetch: {url}")
    return fake


def _run_fixture_build(tmp_path, monkeypatch, summary_mode="ok"):
    out = tmp_path / "build"
    monkeypatch.setattr(slate_build, "fetch",
                        _fixture_fetch(summary_mode))
    monkeypatch.setattr(sys, "argv", [
        "slate_build.py", "--out-dir", str(out),
        "--slate-date", "2026-10-23", "--pricing-time", FIXTURE_PRICING,
        "--mode", "research", "--season-start", "2026-10-21"])
    assert slate_build.main() == 0
    return out


def test_supplement_fills_asset_missing_game(tmp_path, monkeypatch):
    out = _run_fixture_build(tmp_path, monkeypatch)
    m = json.loads((out / "build_manifest.json").read_text(
        encoding="utf-8"))
    assert m["supplement_failures"] == []
    assert len(m["supplements"]) == 1
    entry = m["supplements"][0]
    assert entry["kind"] == "summary_supplement"
    assert entry["event_id"] == "9002" and entry["date"] == "2026-10-22"
    assert entry["url"] == slate_build.SUMMARY_URL.format(event_id="9002")
    assert entry["fetched_at"] == FIXED_FETCHED_AT
    assert entry["bytes"] == len(SUMMARY_9002_BYTES)
    assert entry["sha256"] == hashlib.sha256(
        SUMMARY_9002_BYTES).hexdigest()
    assert entry["raw_path"] == "raw/summary_9002.json"
    assert entry in m["archive"]
    assert (out / "raw" / "summary_9002.json").read_bytes() == \
        SUMMARY_9002_BYTES
    with open(out / "nba_player_games_2026-27.csv", newline="",
              encoding="utf-8") as fh:
        rows = {r["PLAYER_ID"]: r for r in csv.DictReader(fh)
                if r["GAME_ID"] == "9002"}
    assert set(rows) == {"102", "103", "202"}
    assert (rows["102"]["PLAYER_NAME"], rows["102"]["TEAM_ABBREVIATION"],
            rows["102"]["MIN"], rows["102"]["PTS"], rows["102"]["REB"],
            rows["102"]["AST"]) == ("Alpha Two", "AAA", "24", "15",
                                    "6", "2")
    assert (rows["103"]["MIN"], rows["103"]["PTS"], rows["103"]["REB"],
            rows["103"]["AST"]) == ("0", "0", "0", "0")
    assert (rows["202"]["MIN"], rows["202"]["PTS"]) == ("31", "22")
    dates = {r["GAME_ID"]: r["GAME_DATE"] for r in csv.DictReader(
        open(out / "game_dates.csv", newline="", encoding="utf-8"))}
    assert dates == {"9001": "2026-10-21", "9002": "2026-10-22"}
    assert m["checks"]["S2"]["verdict"] == "PASS"
    assert m["checks"]["S4"]["verdict"] == "PASS"
    assert m["checks"]["S3_gate"]["verdict"] == "PASS"
    assert m["classification"] == "RESEARCH_ONLY"
    v = slate_build.verify_slate_build(
        str(out), slate_date="2026-10-23", pricing_time=FIXTURE_PRICING)
    assert v["reasons"] == ["MODE_NOT_COUNTED"]


def _assert_supplement_failure_closed(out, mode):
    m = json.loads((out / "build_manifest.json").read_text(
        encoding="utf-8"))
    assert len(m["supplement_failures"]) == 1
    f = m["supplement_failures"][0]
    assert f["event_id"] == "9002" and f["status"] == "SUPPLEMENT_FAILED"
    with open(out / "nba_player_games_2026-27.csv", newline="",
              encoding="utf-8") as fh:
        assert all(r["GAME_ID"] != "9002" for r in csv.DictReader(fh))
    dates = {r["GAME_ID"] for r in csv.DictReader(
        open(out / "game_dates.csv", newline="", encoding="utf-8"))}
    assert "9002" not in dates
    assert m["checks"]["S2"]["verdict"] == "FAIL"
    assert m["checks"]["S2"]["mismatches"]["9002"] == [None, "2026-10-22"]
    assert m["checks"]["S3_gate"]["verdict"] == "FAIL_CLOSED"
    assert m["classification"] == "RESEARCH_ONLY"
    v = slate_build.verify_slate_build(
        str(out), slate_date="2026-10-23", pricing_time=FIXTURE_PRICING)
    assert v["classification"] == "RESEARCH_ONLY"
    assert "POSITIONS_GATE_RECORDED_FAIL" in v["reasons"]
    if mode == "missing":
        assert not (out / "raw" / "summary_9002.json").exists()
        assert m["supplements"] == []
    else:
        assert (out / "raw" / "summary_9002.json").exists()
        arch = [e for e in m["archive"]
                if e.get("raw_path") == "raw/summary_9002.json"]
        assert len(arch) == 1
        assert arch[0]["content_status"] == "UNPARSEABLE_SUPPLEMENT"


def test_supplement_missing_forces_research_only(tmp_path, monkeypatch):
    out = _run_fixture_build(tmp_path, monkeypatch, "missing")
    _assert_supplement_failure_closed(out, "missing")


def test_supplement_malformed_forces_research_only(tmp_path, monkeypatch):
    out = _run_fixture_build(tmp_path, monkeypatch, "malformed")
    _assert_supplement_failure_closed(out, "malformed")


def test_supplement_bad_shape_forces_research_only(tmp_path, monkeypatch):
    out = _run_fixture_build(tmp_path, monkeypatch, "bad_shape")
    _assert_supplement_failure_closed(out, "bad_shape")


def test_supplement_archive_hash_mismatch_fails_verification(
        tmp_path, monkeypatch):
    out = _run_fixture_build(tmp_path, monkeypatch)
    dst = tmp_path / "tampered"
    shutil.copytree(out, dst)
    raw = dst / "raw" / "summary_9002.json"
    raw.write_bytes(raw.read_bytes() + b" ")
    v = slate_build.verify_slate_build(
        str(dst), slate_date="2026-10-23", pricing_time=FIXTURE_PRICING)
    assert v["classification"] == "RESEARCH_ONLY"
    assert "RAW_HASH_MISMATCH:raw/summary_9002.json" in v["reasons"] or \
        "RAW_SIZE_MISMATCH:raw/summary_9002.json" in v["reasons"]
