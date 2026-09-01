from datetime import datetime, timedelta, timezone

from sportsedge.shared_acquisition_contract import (
    ConfirmationStatus,
    FreshnessStatus,
    TrustClass,
    build_datum,
    delta_changed,
    scoped_blockers,
)


def test_manual_fill_without_observed_time_is_not_fresh():
    now = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    row = build_datum(
        sport="NFL", scope_type="PLAYER_PROP", scope_id="game:player:rec_yards",
        field_name="draftkings_quote", value={"line": 63.5, "price": -110},
        source_name="MANUAL_SCREENSHOT", source_uri="manual://screenshot",
        retrieved_at=now, observed_at=None, ttl_seconds=120,
        confirmation_status=ConfirmationStatus.REPORTED,
        trust_class=TrustClass.MARKET_ONLY, manual_fill=True,
    )
    assert row.freshness_status == FreshnessStatus.FRESHNESS_UNVERIFIED


def test_manual_and_auto_use_same_ttl_rule():
    now = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    observed = now - timedelta(seconds=200)
    rows = [
        build_datum(
            sport="MLB", scope_type="MARKET", scope_id=f"g:{kind}",
            field_name="quote", value=1, source_name=kind, source_uri="https://example.test",
            retrieved_at=now, observed_at=observed, ttl_seconds=120,
            trust_class=TrustClass.MARKET_ONLY, manual_fill=(kind == "manual"),
        )
        for kind in ("auto", "manual")
    ]
    assert {row.freshness_status for row in rows} == {FreshnessStatus.STALE}


def test_stale_model_p_input_is_downgraded_out_of_model_p():
    now = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    row = build_datum(
        sport="CFB", scope_type="GAME", scope_id="123", field_name="weather_wind",
        value=18, source_name="NWS", source_uri="https://weather.gov",
        retrieved_at=now, observed_at=now - timedelta(hours=2), ttl_seconds=900,
        trust_class=TrustClass.MODEL_P_OBJECTIVE,
    )
    assert row.freshness_status == FreshnessStatus.STALE
    assert row.trust_class == TrustClass.CONTEXT_ONLY


def test_blockers_are_scoped_not_slate_wide():
    now = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    good = build_datum(
        sport="NFL", scope_type="GAME", scope_id="game-a", field_name="weather",
        value={"wind": 6}, source_name="NWS", source_uri="https://weather.gov",
        observed_at=now, retrieved_at=now, ttl_seconds=900,
        trust_class=TrustClass.MODEL_P_OBJECTIVE,
    )
    missing = build_datum(
        sport="NFL", scope_type="PLAYER_PROP", scope_id="game-b:player-x:targets",
        field_name="quote", value=None, source_name="ODDS_API", source_uri="https://example.test",
        retrieved_at=now, missing=True, trust_class=TrustClass.MARKET_ONLY,
    )
    blockers = scoped_blockers([good, missing])
    assert ("GAME", "game-a") not in blockers
    assert blockers[("PLAYER_PROP", "game-b:player-x:targets")] == ["quote"]


def test_optional_missing_context_is_visible_but_not_a_pricing_blocker():
    now = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    optional = build_datum(
        sport="CFB", scope_type="GAME", scope_id="game-c",
        field_name="secondary_weather_commentary", value=None,
        source_name="MYSPORTSWEATHER", source_uri="https://mysportsweather.com/",
        retrieved_at=now, missing=True, trust_class=TrustClass.CONTEXT_ONLY,
        required_for_evaluation=False,
    )
    assert optional.freshness_status == FreshnessStatus.MISSING
    assert scoped_blockers([optional]) == {}


def test_required_unverified_manual_quote_blocks_only_its_scope():
    now = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    quote = build_datum(
        sport="MLB", scope_type="PLAYER_PROP", scope_id="g:p:ks",
        field_name="quote", value={"line": 5.5, "price": -110},
        source_name="MANUAL_SCREENSHOT", source_uri="manual://screenshot",
        retrieved_at=now, observed_at=None, ttl_seconds=120,
        trust_class=TrustClass.MARKET_ONLY, manual_fill=True,
        required_for_evaluation=True,
    )
    assert scoped_blockers([quote]) == {("PLAYER_PROP", "g:p:ks"): ["quote"]}


def test_delta_changed_returns_only_changed_fields():
    assert delta_changed({"wind": 5, "roof": "OPEN"}, {"wind": 12, "roof": "OPEN"}) == {
        "wind": (5, 12)
    }
