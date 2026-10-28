"""Regression: a REAL doubleheader in a batter's prior-30 window must price,
and the leak/duplicate gate must stay fail-closed.

Data provenance (tests/fixtures/mlb_batter_kwan_dh_20260904.json): verbatim
excerpts of real MLB StatsAPI responses fetched 2026-10-27 — nothing
synthesized. Steven Kwan (id 680757) really played both games of the
Detroit Tigers @ Cleveland Guardians doubleheader on 2026-09-04:
gamePk 824424 (start 2026-09-04T18:10:00Z) and gamePk 824387 (start
2026-09-04T23:15:00Z). Both games sit inside his prior-30 window for the
real 2026-10-19 ALCS Game 6 fixture (Cleveland @ Tampa Bay, gamePk 849815),
which is exactly the configuration that produced 99
HISTORY_LEAK_OR_DUPLICATE_GAME refusals on 2026-10-19 under the pre-fix
date-stamp window (see research/mlb_batter_doubleheader_rerun_20261027/).

The pre-fix collector stamped both doubleheader games at date midnight, so
the timestamp-distinctness gate read two legitimate games as one duplicated
game. The fixed path keys duplicate detection on game identity
(prior_game_ids) and verifies each doubleheader game's real start.
"""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from sportsedge.mlb_public_batter_history import MLBBatterPublicSource
from sportsedge.research_model_adapters import mlb_batter_to_bridge_rows

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "mlb_batter_kwan_dh_20260904.json")
    .read_text())
NOW = "2026-10-19T22:10:00Z"          # the real board capture instant (17:10 CT)
KICKOFF = "2026-10-20T00:08:00Z"      # real ALCS G6 first pitch
DH_IDS = {"824387", "824424"}
DH_STARTS = {"2026-09-04T18:10:00+00:00", "2026-09-04T23:15:00+00:00"}


def getter(url):
    p = urlparse(url)
    q = parse_qs(p.query)
    if p.path.endswith("/schedule"):
        day = q.get("date", [""])[0]
        key = f"schedule_{day}"
        if key in FIXTURE:
            return FIXTURE[key]
        return {"dates": []}
    if p.path.endswith("/boxscore"):
        return FIXTURE["boxscore_849815"]
    if p.path.endswith("/stats"):
        return FIXTURE["gamelog_680757"]
    raise AssertionError(url)


def _prior():
    return MLBBatterPublicSource(getter=getter).prior_games(
        away="Cleveland Guardians", home="Tampa Bay Rays",
        player_name="Steven Kwan", owner_kickoff=KICKOFF, as_of=NOW)


def _bridge(v, **overrides):
    kw = dict(
        game_id=v["game_id"], player_id=v["batter_id"], market="BATTER_HITS",
        side="OVER", line=0.5, features=v["features"],
        prior_game_times_utc=v["prior_game_times_utc"],
        prior_game_ids=v.get("prior_game_ids"),
        source_as_of_utc=v["source_as_of_utc"], as_of_utc=NOW,
        kickoff_utc=v["kickoff_utc"], home_team="Tampa Bay Rays",
        away_team="Cleveland Guardians")
    kw.update(overrides)
    return mlb_batter_to_bridge_rows(**kw)[0]


def test_real_doubleheader_both_games_kept_with_real_starts():
    v = _prior()
    assert v["prior_game_count"] == 30
    ids = v["prior_game_ids"]
    assert len(set(ids)) == len(ids) == 30
    # Both real doubleheader games survive selection, keyed by gamePk.
    assert DH_IDS <= set(ids)
    stamps = {t for t, g in zip(v["prior_game_times_utc"], ids) if g in DH_IDS}
    # The stamps are the games' real verified starts, not date midnight.
    assert stamps == DH_STARTS


def test_real_doubleheader_window_prices():
    row = _bridge(_prior())
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" not in str(row)
    assert row.get("status") == "PRICED_RESEARCH"


def test_pre_fix_midnight_stamps_would_still_refuse():
    # The pre-fix shape: doubleheader games stamped at date midnight and no
    # game identity supplied. The gate must refuse that shape — the fix is
    # the identity-keyed verified path above, not a weaker gate.
    v = _prior()
    old = [t[:10] + "T00:00:00+00:00" for t in v["prior_game_times_utc"]]
    row = _bridge(v, prior_game_times_utc=old, prior_game_ids=None)
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(row)


def test_true_duplicate_game_id_still_refuses():
    v = _prior()
    ids = list(v["prior_game_ids"])
    ids[1] = ids[0]  # one real game counted twice, under two real stamps
    row = _bridge(v, prior_game_ids=ids)
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(row)


def test_leak_arm_still_refuses_future_prior_game():
    v = _prior()
    times = list(v["prior_game_times_utc"])
    times[0] = "2026-10-19T22:30:00+00:00"  # after the source as-of (22:10Z)
    row = _bridge(v, prior_game_times_utc=times)
    assert "HISTORY_LEAK_OR_DUPLICATE_GAME" in str(row)
