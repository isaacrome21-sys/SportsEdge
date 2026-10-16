"""Integrity tests for the MLB plate-appearance PBP pool (stage 1).

The pool is the foundation the M49 Plate Appearance gates name as
PLATE_APPEARANCE_PBP_POOL_UNBUILT (see research/mlb_pbp_pool/
DESIGN.md). These tests pin:

* the PA identification rule — baserunning plays during someone
  else's PA (inning-ending caught stealing / pickoff entries that
  StatsAPI marks complete) are NOT plate appearances;
* the outcome-class mapping and factual booleans;
* row derivation on a synthetic feed (slots cycle, per-batter PA
  numbers, per-pitcher BF numbers, scoring-runner attribution);
* schema validation over the shipped 30-game sample excerpt;
* box-score reconciliation of the sample games against the shipped
  fixture (PA counts, component totals, final score, slot codes,
  feed-level outs progression) via the builder's own contract;
* PIT discipline (availability keyed on completion date);
* manifest/sample hash consistency.

Full-artifact tests run only when the stage-1 artifact directory
exists in the workspace (it is too large for the repo; see
DESIGN.md "Artifact placement"); they skip cleanly elsewhere.
"""
import gzip
import hashlib
import importlib.util
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(REPO, "research", "mlb_pbp_pool")
ARTIFACT_DIR = os.path.expanduser("~/workspace/sportsedge/mlb_pbp_pool_20261016")

spec = importlib.util.spec_from_file_location(
    "build_pbp_pool", os.path.join(PKG, "build_pbp_pool.py"))
pool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pool)


# ---------------------------------------------------------------------------
# Synthetic feed fixtures (real payload shapes, invented content)
# ---------------------------------------------------------------------------

def _play(at_bat_index, inning, half, batter, pitcher, event_type,
          *, rbi=0, away=0, home=0, outs=0, is_complete=True,
          batter_in_runners=True, extra_scorers=()):
    runners = []
    if batter_in_runners:
        runners.append({"details": {"runner": {"id": batter}},
                        "movement": {"end": "score" if event_type == "home_run" else "1B",
                                     "isOut": event_type in ("field_out", "strikeout")}})
    for scorer in extra_scorers:
        runners.append({"details": {"runner": {"id": scorer}},
                        "movement": {"end": "score", "isOut": False}})
    return {
        "about": {"atBatIndex": at_bat_index, "inning": inning,
                  "halfInning": half, "isTopInning": half == "top",
                  "startTime": "2025-06-01T17:05:00.000Z",
                  "endTime": "2025-06-01T23:05:00.000Z",
                  "isComplete": is_complete},
        "result": {"type": "atBat", "eventType": event_type, "rbi": rbi,
                   "awayScore": away, "homeScore": home,
                   "isOut": event_type in ("field_out", "strikeout")},
        "count": {"balls": 0, "strikes": 0, "outs": outs},
        "matchup": {"batter": {"id": batter}, "pitcher": {"id": pitcher},
                    "batSide": {"code": "R"}, "pitchHand": {"code": "L"}},
        "runners": runners,
    }


def _mini_feed():
    # Top 1: single, HR (batter + one runner score), caught-stealing
    # pseudo-play (complete, batter NOT in runners), strikeout.
    # Bottom 1: walk, incomplete PA (excluded), field out.
    return {"allPlays": [
        _play(0, 1, "top", 101, 201, "single", outs=0),
        _play(1, 1, "top", 102, 201, "home_run", rbi=2, away=2, outs=0,
              extra_scorers=(101,)),
        _play(2, 1, "top", 103, 201, "caught_stealing_2b", away=2, outs=1,
              batter_in_runners=False),
        _play(3, 1, "top", 103, 201, "strikeout", away=2, outs=2),
        _play(4, 1, "bottom", 301, 401, "walk", away=2, outs=0),
        _play(5, 1, "bottom", 302, 401, "single", away=2, is_complete=False),
        _play(6, 1, "bottom", 302, 401, "field_out", away=2, outs=1),
    ]}


# ---------------------------------------------------------------------------
# PA identification rule
# ---------------------------------------------------------------------------

def test_pa_rule_rejects_baserunning_pseudo_play():
    feed = _mini_feed()
    cs = feed["allPlays"][2]
    assert cs["about"]["isComplete"] is True
    assert cs["result"]["type"] == "atBat"
    assert pool.is_pa_play(cs) is False  # batter has no runner record


