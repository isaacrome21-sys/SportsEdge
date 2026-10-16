"""RED (t212, #2357 owner redesign): fixture identity is the statsapi gamePk,
grounded in a hash-pinned raw index.  Ungrounded rows go to a refusal ledger
(excluded, load fails closed only past a threshold).  Time windows are no
longer a load gate."""
from datetime import timedelta

import pytest

from sportsedge.research.mlb_total_offense_defense_challenger import (
    FixtureIndex, MLBTotalCandidateError, load_grounded_finals, prequential_backtest)
from mlb_statsapi_fixture_helpers import pinned_index, raw_game, row_for
from test_mlb_total_offense_defense_challenger import BASE, sample_games

DAY = BASE + timedelta(days=500)


def _base():
    games = sample_games()
    docs = [raw_game(700000 + i, g["away_id"], g["home_id"],
                     g["event_start_ts"].replace("+00:00", "Z"),
                     away_runs=g["away_runs"], home_runs=g["home_runs"]) for i, g in enumerate(games)]
    rows = [dict(g, game_pk=700000 + i) for i, g in enumerate(games)]
    return docs, rows


def _load(extra_docs, extra_rows):
    docs, rows = _base()
    return load_grounded_finals(rows + extra_rows, fixture_index=pinned_index(docs + extra_docs))


def _ok(extra_docs, extra_rows=None):
    extra_rows = [row_for(d) for d in extra_docs] if extra_rows is None else extra_rows
    out = _load(extra_docs, extra_rows)
    assert out.ledger == []
    assert len(out.records) == 200 + len(extra_rows)
    return out


def test_resumed_game_then_regular_game_same_day_passes():
    resumed = raw_game(800001, "NYY", "BOS", DAY, resumeDate=DAY.date().isoformat(),
                       resumedFrom="2026-05-01")
    regular = raw_game(800002, "NYY", "BOS", DAY + timedelta(minutes=70))
    _ok([resumed, regular])


def test_resumed_game_then_different_opponent_passes():
    resumed = raw_game(800011, "NYY", "BOS", DAY, resumedFrom="2026-05-01")
    other = raw_game(800012, "TOR", "BOS", DAY + timedelta(minutes=95))
    _ok([resumed, other])


def test_flipped_makeup_doubleheader_passes():
    g1 = raw_game(800021, "NYY", "BOS", DAY, game_number=1, double_header="S")
    g2 = raw_game(800022, "BOS", "NYY", DAY + timedelta(minutes=150), game_number=2, double_header="S")
    _ok([g1, g2])


@pytest.mark.parametrize("gap", [175, 165, 179, 120])
def test_quick_doubleheaders_pass(gap):
    g1 = raw_game(800031, "NYY", "BOS", DAY, game_number=1, double_header="Y")
    g2 = raw_game(800032, "NYY", "BOS", DAY + timedelta(minutes=gap), game_number=2, double_header="Y")
    _ok([g1, g2])


@pytest.mark.parametrize("forge", [{"gameNumber": 2}, {"doubleHeader": "Y"},
                                   {"game_duration_minutes": 140},
                                   {"game_end_ts": "2027-05-16T20:20:00+00:00"},
                                   {"away_runs": 9}, {"home_id": "TOR"},
                                   {"event_start_ts": "2027-05-16T21:00:00+00:00"}])
def test_forged_fields_not_matching_raw_record_are_unverified(forge):
    doc = raw_game(800041, "NYY", "BOS", DAY)
    out = _load([doc], [row_for(doc, **forge)])
    assert len(out.records) == 200
    assert [e["status"] for e in out.ledger] == ["UNVERIFIED_FIXTURE_IDENTITY"]
    assert out.ledger[0]["event_id"] == "pk-800041"


def test_row_without_game_pk_or_unknown_pk_is_unverified_not_crash():
    doc = raw_game(800051, "NYY", "BOS", DAY)
    rows = [row_for(doc, game_pk=None), row_for(doc, event_id="ghost", game_pk=123)]
    out = _load([doc], rows)
    assert len(out.records) == 200
    assert sorted(e["reason"].split(":")[0] for e in out.ledger) == ["GAME_PK_MISSING", "GAME_PK_NOT_IN_INDEX"]


def test_same_game_pk_twice_is_duplicate_and_excluded():
    doc = raw_game(800061, "NYY", "BOS", DAY)
    rows = [row_for(doc), row_for(doc, event_id="relist")]
    out = _load([doc], rows)
    assert len(out.records) == 200
    assert {e["reason"].split(":")[0] for e in out.ledger} == {"DUPLICATE_FIXTURE_IDENTITY"}


def test_resume_linked_game_pks_are_one_game():
    original = raw_game(800071, "NYY", "BOS", DAY)
    resumed = raw_game(800072, "NYY", "BOS", DAY + timedelta(days=1), resumedFromGamePk=800071)
    out = _load([original, resumed], [row_for(original), row_for(resumed)])
    assert len(out.records) == 200
    assert {e["reason"].split(":")[0] for e in out.ledger} == {"DUPLICATE_FIXTURE_IDENTITY"}


def test_ledger_over_threshold_fails_closed():
    doc = raw_game(800081, "NYY", "BOS", DAY)
    rows = [row_for(doc, event_id=f"x{i}", game_pk=None) for i in range(6)]
    with pytest.raises(MLBTotalCandidateError, match="UNVERIFIED_FIXTURE_LEDGER_EXCEEDED"):
        _load([doc], rows)  # config: 5 rows


def test_default_threshold_comes_from_config():
    import json
    from pathlib import Path
    cfg = json.loads(Path("config/research/mlb_challenger_fixture_identity_v1.json").read_text())
    assert cfg["identity"] == "STATSAPI_GAMEPK_RAW_RECORD"
    assert isinstance(cfg["max_unverified_rows"], int)


def test_index_hash_pinned():
    doc = raw_game(800091, "NYY", "BOS", DAY)
    with pytest.raises(MLBTotalCandidateError, match="FIXTURE_INDEX_NOT_TRUSTED"):
        FixtureIndex.from_statsapi_documents([doc])


def test_ungrounded_rows_excluded_from_backtest_and_reported():
    docs, rows = _base()
    rows[195] = dict(rows[195], game_pk=None)
    report = prequential_backtest(rows, holdout_from=(BASE + timedelta(days=180)).isoformat(),
                                  fixture_index=pinned_index(docs))
    assert report["n_distinct_games"] == 19
    assert report["n_unverified_fixture_identity"] == 1
    assert report["refusal_ledger"][0]["event_id"] == "game-195"


def test_index_from_stored_raw_dir(tmp_path):
    import json
    docs = [raw_game(800101, "NYY", "BOS", DAY), raw_game(800102, "TOR", "BAL", DAY)]
    for i, d in enumerate(docs):
        (tmp_path / f"game_{i}.json").write_text(json.dumps(d))
    from mlb_statsapi_fixture_helpers import trust
    trust(docs)
    idx = FixtureIndex.from_raw_dir(tmp_path)
    assert idx.has(800101) and idx.has(800102)
