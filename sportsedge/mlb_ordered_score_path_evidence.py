"""MLB ordered scoring path POSTGAME outcome-evidence packet, not forecast.

Final-score alone cannot determine race, first/last-run inning, extra
innings, bottom ninth availability or the first scoring play. Here those
are recovered ONLY from a complete officially ordered run-scoring event
ledger and a separate actually-played half-inning ledger. Any caller
source-attestation flag is not independently authenticated by this code.

No assumption of independent inning outcomes, extra-inning simulation,
model probability or DraftKings market settlement. M50 gates untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

VERSION = "MLB_M50_ORDERED_SCORE_POSTGAME_LABEL_V1"
RACE_RUNGS = (3, 4, 5, 6, 7)
HASH = re.compile(r"^[A-Fa-f0-9]{64}$")
HALF = re.compile(r"^([1-9][0-9]*)_(TOP|BOTTOM)$")


class MLBScoringPathError(ValueError):
    """Strict postgame evidence admission refusal."""


@dataclass(frozen=True)
class MLBScoringPathLabels:
    game_pk: int
    first_run_inning: int | None
    last_run_inning: int | None
    first_scoring_play_runs: int | None
    first_scoring_event_id: str | None
    race_to_runs: dict[int, str]
    final_away_runs: int
    final_home_runs: int
    through_nine_away_runs: int
    through_nine_home_runs: int
    regulation_tied_after_nine: bool
    extra_innings_played: bool
    home_batted_bottom_ninth: bool
    highest_scoring_inning_by_team: dict[str, int]
    team_with_highest_scoring_inning: str
    inning_winner_counts_complete_halves: dict[str, int]
    most_innings_won_status: str
    most_innings_won_team: str | None
    source_path_sha256: str
    version: str = VERSION
    status: str = "POSTGAME_LABEL_CANDIDATE_UNVERIFIED"
    source_verified_independently: bool = False
    market_settlement_verified: bool = False
    eligible: bool = False
    research_only: bool = True
    market_test: str = "NO_MARKET_TEST"
    play_authority: bool = False


def _int(value: Any, field: str, *, minimum=1) -> int:
    if type(value) is not int or value < minimum:
        raise MLBScoringPathError(f"{field}_INTEGER_REQUIRED")
    return value


def _utc(value: Any, field: str):
    if not isinstance(value, str) or not value:
        raise MLBScoringPathError(f"{field}_UTC_REQUIRED")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBScoringPathError(f"{field}_UTC_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBScoringPathError(f"{field}_UTC_OFFSET_REQUIRED")
    return dt.astimezone(timezone.utc)


def _validate_halves(value: Any):
    if not isinstance(value, list) or not value:
        raise MLBScoringPathError("PLAYED_HALF_INNINGS_REQUIRED")
    all_halves = []
    max_inning = 0
    for j, raw in enumerate(value):
        if not isinstance(raw, str):
            raise MLBScoringPathError("INVALID_PLAYED_HALF_IDENTITY")
        match = HALF.fullmatch(raw)
        if match is None:
            raise MLBScoringPathError("INVALID_PLAYED_HALF_IDENTITY")
        inning, side = int(match.group(1)), match.group(2)
        if side == "TOP" and (inning > max_inning):
            max_inning = inning
        expected = (f"{j // 2 + 1}_{'TOP' if j % 2 == 0 else 'BOTTOM'}")
        if raw != expected:
            # Last home batting half may be UNPLAYED. But skipping any
            # earlier bottom is invalid (cannot later play another half).
            raise MLBScoringPathError("PLAYED_HALF_INNING_PATH_NONCONTIGUOUS")
        all_halves.append((inning, side))
    if max_inning < 9 or all_halves[-1][0] < 9 or (
            all_halves[-1][1] not in ("TOP", "BOTTOM")):
        raise MLBScoringPathError("NO_COMPLETED_REGULATION_TOP_NINTH")
    return all_halves


def postgame_score_path_labels(packet: Mapping[str, Any]) -> MLBScoringPathLabels:
    if not isinstance(packet, Mapping):
        raise MLBScoringPathError("SOURCE_SCORE_PATH_PACKET_REQUIRED")
    pk = _int(packet.get("game_pk"), "GAME_PK")
    away_id = _int(packet.get("away_team_id"), "AWAY_TEAM")
    home_id = _int(packet.get("home_team_id"), "HOME_TEAM")
    if away_id == home_id:
        raise MLBScoringPathError("SCORE_PATH_TEAM_IDENTITY_COLLISION")
    if packet.get("final_status") != "FINAL" or (
            packet.get("complete_ordered_score_events") is not True) or (
            packet.get("played_half_ledger_complete") is not True):
        raise MLBScoringPathError("COMPLETE_OFFICIAL_PATH_NOT_ATTESTED")
    start = _utc(packet.get("game_start_utc"), "START")
    finish = _utc(packet.get("game_completed_utc"), "COMPLETED")
    observed = _utc(packet.get("observed_at_utc"), "OBSERVED")
    if not start < finish <= observed:
        raise MLBScoringPathError("OFFICIAL_SCORE_PATH_CHRONOLOGY_INVALID")
    source_sha = packet.get("source_snapshot_sha256")
    if not isinstance(source_sha, str) or not HASH.fullmatch(source_sha):
        raise MLBScoringPathError("OFFICIAL_SCORE_PATH_SOURCE_SHA_REQUIRED")
    played = _validate_halves(packet.get("played_half_innings"))
    max_inning = played[-1][0]
    played_keys = {f"{n}_{h}" for n, h in played}
    count_away = _int(packet.get("final_away_runs"), "FINAL_AWAY_RUNS", minimum=0)
    count_home = _int(packet.get("final_home_runs"), "FINAL_HOME_RUNS", minimum=0)
    if count_away == count_home:
        raise MLBScoringPathError("TERMINAL_MLB_SCORE_CANNOT_TIE")
    events = packet.get("scoring_events")
    if not isinstance(events, list):
        raise MLBScoringPathError("ORDERED_SCORING_EVENTS_REQUIRED")
    expected_count = _int(packet.get("expected_scoring_event_count"),
                          "SOURCE_SCORING_EVENT_COUNT", minimum=0)
    if len(events) != expected_count:
        raise MLBScoringPathError("ORDERED_SCORING_EVENT_COUNT_MISMATCH")
    normalized = []
    totals = {"AWAY": 0, "HOME": 0}
    through9 = {"AWAY": 0, "HOME": 0}
    inning_runs: dict[int, dict[str, int]] = {}
    seen_ids = set()
    last_half_idx = -1
    first = None
    last = None
    race = {n: "NEITHER" for n in RACE_RUNGS}
    for j, raw in enumerate(events, 1):
        if not isinstance(raw, Mapping) or raw.get("game_pk") != pk:
            raise MLBScoringPathError("CROSS_GAME_SCORING_EVENT")
        if raw.get("scoring_event_index") != j:
            raise MLBScoringPathError("OUT_OF_ORDER_SCORING_EVENT_INDEX")
        event_id = raw.get("source_event_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen_ids:
            raise MLBScoringPathError("MISSING_OR_DUPLICATE_SOURCE_SCORING_EVENT")
        seen_ids.add(event_id)
        inning = _int(raw.get("inning"), "SCORING_INNING")
        half = raw.get("half")
        halfkey = f"{inning}_{half}"
        if halfkey not in played_keys:
            raise MLBScoringPathError("EVENT_OUTSIDE_PLAYED_HALF")
        idx = (inning - 1) * 2 + (0 if half == "TOP" else 1)
        if idx < last_half_idx:
            raise MLBScoringPathError("SCORING_EVENTS_REORDERED_ACROSS_HALVES")
        last_half_idx = idx
        team = _int(raw.get("scoring_team_id"), "SCORING_TEAM")
        if team != (away_id if half == "TOP" else home_id):
            raise MLBScoringPathError("SCORING_TEAM_HALF_IDENTITY_MISMATCH")
        run_delta = _int(raw.get("official_runs_scored"), "SCORING_RUN_DELTA")
        side = "AWAY" if half == "TOP" else "HOME"
        totals[side] += run_delta
        if inning <= 9:
            through9[side] += run_delta
        if inning not in inning_runs:
            inning_runs[inning] = {"AWAY": 0, "HOME": 0}
        inning_runs[inning][side] += run_delta
        item = {
            "game_pk": pk, "source_event_id": event_id,
            "scoring_event_index": j, "inning": inning,
            "half": half, "official_runs_scored": run_delta,
            "scoring_team_id": team,
        }
        normalized.append(item)
        if first is None:
            first = item
        last = item
        for rung in RACE_RUNGS:
            if race[rung] == "NEITHER" and totals[side] >= rung:
                race[rung] = side
    if totals["AWAY"] != count_away or totals["HOME"] != count_home:
        raise MLBScoringPathError("SCORING_PLAY_RUNS_DO_NOT_MATCH_FINAL_SCORE")
    extra = max_inning > 9
    tied9 = through9["AWAY"] == through9["HOME"]
    if extra != tied9:
        # A regulation tie without extra innings, or extras before a tie,
        # is not an ordinary completed MLB path.
        raise MLBScoringPathError("EXTRA_INNING_REGULATION_TIE_INVARIANT")
    bottom9 = "9_BOTTOM" in played_keys
    home_before_bottom_ninth = sum(
        counts["HOME"] for inning, counts in inning_runs.items()
        if inning < 9)
    away_after_top_ninth = through9["AWAY"]
    if bottom9 and home_before_bottom_ninth > away_after_top_ninth:
        raise MLBScoringPathError("HOME_LED_AFTER_TOP_NINTH_CANNOT_BAT")
    if not bottom9 and (count_home <= count_away or extra):
        raise MLBScoringPathError("NINTH_HOME_HALF_OMISSION_INVALID")
    highs = {"AWAY": 0, "HOME": 0}
    for inning, counts in inning_runs.items():
        for side in highs:
            highs[side] = max(highs[side], counts[side])
    highest = ("TIE_UNRESOLVED_MARKET_RULE" if highs["AWAY"] == highs["HOME"]
               else ("HOME" if highs["HOME"] > highs["AWAY"] else "AWAY"))
    wins = {"HOME": 0, "AWAY": 0, "TIE": 0}
    for inning in range(1, max_inning + 1):
        if f"{inning}_BOTTOM" not in played_keys:
            continue  # An unplayed bottom is NOT a home zero-run half.
        vals = inning_runs.get(inning, {"HOME": 0, "AWAY": 0})
        winner = ("HOME" if vals["HOME"] > vals["AWAY"] else
                  "AWAY" if vals["AWAY"] > vals["HOME"] else "TIE")
        wins[winner] += 1
    partial = any(f"{i}_BOTTOM" not in played_keys
                  for i in range(1, max_inning + 1))
    if partial:
        most_status, most_winner = "PARTIAL_INNING_SETTLEMENT_UNVERIFIED", None
    else:
        most_status = "RAW_COUNTS_BOOK_RULE_NOT_ADMITTED"
        most_winner = ("HOME" if wins["HOME"] > wins["AWAY"] else
                       "AWAY" if wins["AWAY"] > wins["HOME"] else None)
    digest = hashlib.sha256(json.dumps({
        "version": VERSION, "game_pk": pk,
        "source_sha256": source_sha.lower(),
        "played_halves": packet["played_half_innings"],
        "scoring_events": normalized,
        "final_score": [count_away, count_home],
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return MLBScoringPathLabels(
        game_pk=pk,
        first_run_inning=first["inning"] if first else None,
        last_run_inning=last["inning"] if last else None,
        first_scoring_play_runs=first["official_runs_scored"] if first else None,
        first_scoring_event_id=first["source_event_id"] if first else None,
        race_to_runs=race,
        final_away_runs=count_away, final_home_runs=count_home,
        through_nine_away_runs=through9["AWAY"],
        through_nine_home_runs=through9["HOME"],
        regulation_tied_after_nine=tied9,
        extra_innings_played=extra,
        home_batted_bottom_ninth=bottom9,
        highest_scoring_inning_by_team=highs,
        team_with_highest_scoring_inning=highest,
        inning_winner_counts_complete_halves=wins,
        most_innings_won_status=most_status,
        most_innings_won_team=most_winner,
        source_path_sha256=digest)
