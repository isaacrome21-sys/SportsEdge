"""Research-only SBR NBA archive Check B numeric *dry run*.

The thresholds are transcribed from Rocky's 2026-10-20 owner-delegated
ADMISSION_PROTOCOL_DRAFT.md section 3, posted in GitHub coordination issue
#2447 (not yet pinned as a versioned source in the repo). This evaluates
supplied rows without network or authenticating sources.

A numeric B pass is never market-source admission: SBR book identity, final
week cohort completeness, actual closes, OddsPapi provenance, and source
dates still require *independent* evidence. Check A/C/D/E remain separate.
This code never writes to a registry or relabels a price CLOSE.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
from typing import Any, Mapping

VERSION = "ODDSPAPI_SBR_NBA_CHECK_B_DRYRUN_V1"
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
_SEASON = re.compile(r"^(20[0-9]{2})-([0-9]{2})$")
_SIDES = {"MONEYLINE": "HOME", "SPREAD": "HOME", "TOTAL": "OVER"}
_KEYS = {"version", "league", "bookmaker", "market", "cohort", "samples"}
_COHORT = {"most_recent_complete_season", "final_week_start_utc",
           "final_week_end_utc", "final_week_game_ids",
           "official_schedule_snapshot_sha256", "archive_manifest_sha256"}
_ROW = {"game_id", "season", "game_start_utc", "side", "sbr_bookmaker",
        "oddspapi_bookmaker", "sbr_close", "oddspapi_candidate",
        "sbr_receipt_sha256", "oddspapi_receipt_sha256"}
_PRICE_FIELDS = {"american_price", "line"}


class SBRCheckBRefusal(ValueError):
    """Sanitized structural refusal; never show an unverified raw quote."""


def _id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise SBRCheckBRefusal(f"{name}_IDENTITY_INVALID")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise SBRCheckBRefusal(f"{name}_SHA256_REQUIRED")
    return value.lower()


def _utc(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise SBRCheckBRefusal(f"{name}_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SBRCheckBRefusal(f"{name}_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SBRCheckBRefusal(f"{name}_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _season(value: Any) -> int:
    if not isinstance(value, str) or not _SEASON.fullmatch(value):
        raise SBRCheckBRefusal("NBA_SEASON_ID_INVALID")
    start, suffix = value.split("-")
    year = int(start)
    if suffix != str((year+1)%100).zfill(2):
        raise SBRCheckBRefusal("NBA_SEASON_ID_INVALID")
    return year


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise SBRCheckBRefusal(f"{name}_NON_NUMERIC")
    try:
        x = Decimal(str(value))
    except InvalidOperation as exc:
        raise SBRCheckBRefusal(f"{name}_NON_NUMERIC") from exc
    if not x.is_finite() or abs(x) > Decimal("100000"):
        raise SBRCheckBRefusal(f"{name}_NONFINITE_OR_OUT_OF_RANGE")
    return x


def _quote(quote: Any, *, market: str) -> tuple[int | None, Decimal | None]:
    # Missing closes MUST stay in denominators. Missing quotes are *not*
    # a schema error and never get silently removed from the sample.
    if quote is None:
        return None, None
    if not isinstance(quote, Mapping) or set(quote) != _PRICE_FIELDS:
        raise SBRCheckBRefusal("B_QUOTE_SCHEMA_INVALID")
    if market == "MONEYLINE":
        price = quote.get("american_price")
        if type(price) is not int or (-100 < price < 100) or abs(price) > 100000:
            raise SBRCheckBRefusal("B_AMERICAN_PRICE_INVALID")
        if quote.get("line") is not None:
            raise SBRCheckBRefusal("B_MONEYLINE_MUST_HAVE_NULL_LINE")
        return price, None
    if quote.get("american_price") is not None:
        # B spread/total compares the offered LINE, not a substituted price.
        # A separate market-pricing comparator owns price observations.
        price = quote.get("american_price")
        if type(price) is not int or (-100 < price < 100) or abs(price) > 100000:
            raise SBRCheckBRefusal("B_AMERICAN_PRICE_INVALID")
    if quote.get("line") is None:
        return None, None
    return None, _decimal(quote.get("line"), "B_LINE")


def _fraction(n: int, denominator: int) -> Decimal:
    return Decimal(n) / Decimal(denominator)


def _clean_cohort(raw: Any) -> dict:
    if not isinstance(raw, Mapping) or set(raw) != _COHORT:
        raise SBRCheckBRefusal("B_COHORT_MANIFEST_SCHEMA_INVALID")
    season = raw["most_recent_complete_season"]
    _season(season)
    begin = _utc(raw["final_week_start_utc"], "FINAL_WEEK_START")
    end = _utc(raw["final_week_end_utc"], "FINAL_WEEK_END")
    if begin >= end or (end-begin).total_seconds() > 8*24*3600:
        raise SBRCheckBRefusal("FINAL_WEEK_WINDOW_INVALID")
    ids = raw.get("final_week_game_ids")
    if not isinstance(ids, list) or not ids:
        raise SBRCheckBRefusal("FINAL_WEEK_SCHEDULE_REQUIRED")
    expected = {_id(x, "FINAL_WEEK_GAME") for x in ids}
    if len(expected) != len(ids):
        raise SBRCheckBRefusal("FINAL_WEEK_SCHEDULE_DUPLICATE_GAME")
    return {"season": season, "start": begin, "end": end,
            "expected": expected,
            "schedule_hash": _sha(raw["official_schedule_snapshot_sha256"], "OFFICIAL_SCHEDULE"),
            "archive_hash": _sha(raw["archive_manifest_sha256"], "SBR_ARCHIVE_MANIFEST")}


def inspect_sbr_check_b_dryrun(payload: Mapping[str, Any]) -> dict:
    """Evaluate the specific section-3 B NUMERIC bars; never admit sources."""
    if not isinstance(payload, Mapping) or set(payload) != _KEYS or (
            payload.get("version") != VERSION):
        raise SBRCheckBRefusal("UNPINNED_B_DRYRUN_SCHEMA_ONLY")
    if payload.get("league") != "NBA" or payload.get("bookmaker") != "draftkings":
        raise SBRCheckBRefusal("B_NBA_DRAFTKINGS_ONLY")
    market = payload.get("market")
    if not isinstance(market, str) or market not in _SIDES:
        raise SBRCheckBRefusal("B_MARKET_OUT_OF_SCOPE")
    cohort = _clean_cohort(payload.get("cohort"))
    rows = payload.get("samples")
    if not isinstance(rows, list) or not rows:
        raise SBRCheckBRefusal("B_NONEMPTY_FIXED_SAMPLE_REQUIRED")
    results = []
    seasons: set[str] = set()
    observed: set[str] = set()
    final_week_matched: set[str] = set()
    missing_book = missing_closes = 0
    exact = within_half = within_10 = 0
    forbidden = 0
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) != _ROW:
            raise SBRCheckBRefusal("B_SAMPLE_SCHEMA_INVALID")
        game = _id(raw.get("game_id"), "B_GAME")
        if game in observed:
            raise SBRCheckBRefusal("B_DUPLICATE_GAME_WOULD_DOUBLE_COUNT")
        observed.add(game)
        season = raw.get("season")
        _season(season)
        seasons.add(season)
        start = _utc(raw.get("game_start_utc"), "B_GAME_START")
        if raw.get("side") != _SIDES[market]:
            raise SBRCheckBRefusal("B_CANONICAL_SIDE_ONLY")
        _sha(raw.get("sbr_receipt_sha256"), "B_SBR_RECEIPT")
        _sha(raw.get("oddspapi_receipt_sha256"), "B_ODDSPAPI_RECEIPT")
        if game in cohort["expected"]:
            if season != cohort["season"] or not (
                    cohort["start"] <= start <= cohort["end"]):
                raise SBRCheckBRefusal("B_FINAL_WEEK_FIXTURE_SEASON_WINDOW_MISMATCH")
            final_week_matched.add(game)
        book_ok = (raw.get("sbr_bookmaker") == "draftkings"
                   and raw.get("oddspapi_bookmaker") == "draftkings")
        if not book_ok:
            missing_book += 1
        sbr_price, sbr_line = _quote(raw.get("sbr_close"), market=market)
        provider_price, provider_line = _quote(
            raw.get("oddspapi_candidate"), market=market)
        # A missing required market line is a missing close even when the
        # caller supplies a non-null quote object. Preserve every game in
        # the denominator and fail the numeric B bar on any missing close.
        if (raw.get("sbr_close") is None
                or raw.get("oddspapi_candidate") is None
                or (market != "MONEYLINE"
                    and (sbr_line is None or provider_line is None))):
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
    # Draft §3 also requires NO sampled game missing a closing quote.
    # Percentage tolerances cannot waive that separate zero-missing bar.
    market_rules_met = missing_closes == 0 and (
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
        "version": VERSION, "status": "NOT_ADMITTED_UNPINNED_B_DRYRUN",
        "source_policy": SOURCE_POLICY, "source_policy_repo_sha256": None,
        "market": market, "bookmaker": "draftkings", "league": "NBA",
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
        "numeric_b_bar_met_UNVERIFIED": bool(
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
            "A/C/D/E and original-source authentication must be separately demonstrated before any admission run.",
        ],
    }
