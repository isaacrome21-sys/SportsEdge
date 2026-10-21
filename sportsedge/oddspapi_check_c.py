"""Check C2: MLB SBR sample under the posted Check B bars.

Comparator adapted byte-for-byte except MLB season identity from Check B
commit a31ef589e818cf6db25a14062159e4f7fd217f0e. >=200 games, >=4
seasons, latest complete season final week; exact same numerical bars.
No per-season quota invented. Sources and hash strings are unverified.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
from typing import Any, Mapping

VERSION = "ODDSPAPI_SBR_MLB_CHECK_C2_DRYRUN_V1"
SOURCE_POLICY = ("OWNER_DELEGATED_ADMISSION_PROTOCOL_DRAFT_20261020_"
                 "SECTION_3_UNPINNED_IN_REPO")
MIN_DISTINCT_GAMES = 200
MIN_SEASONS = 4
ML_MAX_PRICE_DIFF = 10
ML_MIN_MATCH = Decimal("0.97")
LINE_MIN_EXACT = Decimal("0.95")
LINE_MAX_SMALL_DIFF = Decimal("0.5")
LINE_MIN_WITHIN_SMALL = Decimal("0.99")
LINE_FORBIDDEN_DIFF = Decimal("1.0")
_SHA = re.compile(r"^[a-fA-F0-9]{64}$")
_IDENT = re.compile(r"^[a-zA-Z0-9:_-]{1,128}$")
_SEASON = re.compile(r"^(20[0-9]{2})$")
_SIDES = {"MONEYLINE": "HOME", "SPREAD": "HOME", "TOTAL": "OVER"}
_KEYS = {"version", "league", "bookmaker", "market", "cohort", "samples"}
_COHORT = {"most_recent_complete_season", "final_week_start_utc",
           "final_week_end_utc", "final_week_game_ids",
           "official_schedule_snapshot_sha256", "archive_manifest_sha256"}
_ROW = {"game_id", "season", "game_start_utc", "side", "sbr_bookmaker",
        "oddspapi_bookmaker", "sbr_close", "oddspapi_candidate",
        "sbr_receipt_sha256", "oddspapi_receipt_sha256"}
_PRICE_FIELDS = {"american_price", "line"}


class CheckCRefusal(ValueError):
    """Sanitized structural refusal; never show an unverified raw quote."""


def _id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise CheckCRefusal(f"{name}_IDENTITY_INVALID")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise CheckCRefusal(f"{name}_SHA256_REQUIRED")
    return value.lower()


def _utc(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise CheckCRefusal(f"{name}_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CheckCRefusal(f"{name}_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CheckCRefusal(f"{name}_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _season(value: Any) -> int:
    if not isinstance(value, str) or not _SEASON.fullmatch(value):
        raise CheckCRefusal("MLB_SEASON_ID_INVALID")
    return int(value)


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise CheckCRefusal(f"{name}_NON_NUMERIC")
    try:
        x = Decimal(str(value))
    except InvalidOperation as exc:
        raise CheckCRefusal(f"{name}_NON_NUMERIC") from exc
    if not x.is_finite() or abs(x) > Decimal("100000"):
        raise CheckCRefusal(f"{name}_NONFINITE_OR_OUT_OF_RANGE")
    return x


def _quote(quote: Any, *, market: str) -> tuple[int | None, Decimal | None]:
    # Missing closes MUST stay in denominators. Missing quotes are *not*
    # a schema error and never get silently removed from the sample.
    if quote is None:
        return None, None
    if not isinstance(quote, Mapping) or set(quote) != _PRICE_FIELDS:
        raise CheckCRefusal("B_QUOTE_SCHEMA_INVALID")
    if market == "MONEYLINE":
        price = quote.get("american_price")
        if type(price) is not int or (-100 < price < 100) or abs(price) > 100000:
            raise CheckCRefusal("B_AMERICAN_PRICE_INVALID")
        if quote.get("line") is not None:
            raise CheckCRefusal("B_MONEYLINE_MUST_HAVE_NULL_LINE")
        return price, None
    if quote.get("american_price") is not None:
        # B spread/total compares the offered LINE, not a substituted price.
        # A separate market-pricing comparator owns price observations.
        price = quote.get("american_price")
        if type(price) is not int or (-100 < price < 100) or abs(price) > 100000:
            raise CheckCRefusal("B_AMERICAN_PRICE_INVALID")
    if quote.get("line") is None:
        return None, None
    return None, _decimal(quote.get("line"), "B_LINE")


def _fraction(n: int, denominator: int) -> Decimal:
    return Decimal(n) / Decimal(denominator)


def _clean_cohort(raw: Any) -> dict:
    if not isinstance(raw, Mapping) or set(raw) != _COHORT:
        raise CheckCRefusal("B_COHORT_MANIFEST_SCHEMA_INVALID")
    season = raw["most_recent_complete_season"]
    _season(season)
    begin = _utc(raw["final_week_start_utc"], "FINAL_WEEK_START")
    end = _utc(raw["final_week_end_utc"], "FINAL_WEEK_END")
    if begin >= end or (end-begin).total_seconds() > 8*24*3600:
        raise CheckCRefusal("FINAL_WEEK_WINDOW_INVALID")
    ids = raw.get("final_week_game_ids")
    if not isinstance(ids, list) or not ids:
        raise CheckCRefusal("FINAL_WEEK_SCHEDULE_REQUIRED")
    expected = {_id(x, "FINAL_WEEK_GAME") for x in ids}
    if len(expected) != len(ids):
        raise CheckCRefusal("FINAL_WEEK_SCHEDULE_DUPLICATE_GAME")
    return {"season": season, "start": begin, "end": end,
            "expected": expected,
            "schedule_hash": _sha(raw["official_schedule_snapshot_sha256"], "OFFICIAL_SCHEDULE"),
            "archive_hash": _sha(raw["archive_manifest_sha256"], "SBR_ARCHIVE_MANIFEST")}


def evaluate_c2(payload: Mapping[str, Any]) -> dict:
    """Evaluate the specific section-3 B NUMERIC bars; never admit sources."""
    if not isinstance(payload, Mapping) or set(payload) != _KEYS or (
            payload.get("version") != VERSION):
        raise CheckCRefusal("UNPINNED_B_DRYRUN_SCHEMA_ONLY")
    if payload.get("league") != "MLB" or payload.get("bookmaker") != "draftkings":
        raise CheckCRefusal("C2_MLB_DRAFTKINGS_ONLY")
    market = payload.get("market")
    if not isinstance(market, str) or market not in _SIDES:
        raise CheckCRefusal("B_MARKET_OUT_OF_SCOPE")
    cohort = _clean_cohort(payload.get("cohort"))
    rows = payload.get("samples")
    if not isinstance(rows, list) or not rows:
        raise CheckCRefusal("B_NONEMPTY_FIXED_SAMPLE_REQUIRED")
    results = []
    seasons: set[str] = set()
    observed: set[str] = set()
    final_week_matched: set[str] = set()
    missing_book = missing_closes = 0
    exact = within_half = within_10 = 0
    forbidden = 0
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) != _ROW:
            raise CheckCRefusal("B_SAMPLE_SCHEMA_INVALID")
        game = _id(raw.get("game_id"), "B_GAME")
        if game in observed:
            raise CheckCRefusal("B_DUPLICATE_GAME_WOULD_DOUBLE_COUNT")
        observed.add(game)
        season = raw.get("season")
        _season(season)
        seasons.add(season)
        start = _utc(raw.get("game_start_utc"), "B_GAME_START")
        if raw.get("side") != _SIDES[market]:
            raise CheckCRefusal("B_CANONICAL_SIDE_ONLY")
        _sha(raw.get("sbr_receipt_sha256"), "B_SBR_RECEIPT")
        _sha(raw.get("oddspapi_receipt_sha256"), "B_ODDSPAPI_RECEIPT")
        if game in cohort["expected"]:
            if season != cohort["season"] or not (
                    cohort["start"] <= start <= cohort["end"]):
                raise CheckCRefusal("B_FINAL_WEEK_FIXTURE_SEASON_WINDOW_MISMATCH")
            final_week_matched.add(game)
        book_ok = (raw.get("sbr_bookmaker") == "draftkings"
                   and raw.get("oddspapi_bookmaker") == "draftkings")
        if not book_ok:
            missing_book += 1
        sbr_price, sbr_line = _quote(raw.get("sbr_close"), market=market)
        provider_price, provider_line = _quote(
            raw.get("oddspapi_candidate"), market=market)
        if raw.get("sbr_close") is None or raw.get("oddspapi_candidate") is None:
            missing_closes += 1
        reason = None
        if not book_ok:
            reason = "B_EXPLICIT_DK_BOOK_IDENTITIES_REQUIRED"
        elif raw.get("sbr_close") is None or raw.get("oddspapi_candidate") is None:
            reason = "B_MISSING_CLOSE_OR_PROVIDER_QUOTE"
        elif market == "MONEYLINE":
            if abs(sbr_price - provider_price) <= ML_MAX_PRICE_DIFF:
                within_10 += 1
            else:
                reason = "B_MONEYLINE_PRICE_GAP_OVER_10"
        else:
            if sbr_line is None or provider_line is None:
                reason = "B_MISSING_LINE"
            else:
                diff = abs(sbr_line - provider_line)
                if diff == 0:
                    exact += 1
                if diff <= LINE_MAX_SMALL_DIFF:
                    within_half += 1
                if diff > LINE_FORBIDDEN_DIFF:
                    forbidden += 1
                    reason = "B_LINE_GAP_GT_1"
                elif diff > LINE_MAX_SMALL_DIFF:
                    reason = "B_LINE_GAP_GT_HALF"
                elif diff != 0:
                    reason = "B_LINE_NOT_EXACT"
        results.append({
            "game_sha12": sha256(game.encode()).hexdigest()[:12],
            "season": season,
            "status": "PASS_NUMERIC_ONLY" if reason is None else "FAIL",
            "reason": reason,
        })
    absent = cohort["expected"] - final_week_matched
    # An official-schedule game missing from the submitted rows counts as
    # a failure in the comparison denominator. It is NOT an observed game
    # and cannot help satisfy the sample-size floor.
    denominator = len(rows) + len(absent)
    season_counts = {y: sum(r["season"] == y for r in results)
                     for y in sorted(seasons)}
    cohort_ok = (len(observed) >= MIN_DISTINCT_GAMES
                 and len(seasons) >= MIN_SEASONS
                 and max(seasons) == cohort["season"]
                 and not absent)
    market_rules_met = (
        (_fraction(within_10, denominator) >= ML_MIN_MATCH)
        if market == "MONEYLINE" else (
            _fraction(exact, denominator) >= LINE_MIN_EXACT
            and _fraction(within_half, denominator) >= LINE_MIN_WITHIN_SMALL
            and forbidden == 0
        )
    )
    bar_details = (
        {"ml_within_10_american": within_10,
         "ml_required_rate": "0.97",
         "ml_observed_rate": str(_fraction(within_10, denominator))}
        if market == "MONEYLINE" else {
            "line_exact": exact, "line_required_exact_rate": "0.95",
            "line_observed_exact_rate": str(_fraction(exact, denominator)),
            "line_within_half": within_half,
            "line_required_within_half_rate": "0.99",
            "line_observed_within_half_rate": str(_fraction(within_half, denominator)),
            "line_gap_gt_one_game_count": forbidden,
            "max_gap_over_one_allowed": 0,
        }
    )
    return {
        "version": VERSION, "status": "NOT_ADMITTED_C2_DRYRUN",
        "source_policy": SOURCE_POLICY, "source_policy_repo_sha256": None,
        "market": market, "bookmaker": "draftkings", "league": "MLB",
        "sample_games_submitted": len(rows), "observed_distinct_games": len(observed),
        "cohort_comparison_denominator": denominator,
        "seasons_count": len(seasons), "per_season_submitted_game_counts": season_counts,
        "most_recent_complete_season_claimed": cohort["season"],
        "final_week_expected_game_count_claimed": len(cohort["expected"]),
        "final_week_sampled_game_count": len(final_week_matched),
        "final_week_missing_games": len(absent),
        "final_week_missing_game_sha12": sorted(
            sha256(x.encode()).hexdigest()[:12] for x in absent),
        "sbr_book_identity_missing_or_wrong": missing_book,
        "missing_sbr_close_or_provider_quote": missing_closes,
        "book_identity_numeric_requirement_met": missing_book == 0,
        "cohort_numeric_requirement_met_unverified": cohort_ok,
        "market_numeric_requirement_met_unverified": market_rules_met,
        "numeric_c2_bar_met_UNVERIFIED": bool(
            cohort_ok and market_rules_met and missing_book == 0),
        "bar_details": bar_details,
        "row_results": results,
        "official_schedule_snapshot_sha256_shape_only": cohort["schedule_hash"],
        "archive_manifest_sha256_shape_only": cohort["archive_hash"],
        "official_schedule_independently_authenticated": False,
        "SBR_archive_independently_authenticated": False,
        "OddsPapi_quote_independently_authenticated": False,
        "true_close_proven": False,
        "admission": "NOT_ADMITTED",
        "source_eligible": False, "play_authority": False,
        "market_test": "NOT_STARTED",
        "notes": [
            "Policy §3 thresholds transcribed from Rocky's issue #2447 post; original workspace draft has no repository file/hash pin.",
            "Caller-supplied final-week roster and hash strings are not a verified official schedule.",
            "Missing closes count in denominator; unrepresented final-week games also fail and count in denominator.",
            "SBR archive may lack timestamps and book identity; passing numeric threshold never proves CLOSE or PIT.",
            "A/C1/D/E and original-source authentication must be separately demonstrated before any admission run.",
        ],
    }


C_VERSION = "ODDSPAPI_CHECK_C_DRYRUN_V1"


def evaluate_c1(record):
    """ALCS G6 numerical reproduction. Actual identity remains external proof."""
    fields = {"canonical_event_id", "league", "series", "game_number",
              "home_team", "away_team", "actual_first_play", "quotes"}
    if not isinstance(record, Mapping) or set(record) != fields:
        raise CheckCRefusal("C1_SCHEMA_INVALID")
    event = _id(record["canonical_event_id"], "C1_EVENT")
    if (record["league"] != "MLB" or record["series"] != "ALCS"
            or type(record["game_number"]) is not int or record["game_number"] != 6
            or {record["home_team"], record["away_team"]} != {"TB", "CLE"}):
        raise CheckCRefusal("C1_ALCS_G6_IDENTITY_MISMATCH")
    anchor = record["actual_first_play"]
    if not isinstance(anchor, Mapping) or set(anchor) != {
            "canonical_event_id", "actual_first_play_utc", "official_source_sha256"}:
        raise CheckCRefusal("C1_ACTUAL_FIRST_PLAY_REQUIRED")
    if anchor["canonical_event_id"] != event:
        raise CheckCRefusal("C1_ANCHOR_EVENT_MISMATCH")
    _sha(anchor["official_source_sha256"], "C1_ANCHOR")
    first = _utc(anchor["actual_first_play_utc"], "C1_FIRST_PLAY")
    quotes = record["quotes"]
    if not isinstance(quotes, list):
        raise CheckCRefusal("C1_QUOTES_REQUIRED")
    expected = {("MONEYLINE", "TB"), ("MONEYLINE", "CLE"), ("RUN_LINE", "TB")}
    seen, results = set(), []
    for quote in quotes:
        if not isinstance(quote, Mapping) or set(quote) != {
                "canonical_event_id", "market", "team", "bookmaker", "line",
                "american_price", "captured_at_utc", "source_sha256"}:
            raise CheckCRefusal("C1_QUOTE_SCHEMA_INVALID")
        if quote["canonical_event_id"] != event or quote["bookmaker"] != "draftkings":
            raise CheckCRefusal("C1_QUOTE_EVENT_OR_BOOK_MISMATCH")
        key = (quote["market"], quote["team"])
        if key not in expected or key in seen:
            raise CheckCRefusal("C1_UNEXPECTED_OR_DUPLICATE_QUOTE")
        seen.add(key)
        _sha(quote["source_sha256"], "C1_QUOTE")
        timestamp_ok = _utc(quote["captured_at_utc"], "C1_QUOTE") < first
        if key[0] == "MONEYLINE":
            price, _ = _quote({"american_price": quote["american_price"],
                               "line": quote["line"]}, market="MONEYLINE")
            number_ok = price == (-158 if key[1] == "TB" else 130)
        else:
            _, line = _quote({"american_price": quote["american_price"],
                              "line": quote["line"]}, market="SPREAD")
            number_ok = line == Decimal("-1.5")
        results.append({"market": key[0], "team": key[1], "numbers_exact": number_ok,
                        "strictly_pre_first_play": timestamp_ok,
                        "pass_numeric_only": number_ok and timestamp_ok})
    missing = sorted(expected - seen)
    return {"numeric_c1_bar_met_UNVERIFIED": not missing and all(
                r["pass_numeric_only"] for r in results), "rows": results,
            "missing_quotes": [list(k) for k in missing],
            "fixture_and_sources_independently_authenticated": False}


def evaluate_check_c(payload):
    if not isinstance(payload, Mapping) or set(payload) != {"version", "alcs_g6", "sbr_sample"}:
        raise CheckCRefusal("C_SCHEMA_INVALID")
    if payload["version"] != C_VERSION:
        raise CheckCRefusal("C_VERSION_INVALID")
    c1, c2 = evaluate_c1(payload["alcs_g6"]), evaluate_c2(payload["sbr_sample"])
    return {"version": C_VERSION, "status": "NOT_ADMITTED_C_DRYRUN",
            "check_C1": c1, "check_C2": c2,
            "numeric_c_bar_met_UNVERIFIED": c1["numeric_c1_bar_met_UNVERIFIED"]
                and c2["numeric_c2_bar_met_UNVERIFIED"],
            "admission": "NOT_ADMITTED", "eligible": False, "play_authority": False}
