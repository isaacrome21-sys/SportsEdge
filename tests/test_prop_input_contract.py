from datetime import datetime, timezone

from sportsedge.mlb.prop_input_contract import (
    InputDatum, InputKind, PITCHER_PROP_REQUIRED, audit_required_inputs,
)

NOW = datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)


def d(name, kind, ts="2026-08-22T00:55:00+00:00"):
    return InputDatum(name=name, value=1.0, kind=kind, as_of_utc=ts, source="fixture")


def test_missing_and_stale_are_distinct():
    inputs = {
        "pitcher_k_rate": d("pitcher_k_rate", InputKind.STATCAST, "2026-08-19T00:00:00+00:00"),
    }
    a = audit_required_inputs(inputs, PITCHER_PROP_REQUIRED, now_utc=NOW)
    assert not a.usable
    assert "pitcher_k_rate" in a.stale
    assert "confirmed_lineup" in a.missing


def test_fresh_complete_contract_passes():
    kind = {
        "pitcher_k_rate": InputKind.STATCAST, "pitcher_bb_rate": InputKind.STATCAST,
        "pitcher_xba": InputKind.STATCAST, "pitcher_xwoba": InputKind.STATCAST,
        "pitch_count_recent": InputKind.WORKLOAD, "workload_limit": InputKind.WORKLOAD,
        "opponent_k_rate_vs_hand": InputKind.STATCAST, "opponent_whiff_rate_vs_hand": InputKind.STATCAST,
        "confirmed_lineup": InputKind.LINEUP,
    }
    inputs = {name: d(name, kind[name]) for name in PITCHER_PROP_REQUIRED}
    assert audit_required_inputs(inputs, PITCHER_PROP_REQUIRED, now_utc=NOW).usable


def test_lineup_ttl_is_stricter_than_statcast():
    lineup = d("confirmed_lineup", InputKind.LINEUP, "2026-08-22T00:30:00+00:00")
    statcast = d("pitcher_xba", InputKind.STATCAST, "2026-08-22T00:30:00+00:00")
    assert not lineup.is_fresh(NOW)
    assert statcast.is_fresh(NOW)
