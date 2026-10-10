"""2027 prep (#1482): committed 2026 league_short prior pools (#1977 / #1978) are valid and only read for 2027 games."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sportsedge import mlb_pitcher_prior as P

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "config" / "mlb_pitcher_prior_league_short_2026.json"
EXT = ROOT / "config" / "mlb_pitcher_prior_league_short_ext_2026.json"


def test_2026_artifacts_are_canonical_and_internally_consistent():
    for path in (BASE, EXT):
        text = path.read_text()
        raw = json.loads(text)
        assert text == json.dumps(raw, indent=2) + "\n"
        assert raw["season"] == 2026 and raw["pool"] == "league_short"
        assert all(sum(v.values()) == raw["starts"] for v in raw["counts"].values())
    base, ext = json.loads(BASE.read_text()), json.loads(EXT.read_text())
    assert ext["starts"] == base["starts"]
    assert all(ext["counts"][k] == base["counts"][k] for k in ("outs", "strikeouts"))


def test_2026_pools_are_used_for_2027_games_only():
    for market in sorted(P.FALLBACK_MARKETS):
        assert P.prior_for(date(2027, 4, 1), market=market)["season"] == 2026
        assert P.prior_for(date(2026, 10, 12), market=market)["season"] == 2025
