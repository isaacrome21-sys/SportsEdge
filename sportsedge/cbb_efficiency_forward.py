"""CBB_TORVIK_EFFICIENCY_V1 forward runner — BUILD, NOT FROZEN.

Finding F-1 of the family's freeze package
(research/cbb_torvik_efficiency_screen_20261028/PREREG_FINAL.md):
the DESIGN_PASS construction had no built forward runner. This
module is that build. It changes nothing about the family's state:

  * FREEZE_STATE stays "DRAFT_NOT_IN_FORCE"; the freeze act has not
    happened and this build does not perform it.
  * Every counted entry point refuses with
    CBB_EFFICIENCY_FORWARD_NOT_FROZEN.
  * Every record this build writes carries counted=False and grants
    no validation, forward-clock, or PLAY credit.

What the runner does (NON_COUNTED): price a slate of games from the
morning-of Torvik vintage (reading R-1 — the live route's vintage
for the slate date; the screen's D-1 convention is NOT extended),
with team identity resolved through the admitted crosswalk (PR
#2898), Illinois colleges excluded exactly as the capture scope
excludes them, and entry lines taken from the lane's DK captures.
Rows are priced and recorded ONLY where the design defines the
fields. The design's three recorded gaps (G-1 pick rule, G-2
interval construction, G-3 close validity) were supplied by
Amendment 2 (adopted Oct 30, 2026; pinned below and verified at
construction) and are implemented in
sportsedge.cbb_amendment2_machinery: every record now carries its
Amendment 2 gap, designated side, and pick classification
(PICKED / PASSED / GAP_ZERO) under AMENDMENT_2_S1_PICK_RULE, the
section 2 interval construction is named on the record, and
settlement stamps closes under AMENDMENT_2_S3_CLOSE_VALIDITY
(the close itself is still recorded AS REPORTED on the
settlement path; close validity is judged only inside the
verdict machinery). The verdict machinery exists and is wired
to run_forward_test behind FREEZE_STATE: while the family is
not frozen, run_forward_test refuses NOT_FROZEN exactly as
before -- the refusal is now purely the missing freeze act,
not missing machinery.

Construction and fitted constants live in
sportsedge.cbb_torvik_efficiency_v1 (shared with the team-totals
readout). The construction of record is pinned below and verified
at construction: if the pinned artifacts on disk disagree with the
freeze package's SPEC_HASHES, the runner refuses PIN_MISMATCH.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sportsedge import cbb_amendment2_machinery as amendment2
from sportsedge import cbb_torvik_efficiency_v1 as core
from sportsedge.cbb_torvik_efficiency_v1 import (
    CbbForwardError,
    CbbSlateGame,
    PairedQuote,
    TorvikVintage,
    illinois_excluded,
    load_crosswalk,
    load_vintage,
    model_outputs,
    no_vig_pair,
    parse_ts,
    quote_refusal,
    sha256_file,
    write_entry_records,
)

ENGINE_ID = "CBB_TORVIK_EFFICIENCY_V1"
FAMILY_ID = "CBB_TORVIK_EFFICIENCY_V1"
FORWARD_SCHEMA = "SPORTSEDGE_CBB_EFFICIENCY_FORWARD_ROW_V1"
SETTLEMENT_SCHEMA = "SPORTSEDGE_CBB_EFFICIENCY_FORWARD_SETTLEMENT_V1"
FREEZE_STATE = "DRAFT_NOT_IN_FORCE"
REFUSAL_NOT_FROZEN = "CBB_EFFICIENCY_FORWARD_NOT_FROZEN"
MARKETS = ("SPREAD", "TOTAL")
ROW_ID_MARKETS = {"SPREAD": "spread", "TOTAL": "total"}

PICK_RULE_ID = amendment2.PICK_RULE_ID
INTERVAL_CONSTRUCTION_ID = amendment2.INTERVAL_CONSTRUCTION_ID
CLOSE_RULE_ID = amendment2.CLOSE_RULE_ID

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = _REPO_ROOT / "research" / "cbb_torvik_efficiency_screen_20261028"

# Pins from the freeze package's SPEC_HASHES.txt (PR #2891/#2898).
# The freeze act re-pins the forward artifacts; until then these are
# the construction-of-record pins this build verifies.
EXPECTED_PINS = {
    "construction_of_record_sha256": (
        _PACKAGE_DIR / "run_screen_attempt4.py",
        "75479ea14b2ab4ef954bd4cde629a2d00e24efea173ac61c695482890dd4c45e"),
    "design_sha256": (
        _REPO_ROOT / "research" / "nba_cbb_activation_20261028"
        / "CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md",
        "cacbee09e1ea53c68888e5b7be3c2d61cd99def6eaba9980c0236e89daccb2fd"),
    "amendment_1_sha256": (
        _REPO_ROOT / "research" / "nba_cbb_activation_20261028"
        / "AMENDMENT_1.md",
        "c3ef6f8235cf7f996f8daf7199fe4f89a78a4ec39bfe26719e644b50d54230c0"),
    "amendment_2_sha256": (
        _REPO_ROOT / "research" / "nba_cbb_activation_20261028"
        / "AMENDMENT_2_DRAFT.md",
        amendment2.AMENDMENT_2_SHA256),
    "crosswalk_sha256": (
        _REPO_ROOT / "research" / "cbb_identity_crosswalk_20261028"
        / "crosswalk.json",
        "6cf6b033e5bc208d4bb65e52064aa1afa4468b12386e5dc7f547f7ebcfaf9096"),
    "capture_scope_sha256": (
        _REPO_ROOT / "sportsedge" / "cbb_capture_scope.py",
        "22c8f6773a6357e2b3282ff310b8f83d9ce79017e6adbda76d629302e9b23753"),
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _row_id(slate_date: str, espn_event_id: str, market: str) -> str:
    return f"{slate_date}:{espn_event_id}:{ROW_ID_MARKETS[market]}"


class CbbEfficiencyForwardRunner:
    """Prices CBB_TORVIK_EFFICIENCY_V1 slates in NON_COUNTED mode."""

    def __init__(self, *, repo_root=None) -> None:
        root = Path(repo_root) if repo_root is not None else _REPO_ROOT
        package = root / "research" / "cbb_torvik_efficiency_screen_20261028"
        paths = {
            "construction_of_record_sha256": (
                package / "run_screen_attempt4.py",
                EXPECTED_PINS["construction_of_record_sha256"][1]),
            "design_sha256": (
                root / "research" / "nba_cbb_activation_20261028"
                / "CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md",
                EXPECTED_PINS["design_sha256"][1]),
            "amendment_1_sha256": (
                root / "research" / "nba_cbb_activation_20261028"
                / "AMENDMENT_1.md",
                EXPECTED_PINS["amendment_1_sha256"][1]),
            "amendment_2_sha256": (
                root / "research" / "nba_cbb_activation_20261028"
                / "AMENDMENT_2_DRAFT.md",
                EXPECTED_PINS["amendment_2_sha256"][1]),
            "crosswalk_sha256": (
                root / "research" / "cbb_identity_crosswalk_20261028"
                / "crosswalk.json",
                EXPECTED_PINS["crosswalk_sha256"][1]),
            "capture_scope_sha256": (
                root / "sportsedge" / "cbb_capture_scope.py",
                EXPECTED_PINS["capture_scope_sha256"][1]),
        }
        pins: dict[str, str] = {}
        for key, (path, expected) in paths.items():
            if not path.is_file():
                raise CbbForwardError(
                    "PIN_MISMATCH", f"pinned artifact missing: {path}")
            actual = sha256_file(path)
            if actual != expected:
                raise CbbForwardError(
                    "PIN_MISMATCH",
                    f"{path.name} sha256 {actual} != package pin "
                    f"{expected}")
            pins[key] = actual
        pins["prereg_final_sha256"] = sha256_file(
            package / "PREREG_FINAL.md")
        pins["shared_construction_module_sha256"] = sha256_file(
            Path(core.__file__))
        pins["runner_sha256"] = sha256_file(Path(__file__))
        self.pins = pins
        self.crosswalk_path = paths["crosswalk_sha256"][0]

    # --------------------------------------------------------------
    # counted entry points — refused while NOT FROZEN
    # --------------------------------------------------------------

    def price_counted_slate(self, *args, **kwargs):
        raise CbbForwardError(
            REFUSAL_NOT_FROZEN,
            "the freeze act has not happened; counted pricing is "
            "refused (this build prices NON_COUNTED only)")

    def run_forward_test(self, records=None, finals=None,
                         closes=None, *, k_at_verdict=None,
                         k_at_freeze=None,
                         review_already_recorded=False,
                         missing_offer=None):
        """The family's single verdict review (Amendment 2
        machinery, sportsedge.cbb_amendment2_machinery).

        Refuses NOT_FROZEN while FREEZE_STATE is not FROZEN: the
        machinery is built and wired, but no review may run --
        and no row may count -- before the freeze act. The freeze
        act flips the state and supplies k from its own act.
        """
        if FREEZE_STATE != "FROZEN":
            raise CbbForwardError(
                REFUSAL_NOT_FROZEN,
                "no forward test can run before the freeze act; "
                "the Amendment 2 verdict machinery is built and "
                "wired but the family is not frozen")
        if records is None or finals is None or closes is None \
                or k_at_verdict is None:
            raise CbbForwardError(
                "FORM_INVALID",
                "run_forward_test requires records, finals, closes "
                "and k_at_verdict")
        return amendment2.evaluate_forward_test(
            records, finals, closes, family_id=FAMILY_ID,
            k_at_freeze=k_at_freeze, k_at_verdict=k_at_verdict,
            review_already_recorded=review_already_recorded,
            missing_offer=missing_offer)

    # --------------------------------------------------------------
    # NON_COUNTED pricing
    # --------------------------------------------------------------

    def price_slate(self, slate_date: str, games: list[CbbSlateGame],
                    *, vintage: TorvikVintage, now: datetime,
                    counted: bool = False) -> dict:
        if counted:
            raise CbbForwardError(
                REFUSAL_NOT_FROZEN,
                "counted=True refused: the family is not frozen")
        if now.tzinfo is None:
            raise CbbForwardError("FORM_INVALID",
                                  "now must be timezone-aware")
        if vintage.slate_date != slate_date:
            raise CbbForwardError(
                "TORVIK_VINTAGE_DATE_MISMATCH",
                f"vintage is for {vintage.slate_date}, slate date is "
                f"{slate_date}")
        crosswalk = load_crosswalk(self.crosswalk_path)
        records: list[dict] = []
        refusals: list[dict] = []
        seen_games: set[str] = set()
        seen_rows: set[str] = set()
        for game in games:
            if game.slate_date != slate_date:
                refusals.append({
                    "espn_event_id": game.espn_event_id, "market": None,
                    "reason": "SLATE_DATE_MISMATCH"})
                continue
            if game.espn_event_id in seen_games:
                refusals.append({
                    "espn_event_id": game.espn_event_id, "market": None,
                    "reason": "DUPLICATE_GAME"})
                continue
            seen_games.add(game.espn_event_id)
            tip = parse_ts(game.tip_utc)
            if tip is None or tip.tzinfo is None:
                refusals.append({
                    "espn_event_id": game.espn_event_id, "market": None,
                    "reason": "FORM_INVALID"})
                continue
            if now >= tip:
                refusals.append({
                    "espn_event_id": game.espn_event_id, "market": None,
                    "reason": "ENTRY_NOT_PRE_EVENT"})
                continue
            away_team = crosswalk.for_espn_id(game.away_espn_id)
            home_team = crosswalk.for_espn_id(game.home_espn_id)
            if away_team is None or home_team is None:
                refusals.append({
                    "espn_event_id": game.espn_event_id, "market": None,
                    "reason": "IDENTITY_UNVERIFIED"})
                continue
            if (illinois_excluded(away_team, game.away_espn_id,
                                  game.institution_state_away)
                    or illinois_excluded(home_team, game.home_espn_id,
                                         game.institution_state_home)):
                refusals.append({
                    "espn_event_id": game.espn_event_id, "market": None,
                    "reason": "ILLINOIS_COLLEGE_EXCLUDED"})
                continue
            away_ratings = vintage.by_team.get(away_team.torvik_name)
            home_ratings = vintage.by_team.get(home_team.torvik_name)
            if away_ratings is None or home_ratings is None:
                refusals.append({
                    "espn_event_id": game.espn_event_id, "market": None,
                    "reason": "TORVIK_TEAM_NOT_CARRIED"})
                continue
            outputs = model_outputs(
                home_ratings, away_ratings, vintage.league_mean_eff,
                vintage.league_mean_tempo, game.neutral_site)
            for market in MARKETS:
                row_id = _row_id(slate_date, game.espn_event_id, market)
                pair = game.entry_quotes.get(market)
                reason = quote_refusal(
                    pair, positive_line=(market == "TOTAL"), tip=tip)
                if reason is not None:
                    refusals.append({
                        "espn_event_id": game.espn_event_id,
                        "market": market, "reason": reason})
                    continue
                if row_id in seen_rows:
                    refusals.append({
                        "espn_event_id": game.espn_event_id,
                        "market": market, "reason": "DUPLICATE_ROW"})
                    continue
                seen_rows.add(row_id)
                records.append(self._record(
                    slate_date, game, market, pair, away_team,
                    home_team, outputs, vintage, now, row_id))
        return {
            "schema": FORWARD_SCHEMA,
            "engine_id": ENGINE_ID,
            "freeze_state": FREEZE_STATE,
            "counted": False,
            "slate_date": slate_date,
            "priced_at": now.astimezone(timezone.utc).isoformat(),
            "records": records,
            "refusals": refusals,
        }

    def _record(self, slate_date, game, market, pair: PairedQuote,
                away_team, home_team, outputs, vintage, now,
                row_id) -> dict:
        prob_a, prob_b = no_vig_pair(pair.side_a_price, pair.side_b_price)
        if market == "SPREAD":
            sides = {"side_a": "AWAY", "side_b": "HOME"}
            model_line = outputs["model_margin_home_candidate"]
            model_line_baseline = outputs[
                "model_margin_home_baseline_simple"]
            line_semantics = (
                "line is the away team's spread as captured; model "
                "lines are home-minus-away margins")
        else:
            sides = {"side_a": "OVER", "side_b": "UNDER"}
            model_line = outputs["model_total_candidate"]
            model_line_baseline = outputs["model_total_baseline_simple"]
            line_semantics = "line is the game total as captured"
        # Amendment 2 section 1: the gap is the model value minus
        # the market value -- for SPREAD the captured away spread
        # IS the market-implied margin M_mkt, so one subtraction
        # serves both markets. Designation happens at pricing
        # time, before tip, and is committed on the record
        # (section 1.5).
        designation = amendment2.designate_pick(
            market, model_line, float(pair.line))
        return {
            "schema": FORWARD_SCHEMA,
            "row_id": row_id,
            "engine_id": ENGINE_ID,
            "model_version": (
                f"cbb_torvik_efficiency_v1@sha256:"
                f"{self.pins['construction_of_record_sha256'][:12]}"),
            "freeze_state": FREEZE_STATE,
            "counted": False,
            "label": "NON_COUNTED",
            "verified_play": False,
            "slate_date": slate_date,
            "game_date": slate_date,
            "espn_event_id": game.espn_event_id,
            "away_team": away_team.canonical_id,
            "home_team": home_team.canonical_id,
            "away_espn_id": game.away_espn_id,
            "home_espn_id": game.home_espn_id,
            "neutral_site": bool(game.neutral_site),
            "tip_utc": game.tip_utc,
            "market": market,
            "line_semantics": line_semantics,
            **sides,
            "line": float(pair.line),
            "side_a_price": pair.side_a_price,
            "side_b_price": pair.side_b_price,
            "side_a_captured_at": pair.side_a_captured_at,
            "side_b_captured_at": pair.side_b_captured_at,
            "capture_source": pair.capture_source,
            "no_vig_prob_side_a": prob_a,
            "no_vig_prob_side_b": prob_b,
            "model_margin_home_candidate": outputs[
                "model_margin_home_candidate"],
            "model_total_candidate": outputs["model_total_candidate"],
            "model_margin_home_baseline_simple": outputs[
                "model_margin_home_baseline_simple"],
            "model_total_baseline_simple": outputs[
                "model_total_baseline_simple"],
            "expected_points_away_candidate": outputs[
                "expected_points_away_candidate"],
            "expected_points_home_candidate": outputs[
                "expected_points_home_candidate"],
            "expected_points_away_baseline_simple": outputs[
                "expected_points_away_baseline_simple"],
            "expected_points_home_baseline_simple": outputs[
                "expected_points_home_baseline_simple"],
            "home_court_term_candidate": outputs[
                "home_court_term_candidate"],
            "home_court_constant_baseline_simple": outputs[
                "home_court_constant_baseline_simple"],
            "model_spread_or_total": model_line,
            "baseline_spread_or_total": model_line_baseline,
            # Amendment 2 section 1 (G-1, supplied by the adopted
            # amendment): gap, designated side, and classification
            # are computed at pricing time and committed here.
            "gap": designation["gap"],
            "designated_side": designation["designated_side"],
            "classification": designation["classification"],
            "pick": (designation["designated_side"]
                     if designation["classification"] == "PICKED"
                     else None),
            "pick_threshold": designation["threshold"],
            "pick_rule": PICK_RULE_ID,
            "interval_construction": INTERVAL_CONSTRUCTION_ID,
            "close_rule": CLOSE_RULE_ID,
            "seed": core.SEED,
            "priced_at": now.astimezone(timezone.utc).isoformat(),
            "torvik_vintage_date": vintage.slate_date,
            "torvik_vintage_sha256": vintage.sha256,
            "torvik_vintage_route": "live_morning_pull_R-1",
            "league_mean_eff": vintage.league_mean_eff,
            "league_mean_tempo": vintage.league_mean_tempo,
            **self.pins,
        }

    # --------------------------------------------------------------
    # settlement — a separate path from pricing; NON_COUNTED here
    # --------------------------------------------------------------

    def settle_records(self, records: list[dict], finals: dict,
                       closes: dict | None = None) -> list[dict]:
        """Attach finals and accuracy errors to priced records.

        ``finals`` maps espn_event_id -> {"home_points", "away_points",
        "void"}. ``closes`` maps row_id -> the final capture's quote
        AS REPORTED; on this NON_COUNTED settlement path no close is
        excluded or aged out — the close block is recorded under
        the Amendment 2 section 3 rule id, and close validity is
        judged only inside the verdict machinery
        (run_forward_test), never here.
        """
        closes = closes or {}
        settled: list[dict] = []
        for record in records:
            final = finals.get(record["espn_event_id"])
            out = {
                "schema": SETTLEMENT_SCHEMA,
                "row_id": record["row_id"],
                "engine_id": ENGINE_ID,
                "freeze_state": FREEZE_STATE,
                "counted": False,
                "espn_event_id": record["espn_event_id"],
                "market": record["market"],
                "close_rule": CLOSE_RULE_ID,
            }
            close = closes.get(record["row_id"])
            out["close"] = close
            out["close_supplied"] = close is not None
            if final is None:
                out["settlement"] = "RESULT_UNAVAILABLE"
                settled.append(out)
                continue
            if final.get("void"):
                out["settlement"] = "VOID"
                settled.append(out)
                continue
            home_pts = int(final["home_points"])
            away_pts = int(final["away_points"])
            actual_margin = home_pts - away_pts
            actual_total = home_pts + away_pts
            if record["market"] == "SPREAD":
                model_value = record["model_margin_home_candidate"]
                base_value = record["model_margin_home_baseline_simple"]
                actual_value = actual_margin
            else:
                model_value = record["model_total_candidate"]
                base_value = record["model_total_baseline_simple"]
                actual_value = actual_total
            out.update({
                "settlement": "GRADED",
                "home_points": home_pts,
                "away_points": away_pts,
                "actual_margin_home": actual_margin,
                "actual_total": actual_total,
                "abs_error_candidate": abs(model_value - actual_value),
                "abs_error_baseline_simple": abs(
                    base_value - actual_value),
            })
            settled.append(out)
        return settled


def games_from_board(board: dict, fixtures: dict) -> list[CbbSlateGame]:
    """Build slate games from a shared-intake board dict plus a
    fixture identity table.

    ``board`` is the shape produced by the shared intake parser
    (SharedBoard.to_dict()): each game carries away/home display
    names, a per-game captured_at, and markets named SPREAD / TOTAL
    with line/price_a/price_b. ``fixtures`` maps the board's
    "AWAY@HOME" display-name key to the fixture identity
    {espn_event_id, away_espn_id, home_espn_id, neutral_site,
    tip_utc, slate_date}. Identity NEVER comes from the board: a
    board game with no fixture entry is skipped here and therefore
    never priced.

    NOTE (named in BUILD_RECORD): the shared parser has no CBB
    adapter yet — ADAPTERS covers MLB/NFL/CFB/NBA/NHL — so no live
    [CBB LINES] body can be parsed until that adapter lands (the
    Nov 1 pre-check workstream). This helper consumes the parser's
    OUTPUT SHAPE, exactly as the frozen NFL runner consumes its
    driver's parsed captures; it does not parse issue text itself.
    """
    games: list[CbbSlateGame] = []
    for entry in board.get("games", []):
        key = f"{entry.get('away')}@{entry.get('home')}"
        fixture = fixtures.get(key)
        if fixture is None:
            continue
        captured_at = entry.get("captured_at") or board.get(
            "board_captured_at")
        quotes: dict[str, PairedQuote] = {}
        for market_entry in entry.get("markets", []):
            name = market_entry.get("market")
            if name not in MARKETS:
                continue
            quotes[name] = PairedQuote(
                line=market_entry.get("line"),
                side_a_price=market_entry.get("price_a"),
                side_b_price=market_entry.get("price_b"),
                side_a_captured_at=captured_at,
                side_b_captured_at=captured_at,
                capture_source=entry.get("capture_source",
                                         "DK_CAPTURE"))
        games.append(CbbSlateGame(
            espn_event_id=str(fixture["espn_event_id"]),
            slate_date=str(fixture["slate_date"]),
            away_espn_id=str(fixture["away_espn_id"]),
            home_espn_id=str(fixture["home_espn_id"]),
            neutral_site=bool(fixture["neutral_site"]),
            tip_utc=str(fixture["tip_utc"]),
            entry_quotes=quotes,
            institution_state_away=fixture.get("institution_state_away"),
            institution_state_home=fixture.get("institution_state_home")))
    return games


__all__ = [
    "CLOSE_RULE_ID",
    "CbbEfficiencyForwardRunner",
    "CbbForwardError",
    "CbbSlateGame",
    "ENGINE_ID",
    "FAMILY_ID",
    "FREEZE_STATE",
    "INTERVAL_CONSTRUCTION_ID",
    "MARKETS",
    "PICK_RULE_ID",
    "PairedQuote",
    "REFUSAL_NOT_FROZEN",
    "games_from_board",
    "load_vintage",
    "write_entry_records",
]
