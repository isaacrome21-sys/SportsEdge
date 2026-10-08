from sportsedge.mlb_context_artifact import build_candidate_artifact


def test_artifact_requires_validated_pit_price_blind_source():
    validation = {"status": "VALIDATED"}
    try:
        build_candidate_artifact(
            {},
            validation,
            source_manifest={"pit_strict": False, "contains_sportsbook_prices": False},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected PIT rejection")

    try:
        build_candidate_artifact(
            {},
            validation,
            source_manifest={"pit_strict": True, "contains_sportsbook_prices": True},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected sportsbook rejection")


def test_artifact_identity_is_deterministic():
    validation = {"status": "VALIDATED", "holdout_games": 200}
    manifest = {
        "pit_strict": True,
        "contains_sportsbook_prices": False,
        "source": "fixture",
    }
    one = build_candidate_artifact(
        {"wind_mph": 0.01}, validation, source_manifest=manifest
    )
    two = build_candidate_artifact(
        {"wind_mph": 0.01}, validation, source_manifest=manifest
    )
    assert one["artifact_id"] == two["artifact_id"]
    assert one["status"] == "VALIDATED"


def test_artifact_rejects_nonfinite_coefficient():
    try:
        build_candidate_artifact(
            {"wind_mph": float("nan")},
            {"status": "VALIDATED"},
            source_manifest={"pit_strict": True, "contains_sportsbook_prices": False},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected non-finite coefficient rejection")
