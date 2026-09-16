from datetime import datetime, timedelta, timezone

from scripts.build_mlb_moneyline_preseason_evidence import Game
from scripts.build_mlb_moneyline_rolling_candidate import build_chronological_examples


def _games():
    rows = []
    start = datetime(2022, 3, 1, 18, 0, tzinfo=timezone.utc)
    pk = 1
    # Alternate home/away so both teams accumulate enough market-blind history.
    for season in (2022, 2023):
        for i in range(140):
            home = 10 if i % 2 == 0 else 20
            away = 20 if home == 10 else 10
            rows.append(Game(
                season, pk, start, home, away,
                5 if home == 10 else 3,
                2 if away == 20 else 4,
            ))
            pk += 1
            start += timedelta(days=1)
    return rows


def test_rolling_candidate_uses_strict_48h_development_embargo():
    rows = build_chronological_examples(_games())
    assert rows
    for row in rows:
        cutoff = datetime.fromisoformat(row["development_feature_cutoff_ts"])
        event = datetime.fromisoformat(row["event_start_ts"])
        assert cutoff < event
        assert (event - cutoff) == timedelta(hours=48)
        assert "odds" not in row
        assert "implied_probability" not in row
