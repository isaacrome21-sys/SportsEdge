from datetime import date, datetime, timezone

from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.mlb_joint_mode_bridge import build_canonical_feature_row


class ContextSource:
    def __init__(self):
        self.retrieved_at = datetime(2026, 10, 4, 23, 0, tzinfo=timezone.utc)
        self.calls = []

    def feature_row(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "game_pk": kwargs["game_pk"],
            "market": kwargs["market"],
            "entity_id": kwargs["entity_id"],
            "team_id": kwargs["team_id"],
            "retrieved_at": self.retrieved_at.isoformat(),
            "asof": self.retrieved_at.isoformat(),
            "source": "MLB_STATSAPI_CHRONOLOGICAL_GAMELOG",
            "source_subset_hash": "a" * 64,
            "joint_feature_version": "mlb_pitcher_joint_history_lineup_k_v1",
            "features": {
                "history_pool": [
                    {
                        "strikeouts": 6,
                        "outs": 18,
                        "earned_runs": 2,
                        "hits_allowed": 5,
                        "walks_allowed": 1,
                    }
                ] * 5,
                "opp_k_adjustment": {
                    "market": "PITCHER_K",
                    "beta": 1.0,
                    "target_rel": 1.1,
                    "history_rel": [1.0] * 5,
                    "lineup_k_adjustment": {
                        "W": 200.0,
                        "gamma": 0.5,
                        "target_deviation": 1.08,
                        "history_deviation": [1.0] * 5,
                        "validated_in": "#1540",
                    },
                },
            },
        }


def _lineup(team_id, side, start):
    return TeamLineup(
        team_id=team_id,
        side=side,
        player_ids=tuple(range(start, start + 9)),
        batting_slots=tuple(range(1, 10)),
        confirmed=True,
    )


def _game():
    return LiveGame(
        game_pk=777,
        away_team_id=10,
        home_team_id=20,
        away_probable_pitcher_id=101,
        home_probable_pitcher_id=202,
        away_lineup=_lineup(10, "away", 1000),
        home_lineup=_lineup(20, "home", 2000),
        venue_id=1,
        official_date="2026-10-04",
        status="Preview",
    )


def _quote(entity_id):
    return {
        "game_id": "777",
        "period": "FG",
        "market": "PITCHER_K",
        "entity_id": str(entity_id),
        "line": 5.5,
        "side": "OVER",
        "american_odds": -110,
        "book_key": "draftkings",
        "sportsbook": "DraftKings",
        "is_alternate": False,
        "raw_market_name": "Pitcher Strikeouts",
        "retrieved_at": "2026-10-04T22:59:00+00:00",
        "ttl_seconds": 300,
        "offer_id": "k-over",
    }


def test_single_pitcher_bridge_uses_native_context_feature_builder():
    source = ContextSource()
    row = build_canonical_feature_row(
        game=_game(),
        quote=_quote(101),
        source=source,
        target_date=date(2026, 10, 4),
    )

    assert len(source.calls) == 1
    call = source.calls[0]
    assert call["player_id"] == 101
    assert call["team_id"] == 10
    assert call["away_team_id"] == 10
    assert call["home_team_id"] == 20
    assert row["feature_source_hash"] == "a" * 64
    assert row["features"]["opp_k_adjustment"]["lineup_k_adjustment"]["gamma"] == 0.5
    assert row["joint_feature_version"] == "mlb_pitcher_joint_history_lineup_k_v1"


def test_home_pitcher_bridge_binds_home_team_identity():
    source = ContextSource()
    row = build_canonical_feature_row(
        game=_game(),
        quote=_quote(202),
        source=source,
        target_date=date(2026, 10, 4),
    )

    assert source.calls[0]["team_id"] == 20
    assert row["team_id"] == 20