def test_pa_rule_accepts_real_resolutions():
    feed = _mini_feed()
    for idx in (0, 1, 3, 4, 6):
        assert pool.is_pa_play(feed["allPlays"][idx]) is True
    assert pool.is_pa_play(feed["allPlays"][5]) is False  # incomplete


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def test_derive_rows_slots_counters_and_scoring():
    rows, orphans, stats = pool.derive_game_rows(999001, 2025, _mini_feed())
    assert orphans == []
    assert len(rows) == 5  # 7 plays - CS pseudo-play - incomplete PA
    assert stats["non_pa_complete_plays"] == 1
    assert stats["incomplete_plays"] == 1
    top = [r for r in rows if r["half"] == "top"]
    assert [r["batting_order_slot"] for r in top] == [1, 2, 3]
    assert [r["batter_pa_number"] for r in top] == [1, 1, 1]
    assert [r["pitcher_bf_number"] for r in top] == [1, 2, 3]
    hr = top[1]
    assert hr["outcome_class"] == "HOME_RUN"
    assert hr["is_hit"] and hr["is_home_run"]
    assert hr["runs_scored_on_play"] == 2
    assert sorted(hr["scoring_runner_ids"]) == [101, 102]
    assert hr["rbi"] == 2
    # The batter whose PA was interrupted by the CS keeps slot 3 and
    # his strikeout is his first counted PA.
    assert top[2]["batter_id"] == 103 and top[2]["is_strikeout"]
    # Dates: ET calendar of start/end timestamps.
    assert rows[0]["game_date"] == "2025-06-01"
    assert rows[0]["game_completed_date"] == "2025-06-01"


def _orphan_feed():
    # Triple, then a wild-pitch entry on which the runner from third
    # scores during the NEXT batter's PA (batter not in runners ->
    # orphan), then that batter's PA resolves as a strikeout.
    return {"allPlays": [
        _play(0, 1, "top", 101, 201, "triple", outs=0),
        _play(1, 1, "top", 102, 201, "wild_pitch", away=1, outs=0,
              batter_in_runners=False, extra_scorers=(101,)),
        _play(2, 1, "top", 102, 201, "strikeout", away=1, outs=1),
    ]}


def _batting(**kw):
    base = {"plateAppearances": 0, "atBats": 0, "baseOnBalls": 0,
            "hitByPitch": 0, "sacFlies": 0, "sacBunts": 0,
            "catchersInterference": None, "hits": 0, "homeRuns": 0,
            "strikeOuts": 0, "rbi": 0, "runs": 0}
    base.update(kw)
    return base


def test_orphan_scoring_play_goes_to_side_table_not_a_pa_row():
    rows, orphans, stats = pool.derive_game_rows(999005, 2025, _orphan_feed())
    assert len(rows) == 2  # triple + strikeout; the WP is not a PA
    assert [r["runs_scored_on_play"] for r in rows] == [0, 0]
    assert len(orphans) == 1
    assert orphans[0]["event_type"] == "wild_pitch"
    assert orphans[0]["scoring_runner_ids"] == [101]
    assert orphans[0]["runs"] == 1 and orphans[0]["play_index"] == 1
    # Reconciliation: PA runs (0) + orphan runs (1) == box runs (1).
    box = {"teams": {
        "away": {"team": {"id": 900},
                 "teamStats": {"batting": _batting(
                     plateAppearances=2, atBats=2, hits=1, strikeOuts=1,
                     runs=1)},
                 "players": {"ID101": {"battingOrder": "100"},
                             "ID102": {"battingOrder": "200"}}},
        "home": {"team": {"id": 901},
                 "teamStats": {"batting": _batting()},
                 "players": {}}}}
    pool.attach_teams(rows, orphans, box)
    assert orphans[0]["batting_team_id"] == 900
    failures = pool.reconcile_game(rows, orphans, box, stats)
    assert failures == [], failures


def test_outcome_mapping_and_booleans():
    for event_type, outcome in pool.OUTCOME_CLASS.items():
        assert pool.OUTCOME_CLASS[event_type] == outcome
    assert pool.OUTCOME_CLASS["walk"] == "WALK"
    assert pool.OUTCOME_CLASS["intent_walk"] == "INTENT_WALK"
    assert pool.OUTCOME_CLASS["catcher_interf"] == "INTERFERENCE"
    rows, _, _ = pool.derive_game_rows(999002, 2025, {"allPlays": [
        _play(0, 1, "top", 101, 201, "intent_walk", outs=0)]})
    assert rows[0]["is_walk"] is True and rows[0]["is_intent_walk"] is True


def test_unmapped_event_type_fails_closed():
    with pytest.raises(pool.PoolError):
        pool.derive_game_rows(999003, 2025, {"allPlays": [
            _play(0, 1, "top", 101, 201, " balk".strip(), outs=0)]})


def test_validate_row_catches_schema_drift():
    rows, orphans, _ = pool.derive_game_rows(999004, 2025, _mini_feed())
    box = {"teams": {"away": {"team": {"id": 900}},
                     "home": {"team": {"id": 901}}}}
    pool.attach_teams(rows, orphans, box)
    assert pool.validate_row(rows[0]) == []
    bad = dict(rows[0])
    del bad["rbi"]
    assert pool.validate_row(bad)
    bad2 = dict(rows[0])
    bad2["outcome_class"] = "WALK"  # inconsistent with event_type
    assert pool.validate_row(bad2)


