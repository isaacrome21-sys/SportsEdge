from copy import deepcopy
from datetime import datetime, timezone

from sportsedge.mlb_decision_settlement import settle_moneyline_decisions
from sportsedge.mlb_source import GameSnapshot


def _game(status="Final"):
    return GameSnapshot(
        game_pk=123,
        game_date="2026-08-13T23:00:00+00:00",
        status=status,
        away_id=1,
        away_name="Away",
        home_id=2,
        home_name="Home",
        away_probable_pitcher_id=None,
        away_probable_pitcher_name=None,
        home_probable_pitcher_id=None,
        home_probable_pitcher_name=None,
        retrieved_at="2026-08-14T03:00:00+00:00",
        detailed_status="Final" if status == "Final" else "Scheduled",
    )


def _boxscore(_game_pk):
    return {
        "teams": {
            "away": {"teamStats": {"batting": {"runs": 2}}},
            "home": {"teamStats": {"batting": {"runs": 5}}},
        }
    }


def test_settlement_is_separate_and_excludes_post_first_pitch_decisions():
    ledger = {
        "run_id": "r1",
        "decisions": [
            {
                "decision_id": "d-home",
                "wager_key": "w-home",
                "run_id": "r1",
                "slate_date_ct": "2026-08-13",
                "generated_at_utc": "2026-08-13T22:59:00+00:00",
                "game_id": "123",
                "market": "MONEYLINE",
                "side": "HOME",
                "book_key": "draftkings",
                "american_odds": -120,
                "model_p": 0.60,
            },
            {
                "decision_id": "d-away",
                "wager_key": "w-away",
                "run_id": "r1",
                "slate_date_ct": "2026-08-13",
                "generated_at_utc": "2026-08-13T22:58:00+00:00",
                "game_id": "123",
                "market": "MONEYLINE",
                "side": "AWAY",
                "book_key": "draftkings",
                "american_odds": +110,
                "model_p": 0.40,
            },
            {
                "decision_id": "late",
                "generated_at_utc": "2026-08-13T23:00:00+00:00",
                "game_id": "123",
                "market": "MONEYLINE",
                "side": "HOME",
                "book_key": "draftkings",
                "american_odds": -120,
                "model_p": 0.60,
            },
        ],
    }
    before = deepcopy(ledger)
    out = settle_moneyline_decisions(
        ledger,
        [_game()],
        boxscore_fetcher=_boxscore,
        settled_at=datetime(2026, 8, 14, 4, 0, tzinfo=timezone.utc),
    )
    assert ledger == before
    assert out["settlement_count"] == 2
    rows = {r["decision_id"]: r for r in out["settlements"]}
    assert rows["d-home"]["outcome_win"] is True
    assert rows["d-away"]["outcome_win"] is False
    assert "late" not in rows


def test_nonfinal_game_never_settles():
    ledger = {
        "run_id": "r1",
        "decisions": [{
            "decision_id": "d",
            "generated_at_utc": "2026-08-13T22:00:00+00:00",
            "game_id": "123",
            "market": "MONEYLINE",
            "side": "HOME",
            "book_key": "draftkings",
            "american_odds": -120,
            "model_p": 0.60,
        }],
    }
    out = settle_moneyline_decisions(ledger, [_game(status="Preview")], boxscore_fetcher=_boxscore)
    assert out["settlement_count"] == 0
