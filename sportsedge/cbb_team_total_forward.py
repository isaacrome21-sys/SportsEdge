"""CBB team-totals forward runner — BUILD, NOT FROZEN.

The team-totals family (PR #2892;
research/cbb_team_totals_screen_20261028/PREREG_FINAL.md) is a
READOUT of CBB_TORVIK_EFFICIENCY_V1: the expected team points of the
parent construction ARE the team-total forecasts, home and away.
There is NO second model. This module is the family's forward
runner — finding F-1 of its freeze package — built on the shared
core (sportsedge.cbb_torvik_efficiency_v1) and the parent family's
runner discipline (sportsedge.cbb_efficiency_forward). It changes
nothing about the family's state:

  * FREEZE_STATE stays "DRAFT_NOT_IN_FORCE"; the freeze act has not
    happened and this build does not perform it.
  * Every counted entry point refuses with
    CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN.
  * Every record carries counted=False and grants no validation,
    forward-clock, or PLAY credit.

Terms inherited and honored here (the package's own readings):

  * Forward accuracy leg is against the SIMPLE baseline's team
    points ONLY (package answer A-1): no naive leg is recorded
    forward, even though the screen carried one.
  * Forward input is reading R-1, identical to the parent: the
    morning-of live-route Torvik vintage for the slate date.
  * The recorded gaps are stamped, never filled: G-1 (no pick rule
    -> classification="PICK_RULE_UNDEFINED", pick=None), G-2 (no
    forward interval -> no verdict machinery), G-3 (no
    close-validity rule -> closes recorded AS REPORTED under
    close_rule="CLOSE_RULE_UNDEFINED_GAP_G3").
  * Illinois colleges are excluded exactly as the capture scope
    excludes them; identity resolves through the admitted crosswalk.

One record per team per game: market TEAM_TOTAL with the subject
team named, priced from the capture's TEAM_TOTAL_AWAY /
TEAM_TOTAL_HOME sections (the capture-scope module's section
names).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
FAMILY_ID = "CBB_TORVIK_EFFICIENCY_V1_TEAM_TOTALS"
FORWARD_SCHEMA = "SPORTSEDGE_CBB_TEAM_TOTAL_FORWARD_ROW_V1"
SETTLEMENT_SCHEMA = "SPORTSEDGE_CBB_TEAM_TOTAL_FORWARD_SETTLEMENT_V1"
FREEZE_STATE = "DRAFT_NOT_IN_FORCE"
REFUSAL_NOT_FROZEN = "CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN"
MARKET = "TEAM_TOTAL"
SECTIONS = ("TEAM_TOTAL_AWAY", "TEAM_TOTAL_HOME")

GAP_PICK_RULE = "PICK_RULE_UNDEFINED"
GAP_INTERVAL = "INTERVAL_CONSTRUCTION_UNDEFINED_GAP_G2"
GAP_CLOSE_RULE = "CLOSE_RULE_UNDEFINED_GAP_G3"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = _REPO_ROOT / "research" / "cbb_team_totals_screen_20261028"

# Pins from the freeze package's SPEC_HASHES.txt (PR #2892/#2898).
EXPECTED_PINS = {
    "construction_of_record_sha256": (
        _PACKAGE_DIR / "cbb_team_totals.py",
        "ac01327a4ed3bb9a37f03e7a9391d2a0918d4f022c86de42bb841a9f15044989"),
    "design_sha256": (
        _REPO_ROOT / "research" / "nba_cbb_activation_20261028"
        / "CBB_TEAM_TOTALS_1H_DESIGN.md",
        "d206e74a203d50778cc461b4476b2f9f31d4826c3e989ec44b9bb212c486aaac"),
    "parent_design_sha256": (
        _REPO_ROOT / "research" / "nba_cbb_activation_20261028"
        / "CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md",
        "cacbee09e1ea53c68888e5b7be3c2d61cd99def6eaba9980c0236e89daccb2fd"),
    "amendment_1_sha256": (
        _REPO_ROOT / "research" / "nba_cbb_activation_20261028"
        / "AMENDMENT_1.md",
        "c3ef6f8235cf7f996f8daf7199fe4f89a78a4ec39bfe26719e644b50d54230c0"),
    "crosswalk_sha256": (
        _REPO_ROOT / "research" / "cbb_identity_crosswalk_20261028"
        / "crosswalk.json",
        "6cf6b033e5bc208d4bb65e52064aa1afa4468b12386e5dc7f547f7ebcfaf9096"),
    "capture_scope_sha256": (
        _REPO_ROOT / "sportsedge" / "cbb_capture_scope.py",
        "22c8f6773a6357e2b3282ff310b8f83d9ce79017e6adbda76d629302e9b23753"),
}


def _row_id(slate_date: str, espn_event_id: str, canonical_id: str) -> str:
    return f"{slate_date}:{espn_event_id}:team_total:{canonical_id}"


class CbbTeamTotalForwardRunner:
    """Prices the team-totals readout in NON_COUNTED mode."""

    def __init__(self, *, repo_root=None) -> None:
        root = Path(repo_root) if repo_root is not None else _REPO_ROOT
        package = root / "research" / "cbb_team_totals_screen_20261028"
        paths = {
            "construction_of_record_sha256": (
                package / "cbb_team_totals.py",
                EXPECTED_PINS["construction_of_record_sha256"][1]),
            "design_sha256": (
                root / "research" / "nba_cbb_activation_20261028"
                / "CBB_TEAM_TOTALS_1H_DESIGN.md",
                EXPECTED_PINS["design_sha256"][1]),
            "parent_design_sha256": (
                root / "research" / "nba_cbb_activation_20261028"
                / "CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md",
                EXPECTED_PINS["parent_design_sha256"][1]),
            "amendment_1_sha256": (
                root / "research" / "nba_cbb_activation_20261028"
                / "AMENDMENT_1.md",
                EXPECTED_PINS["amendment_1_sha256"][1]),
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

    def run_forward_test(self, *args, **kwargs):
        raise CbbForwardError(
            REFUSAL_NOT_FROZEN,
            "no forward test can run before the freeze act; the "
            "verdict machinery additionally awaits the G-2 interval "
            "act (INTERVAL_CONSTRUCTION_UNDEFINED_GAP_G2)")

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
            subjects = (
                ("TEAM_TOTAL_AWAY", away_team, "AWAY",
                 outputs["expected_points_away_candidate"],
                 outputs["expected_points_away_baseline_simple"]),
                ("TEAM_TOTAL_HOME", home_team, "HOME",
                 outputs["expected_points_home_candidate"],
                 outputs["expected_points_home_baseline_simple"]),
            )
            for section, team, venue, model_pts, base_pts in subjects:
                game_teams = (away_team.canonical_id,
                              home_team.canonical_id)
                row_id = _row_id(slate_date, game.espn_event_id,
                                  team.canonical_id)
                pair = game.entry_quotes.get(section)
                reason = quote_refusal(pair, positive_line=True, tip=tip)
                if reason is not None:
                    refusals.append({
                        "espn_event_id": game.espn_event_id,
                        "market": MARKET, "team": team.canonical_id,
                        "reason": reason})
                    continue
                if row_id in seen_rows:
                    refusals.append({
                        "espn_event_id": game.espn_event_id,
                        "market": MARKET, "team": team.canonical_id,
                        "reason": "DUPLICATE_ROW"})
                    continue
                seen_rows.add(row_id)
                records.append(self._record(
                    slate_date, game, section, venue, team, pair,
                    model_pts, base_pts, outputs, vintage, now, row_id,
                    game_teams))
        return {
            "schema": FORWARD_SCHEMA,
            "engine_id": ENGINE_ID,
            "family_id": FAMILY_ID,
            "freeze_state": FREEZE_STATE,
            "counted": False,
            "slate_date": slate_date,
            "priced_at": now.astimezone(timezone.utc).isoformat(),
            "records": records,
            "refusals": refusals,
        }

    def _record(self, slate_date, game, section, venue, team,
                pair: PairedQuote, model_pts, base_pts, outputs,
                vintage, now, row_id, game_teams) -> dict:
        prob_over, prob_under = no_vig_pair(pair.side_a_price,
                                            pair.side_b_price)
        return {
            "schema": FORWARD_SCHEMA,
            "row_id": row_id,
            "engine_id": ENGINE_ID,
            "family_id": FAMILY_ID,
            "model_version": (
                f"cbb_torvik_efficiency_v1_team_totals@sha256:"
                f"{self.pins['construction_of_record_sha256'][:12]}"),
            "freeze_state": FREEZE_STATE,
            "counted": False,
            "label": "NON_COUNTED",
            "verified_play": False,
            "slate_date": slate_date,
            "game_date": slate_date,
            "espn_event_id": game.espn_event_id,
            "away_team": game_teams[0],
            "home_team": game_teams[1],
            "team": team.canonical_id,
            "team_espn_id": (game.away_espn_id if venue == "AWAY"
                             else game.home_espn_id),
            "venue": venue,
            "capture_section": section,
            "neutral_site": bool(game.neutral_site),
            "tip_utc": game.tip_utc,
            "market": MARKET,
            "side_a": "OVER",
            "side_b": "UNDER",
            "line": float(pair.line),
            "side_a_price": pair.side_a_price,
            "side_b_price": pair.side_b_price,
            "side_a_captured_at": pair.side_a_captured_at,
            "side_b_captured_at": pair.side_b_captured_at,
            "capture_source": pair.capture_source,
            "no_vig_prob_over": prob_over,
            "no_vig_prob_under": prob_under,
            "model_team_points_candidate": model_pts,
            "model_team_points_baseline_simple": base_pts,
            # A-1: the forward accuracy leg names the simple baseline
            # ONLY. No naive value is computed or recorded forward.
            "forward_baselines": ["SIMPLE_RATINGS"],
            "home_court_term_candidate": outputs[
                "home_court_term_candidate"],
            "home_court_constant_baseline_simple": outputs[
                "home_court_constant_baseline_simple"],
            "classification": GAP_PICK_RULE,
            "pick": None,
            "pick_rule": GAP_PICK_RULE,
            "interval_construction": GAP_INTERVAL,
            "close_rule": GAP_CLOSE_RULE,
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
    # settlement — separate from pricing; NON_COUNTED here
    # --------------------------------------------------------------

    def settle_records(self, records: list[dict], finals: dict,
                       closes: dict | None = None) -> list[dict]:
        closes = closes or {}
        settled: list[dict] = []
        for record in records:
            final = finals.get(record["espn_event_id"])
            out = {
                "schema": SETTLEMENT_SCHEMA,
                "row_id": record["row_id"],
                "engine_id": ENGINE_ID,
                "family_id": FAMILY_ID,
                "freeze_state": FREEZE_STATE,
                "counted": False,
                "espn_event_id": record["espn_event_id"],
                "market": MARKET,
                "team": record["team"],
                "close_rule": GAP_CLOSE_RULE,
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
            actual = home_pts if record["venue"] == "HOME" else away_pts
            out.update({
                "settlement": "GRADED",
                "home_points": home_pts,
                "away_points": away_pts,
                "actual_team_points": actual,
                "abs_error_candidate": abs(
                    record["model_team_points_candidate"] - actual),
                "abs_error_baseline_simple": abs(
                    record["model_team_points_baseline_simple"]
                    - actual),
            })
            settled.append(out)
        return settled


def games_from_board(board: dict, fixtures: dict) -> list[CbbSlateGame]:
    """Build slate games from a shared-intake board dict plus a
    fixture identity table, for the team-totals sections.

    The board's TEAM_TOTAL markets carry a subject team (the shared
    parser's team field); they map to the capture sections
    TEAM_TOTAL_AWAY / TEAM_TOTAL_HOME by the fixture's identity —
    never by display-name matching at pricing time. See the parent
    runner's games_from_board for the no-CBB-adapter note.
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
            if market_entry.get("market") != "TEAM_TOTAL":
                continue
            subject = market_entry.get("team")
            if subject == entry.get("away"):
                section = "TEAM_TOTAL_AWAY"
            elif subject == entry.get("home"):
                section = "TEAM_TOTAL_HOME"
            else:
                continue
            quotes[section] = PairedQuote(
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
    "CbbForwardError",
    "CbbSlateGame",
    "CbbTeamTotalForwardRunner",
    "ENGINE_ID",
    "FAMILY_ID",
    "FREEZE_STATE",
    "GAP_CLOSE_RULE",
    "GAP_INTERVAL",
    "GAP_PICK_RULE",
    "MARKET",
    "PairedQuote",
    "REFUSAL_NOT_FROZEN",
    "games_from_board",
    "load_vintage",
    "write_entry_records",
]
