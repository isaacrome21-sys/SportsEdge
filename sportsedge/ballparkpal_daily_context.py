from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

SOURCE_ROLE = "CONTEXT_ONLY"
MODEL_VOTE = False
TRUTH_GATE_ELIGIBLE = False

# Public BallparkPal report families seen in the daily slate posts.  These are
# intentionally supplemental: they can corroborate or challenge SportsEdge and
# surface data-quality flags, but they are not allowed to become Model_P votes.
REPORT_SPECS: dict[str, dict[str, Any]] = {
    "stadium_weather": {
        "context_class": "ballparkpal_stadium_weather",
        "source": "BALLPARKPAL_DAILY_STADIUM_REPORT",
        "allowed_uses": (
            "park_weather_crosscheck",
            "run_environment_crosscheck",
            "extra_base_hit_environment_crosscheck",
            "home_run_environment_crosscheck",
        ),
    },
    "home_run_zone": {
        "context_class": "ballparkpal_home_run_zone",
        "source": "BALLPARKPAL_HOME_RUN_ZONE",
        "allowed_uses": (
            "external_hr_sim_benchmark",
            "team_hr_environment_crosscheck",
            "slate_hr_environment_crosscheck",
        ),
    },
    "batter_pitcher": {
        "context_class": "ballparkpal_batter_pitcher",
        "source": "BALLPARKPAL_BATTER_V_PITCHER_MATCHUPS",
        "allowed_uses": (
            "batter_pitcher_context_crosscheck",
            "platoon_context_crosscheck",
            "contact_power_discipline_crosscheck",
        ),
    },
    "most_likely": {
        "context_class": "ballparkpal_most_likely",
        "source": "BALLPARKPAL_MOST_LIKELY_REPORT",
        "allowed_uses": (
            "external_sim_rank_crosscheck",
            "prop_candidate_discovery",
            "model_disagreement_flagging",
        ),
    },
    "pitcher_report": {
        "context_class": "ballparkpal_pitcher_report",
        "source": "BALLPARKPAL_PITCHING_PREVIEW",
        "allowed_uses": (
            "pitch_mix_crosscheck",
            "pitcher_contact_crosscheck",
            "starter_projection_crosscheck",
            "opener_bulk_role_crosscheck",
        ),
    },
}

CONTEXT_CLASSES = tuple(spec["context_class"] for spec in REPORT_SPECS.values())


class BallparkPalDailyContextError(ValueError):
    pass


def _optional_observed_at(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise BallparkPalDailyContextError(
                "observed_at_utc must be an ISO-8601 timestamp"
            ) from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise BallparkPalDailyContextError(
            "observed_at_utc must be timezone-aware"
        )
    return dt.astimezone(timezone.utc).isoformat()


def _positive_game_pk(value: Any) -> int:
    try:
        game_pk = int(value)
    except (TypeError, ValueError) as exc:
        raise BallparkPalDailyContextError("game_pk is required") from exc
    if game_pk <= 0:
        raise BallparkPalDailyContextError("game_pk must be positive")
    return game_pk


def normalize_ballparkpal_daily_report(
    report_type: str,
    report: Mapping[str, Any],
    *,
    expected_game_pk: int | None = None,
) -> dict[str, Any]:
    """Normalize a public BallparkPal daily report as supplemental context.

    The actual report payload is preserved rather than reverse-engineering the
    publisher's proprietary model from screenshots.  SportsEdge records source,
    report family, timestamp and game identity, then keeps the evidence in the
    HYBRID_CONTEXT lane only.

    ``most_likely`` American-style numbers are external simulation/ranking output,
    not sportsbook quotes.  Downstream consumers must never feed them to no-vig,
    EV or price-shopping logic as if they were offered market prices.
    """
    key = str(report_type).strip().lower()
    spec = REPORT_SPECS.get(key)
    if spec is None:
        raise BallparkPalDailyContextError(f"unsupported report_type: {key}")
    if not isinstance(report, Mapping):
        raise BallparkPalDailyContextError("report must be a mapping")

    game_pk = _positive_game_pk(report.get("game_pk"))
    if expected_game_pk is not None and game_pk != int(expected_game_pk):
        raise BallparkPalDailyContextError(
            f"game identity mismatch: report game_pk={game_pk}, expected={int(expected_game_pk)}"
        )

    payload = report.get("payload")
    if not isinstance(payload, (Mapping, list, tuple)):
        raise BallparkPalDailyContextError(
            "payload must be a mapping, list, or tuple"
        )

    return {
        "source": spec["source"],
        "source_role": SOURCE_ROLE,
        "context_class": spec["context_class"],
        "report_type": key,
        "model_p_eligible": MODEL_VOTE,
        "truth_gate_eligible": TRUTH_GATE_ELIGIBLE,
        "game_pk": game_pk,
        "observed_at_utc": _optional_observed_at(report.get("observed_at_utc")),
        "source_url": str(report.get("source_url") or "").strip() or None,
        "allowed_uses": list(spec["allowed_uses"]),
        "prohibited_uses": [
            "model_p_vote",
            "truth_gate_promotion_evidence",
            "market_price_substitution",
            "no_vig_input",
            "standalone_bet_recommendation",
        ],
        "payload": payload,
    }


def build_ballparkpal_daily_provider(report_type: str, report: Mapping[str, Any]):
    """Return a provider compatible with collect_mlb_hybrid_context()."""
    key = str(report_type).strip().lower()
    if key not in REPORT_SPECS:
        raise BallparkPalDailyContextError(f"unsupported report_type: {key}")

    def provider(game_pk: int, as_of: datetime, live_payload: Mapping[str, Any]) -> dict[str, Any]:
        return normalize_ballparkpal_daily_report(
            key,
            report,
            expected_game_pk=game_pk,
        )

    return provider
