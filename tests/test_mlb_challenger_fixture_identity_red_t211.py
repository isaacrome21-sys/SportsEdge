"""RED (t211u, #2357): one real fixture under two event ids must not be
double counted (history or prequential trials)."""
from datetime import timedelta

from mlb_statsapi_fixture_helpers import trusted_manifest  # noqa: F401  (autouse)
import pytest

from sportsedge.research.mlb_total_offense_defense_challenger import (
    MLBTotalCandidateError, parse_finals, predict_total, prequential_backtest)
from test_mlb_total_offense_defense_challenger import BASE, index_for, sample_games, target


def _dup(games, i=5, **chg):
    row = dict(games[i], event_id=f"dup-of-{i}")
    row.update(chg)
    return games + [row]


def test_same_fixture_different_event_id_refused():
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(_dup(sample_games()))


def test_same_fixture_case_or_space_variant_team_ids_refused():
    g = sample_games()
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(_dup(g, i=4, away_id=" a ", home_id="b"))


def test_team_in_two_games_at_same_start_refused():
    g = sample_games()
    row = dict(g[4], event_id="clash", away_id="A", home_id="Z")
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(g + [row])


def test_backtest_excludes_duplicate_fixture(tmp_path, monkeypatch):
    # t212 redesign: a re-listed gamePk is excluded (both copies) and ledgered,
    # never double counted; the load fails closed only past the threshold.
    report = prequential_backtest(_dup(sample_games(), i=190),
                                  holdout_from=(BASE + timedelta(days=180)).isoformat(),
                                  fixture_index=index_for(sample_games()))
    assert report["n_distinct_games"] == 19
    assert {e["reason"].split(":")[0] for e in report["refusal_ledger"]} == {"DUPLICATE_FIXTURE_IDENTITY"}
    import json
    import sportsedge.research.mlb_total_offense_defense_challenger as ch
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"identity": "STATSAPI_GAMEPK_RAW_RECORD",
                               "max_unverified_rows": 1, "max_unverified_fraction": 0.01}))
    from mlb_statsapi_fixture_helpers import use_config
    use_config(cfg)
    with pytest.raises(MLBTotalCandidateError, match="UNVERIFIED_FIXTURE_LEDGER_EXCEEDED"):
        prequential_backtest(_dup(sample_games(), i=190),
                             holdout_from=(BASE + timedelta(days=180)).isoformat(),
                             fixture_index=index_for(sample_games()))


def test_doubleheader_distinct_starts_still_allowed():
    g = sample_games()
    row = dict(g[4], event_id="dh2", game_pk=799004,
               event_start_ts=(BASE + timedelta(days=4, hours=5)).isoformat(),
               final_observed_ts=(BASE + timedelta(days=4, hours=9)).isoformat())
    assert len(parse_finals(g + [row])) == len(g) + 1
    predict_total(g + [row], target(), fixture_index=index_for(g + [row]))