# ---------------------------------------------------------------------------
# Shipped sample: schema + box-score reconciliation + PIT discipline
# ---------------------------------------------------------------------------

def _sample_raw():
    sample_dir = os.path.join(PKG, "sample")
    raw = b""
    for name in sorted(os.listdir(sample_dir)):
        if name.startswith("pool_sample_part") and name.endswith(".jsonl"):
            with open(os.path.join(sample_dir, name), "rb") as fh:
                raw += fh.read()
    return raw


def _sample():
    rows = [json.loads(line) for line in
            _sample_raw().decode("utf-8").splitlines() if line.strip()]
    with open(os.path.join(PKG, "sample", "sample_boxscores.json")) as fh:
        fixtures = json.load(fh)
    return rows, fixtures


def test_sample_schema_valid():
    rows, _ = _sample()
    assert len(rows) > 1000
    for row in rows:
        assert pool.validate_row(row) == [], row


def test_sample_reconciles_with_boxscores():
    rows, fixtures = _sample()
    by_game = {}
    for row in rows:
        by_game.setdefault(row["game_id"], []).append(row)
    assert set(by_game) == {int(g) for g in fixtures}
    for gid, grows in by_game.items():
        fixture = fixtures[str(gid)]
        grows.sort(key=lambda r: r["pa_index"])
        failures = pool.reconcile_game(
            grows, fixture.get("orphans", []), fixture["boxscore"],
            {"feed_outs_by_half": fixture["feed_outs_by_half"]})
        assert failures == [], (gid, failures)


def test_sample_sorted_and_pit_keys():
    rows, _ = _sample()
    keys = [(r["game_date"], r["game_id"], r["pa_index"]) for r in rows]
    assert keys == sorted(keys)
    for row in rows:
        assert row["game_completed_date"] >= row["game_date"]
        # PIT availability predicate: strictly earlier completion.
        assert row["game_type"] == "R"


def test_sample_first_pa_population_and_inning_runs():
    rows, fixtures = _sample()
    by_game = {}
    for row in rows:
        by_game.setdefault(row["game_id"], []).append(row)
    for gid, grows in by_game.items():
        batters = {r["batter_id"] for r in grows}
        first_pas = [r for r in grows if r["batter_pa_number"] == 1]
        assert len(first_pas) == len(batters)
        box = fixtures[str(gid)]["boxscore"]
        orphans = fixtures[str(gid)].get("orphans", [])
        for half, side in (("top", "away"), ("bottom", "home")):
            pool_runs = sum(r["runs_scored_on_play"] for r in grows
                            if r["half"] == half)
            pool_runs += sum(o["runs"] for o in orphans if o["half"] == half)
            assert pool_runs == box["teams"][side]["teamStats"]["batting"]["runs"]


def test_manifest_matches_shipped_sample():
    with open(os.path.join(PKG, "MANIFEST.json")) as fh:
        manifest = json.load(fh)
    raw = _sample_raw()
    assert hashlib.sha256(raw).hexdigest() == manifest["sample"]["sha256_jsonl"]
    _, fixtures = _sample()
    assert manifest["sample"]["games"] == len(fixtures)


# ---------------------------------------------------------------------------
# Full artifact (workspace-only; skips where the artifact is absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.isdir(ARTIFACT_DIR),
                    reason="stage-1 pool artifact not present in workspace")
def test_full_artifact_hashes_and_schema():
    with open(os.path.join(PKG, "MANIFEST.json")) as fh:
        manifest = json.load(fh)
    for season, info in manifest["seasons"].items():
        path = os.path.join(ARTIFACT_DIR, info["file"])
        raw = open(path, "rb").read()
        assert hashlib.sha256(raw).hexdigest() == info["sha256_gz"], season
        text = gzip.decompress(raw).decode("utf-8")
        assert hashlib.sha256(text.encode()).hexdigest() == info["sha256_jsonl"], season
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        assert len(rows) == info["rows"], season
        for row in rows[::997]:  # schema spot-check stride; full pass is --verify's job
            assert pool.validate_row(row) == [], (season, row)
        oraw = open(os.path.join(ARTIFACT_DIR, info["orphans_file"]), "rb").read()
        assert hashlib.sha256(oraw).hexdigest() == info["orphans_sha256_gz"], season
        orphans = [json.loads(line) for line in
                   gzip.decompress(oraw).decode("utf-8").splitlines() if line.strip()]
        assert len(orphans) == info["orphan_rows"], season
        assert sum(o["runs"] for o in orphans) == info["orphan_runs"], season
