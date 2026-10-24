"""t278 review follow-ups: new CFB watch statuses and unknown statuses are never picks;
tracker summary refuses to report numbers when the audit log and records diverge."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge import phone_display
from sportsedge.sports.cfb.forward_clv_tracker import ForwardTracker, TrackerError

NEW_WATCH = ("WATCH_CFB_MARKET_ONLY_NO_VALIDATED_WEIGHT", "WATCH_UNVALIDATED_INJURY_WEATHER_ADJ")


@pytest.mark.parametrize("status", NEW_WATCH + ("SOMETHING_UNKNOWN", "", None, "PLAY", "VALIDATED_EDGE"))
def test_is_pick_status_fails_closed(status):
    assert phone_display.is_pick_status(status) is False


def test_is_pick_status_only_canonical_candidates():
    for s in phone_display.CANDIDATE_STATUSES:
        assert phone_display.is_pick_status(s) is True


def _row(status):
    return {"status": status, "estimate_p": 0.6, "ev_per_dollar": 0.1, "odds_american": 110,
            "quote_freshness": {"code": "QUOTE_FRESH_UNDER_180S", "age_seconds": 10, "max_age_seconds": 180},
            "pricing_provenance": {"lane": "INDEPENDENT"}, "context_notes": []}


@pytest.mark.parametrize("status", NEW_WATCH + ("SOMETHING_UNKNOWN",))
def test_disposition_never_play_for_watch_or_unknown(status):
    label, _, _ = phone_display._disposition(_row(status), 0.02)
    assert label in {"WATCH", "BLOCKED", "PASS", "REFRESH REQUIRED"}


NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=2)


def _settled():
    t = ForwardTracker()
    t.add(dict(record_id="r1", market="OPP:SPREAD", side="HOME", line=-3.5, odds=-110,
               created_at=NOW.isoformat(), captured_at=NOW.isoformat(), kickoff=KO.isoformat()), now=NOW)
    t.close("r1", closing_odds=-120, closing_line=-3.5, now=KO + timedelta(minutes=1))
    t.settle("r1", result="WIN", now=KO + timedelta(hours=4))
    return t


def test_summary_raises_when_audit_inconsistent():
    t = _settled()
    t._records["r1"]["result"] = "LOSS"  # white-box tamper
    with pytest.raises(TrackerError, match="AUDIT_INCONSISTENT"):
        t.summary()


def test_summary_numbers_when_consistent():
    s = _settled().summary()
    assert s["audit_consistent"] is True and s["roi_units"] == pytest.approx(100 / 110)


# --- t278 MEDIUM: every engine-status pick decision routes through is_pick_status ---
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Places allowed to name candidate statuses directly: the definitions themselves,
# provenance gating (stricter superset that only ADDS holds), and counters/labels
# that never decide a pick. Any new file deciding picks by literal must route via
# phone_display.is_pick_status or be reviewed and added here.
EXEMPT = {
    "sportsedge/phone_display.py": "defines CANDIDATE_STATUSES / is_pick_status",
    "artifacts/free_models.py": "defines POSITIVE_EV_STATUS emitted by the engine",
    "sportsedge/pricing_provenance.py": "PLAY_SURFACE_STATUSES only adds provenance holds",
    "sportsedge/mlb_phone_full_board.py": "display-status list for MLB research board labels",
    "scripts/run_it_all.py": "counts research rows; never selects picks",
    "scripts/free_models_phone_issue.py": "exclusion counter for issue text",
    # Emitters / demoters: they SET a candidate status or only DOWNGRADE one; none selects picks.
    "sportsedge/research_three_sport_bridge.py": "emits RESEARCH_CANDIDATE_NOT_VALIDATED",
    "sportsedge/nba_phone_prop_pricing.py": "emits RESEARCH_CANDIDATE_NOT_VALIDATED",
    "sportsedge/team_half_pricing.py": "demotes period candidates",
    "sportsedge/mlb_phone_batter_pricing.py": "demotes unverified-lineup candidates",
    "sportsedge/nfl_phone_player_pricing.py": "demotes candidates",
    "sportsedge/cfb_phone_player_pricing.py": "demotes candidates",
    "sportsedge/live_run_it.py": "separate LIVE_* status vocabulary",
    "sportsedge/backtest/report.py": "status taxonomy for backtest reporting",
    "sportsedge/forward_validation/core.py": "forward-validation ledger classification",
    "sportsedge/forward_validation/nba_full_board_ledger.py": "forward-validation ledger classification",
}


def test_no_renderer_decides_picks_by_status_literal_outside_is_pick_status():
    offenders = []
    for base in ("sportsedge", "artifacts", "scripts"):
        for p in (ROOT / base).rglob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            if rel in EXEMPT:
                continue
            src = p.read_text(errors="ignore")
            if re.search(r"RESEARCH_POSITIVE_EV_UNVALIDATED|RESEARCH_CANDIDATE_NOT_VALIDATED|"
                         r"\bCANDIDATE_STATUSES\b|==\s*POSITIVE_EV_STATUS", src):
                offenders.append(rel)
    assert offenders == []


def test_engine_and_phone_display_route_through_is_pick_status():
    fm = (ROOT / "artifacts/free_models.py").read_text()
    assert "== POSITIVE_EV_STATUS and is_play_eligible" not in fm
    assert "is_pick_status(r[\"status\"])" in fm
    pd = (ROOT / "sportsedge/phone_display.py").read_text()
    body = pd.split("def is_pick_status", 1)[1]
    assert "status in CANDIDATE_STATUSES" not in body.split("\ndef ", 1)[1]
    assert "CANDIDATE_STATUSES |" not in pd
    assert pd.count("is_pick_status(status)") >= 2
    rf = (ROOT / "artifacts/run_it_full.py").read_text()
    assert 'r.get("status")=="RESEARCH_CANDIDATE_NOT_VALIDATED"' not in rf
    assert 'is_pick_status(r.get("status"))' in rf


@pytest.mark.parametrize("status", NEW_WATCH + ("SOMETHING_UNKNOWN",))
def test_value_screen_excludes_watch_and_unknown(status):
    assert phone_display.is_pick_status(status) is False


def test_squeeze_doc_names_row_count_fields():
    doc = (ROOT / "docs/cfb_totals_squeeze_20261024.md").read_text()
    assert "input_snapshot.n_rows" in doc and "= 204" in doc
    assert "evaluated_rows" in doc and "234" in doc
