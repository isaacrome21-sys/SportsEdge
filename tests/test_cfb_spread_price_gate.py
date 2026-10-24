from datetime import datetime, timedelta, timezone

from sportsedge.cfb_spread_price_gate import assess_spread


NOW = datetime(2026, 10, 23, 20, 0, tzinfo=timezone.utc)


def valid_args():
    return dict(
        line=-7.0,
        opposite_line=7.0,
        price_american=-110,
        opposite_price_american=-110,
        side_quoted_at=NOW - timedelta(seconds=20),
        opposite_quoted_at=NOW - timedelta(seconds=30),
        as_of=NOW,
        sportsbook="DraftKings",
        source_ref="capture://cfb/game-1/spread",
        cover_probability=.55,
        push_probability=.05,
        loss_probability=.40,
        model_verified=True,
        model_market_blind=True,
        model_id="CFB_SPREAD_VERIFIED_V1",
    )


def test_push_aware_ev_no_vig_and_playable_to():
    result = assess_spread(**valid_args())
    assert result.status == "PLAY"
    assert result.reason == "POSITIVE_EV_AND_MARKET_EDGE"
    assert result.expected_profit_per_unit > 0
    assert abs(result.conditional_cover - .55 / .95) < 1e-12
    assert abs(result.no_vig_market_cover - .5) < 1e-12
    assert result.no_vig_edge > 0
    assert result.playable_to_american == -137


def test_price_cap_and_illinois_exclusion():
    args = valid_args() | {"price_american": -170}
    assert assess_spread(**args).reason == "STRAIGHT_PRICE_CAP"
    args = valid_args() | {"illinois_college_team": True}
    assert assess_spread(**args).reason == "ILLINOIS_COLLEGE_EXCLUDED"


def test_model_and_source_authority_fail_closed():
    args = valid_args()
    assert assess_spread(**(args | {"model_verified": False})).reason == "MODEL_NOT_VERIFIED"
    assert assess_spread(**(args | {"model_market_blind": False})).reason == "MODEL_NOT_MARKET_BLIND"
    assert assess_spread(**(args | {"model_id": ""})).reason == "MODEL_ID_MISSING"
    assert assess_spread(**(args | {"sportsbook": "Unknown"})).reason == "SPORTSBOOK_NOT_DRAFTKINGS"
    assert assess_spread(**(args | {"source_ref": " "})).reason == "SOURCE_REF_MISSING"


def test_exact_paired_line_and_two_sided_prices_required():
    args = valid_args()
    assert assess_spread(**(args | {"opposite_line": 7.5})).reason == "PAIRED_LINE_MISMATCH"
    assert assess_spread(**(args | {"opposite_price_american": None})).reason == "PAIRED_PRICE_INVALID"
    assert assess_spread(**(args | {"price_american": -99})).reason == "PAIRED_PRICE_INVALID"


def test_timestamp_freshness_future_and_capture_span_fail_closed():
    args = valid_args()
    assert assess_spread(
        **(args | {"side_quoted_at": NOW - timedelta(seconds=181)})
    ).reason == "QUOTE_STALE"
    assert assess_spread(
        **(args | {"side_quoted_at": NOW + timedelta(seconds=1)})
    ).reason == "QUOTE_FROM_FUTURE"
    assert assess_spread(
        **(
            args
            | {
                "side_quoted_at": NOW - timedelta(seconds=1),
                "opposite_quoted_at": NOW - timedelta(seconds=152),
            }
        )
    ).reason == "PAIRED_CAPTURE_SPAN_EXCEEDED"
    assert assess_spread(
        **(args | {"side_quoted_at": datetime(2026, 10, 23, 20, 0)})
    ).reason == "QUOTE_TIMESTAMP_INVALID"


def test_invalid_probabilities_and_all_push_fail_closed():
    args = valid_args()
    assert assess_spread(**(args | {"cover_probability": None})).reason == "PROBABILITIES_INVALID"
    assert assess_spread(**(args | {"loss_probability": .3})).reason == "PROBABILITIES_NOT_NORMALIZED"
    assert assess_spread(
        **(args | {"cover_probability": 0, "push_probability": 1, "loss_probability": 0})
    ).reason == "ALL_PUSH_NO_DECISION"


def test_nonpositive_ev_passes_with_diagnostics():
    result = assess_spread(
        **(
            valid_args()
            | {
                "cover_probability": .45,
                "push_probability": 0,
                "loss_probability": .55,
            }
        )
    )
    assert result.status == "PASS"
    assert result.reason == "NONPOSITIVE_EV"
    assert result.expected_profit_per_unit < 0
    assert result.no_vig_market_cover == .5
    assert result.no_vig_edge < 0
