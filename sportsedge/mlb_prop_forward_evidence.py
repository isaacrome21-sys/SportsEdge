"""Prospective MLB prop evidence capture and settlement primitives.

This lane collects immutable observations only. It never creates Model_P,
calibration, promotion, staking, Truth Gate, or OFFICIAL authority. A final
settlement is eligible only when a pregame source receipt was captured before
scheduled first pitch; otherwise the observation must remain missed/blocked.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from sportsedge.prop_evidence import EVIDENCE_GROUPS, expected_market_identities

MLB_LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
FINAL_ABSTRACT_STATES = frozenset({"FINAL"})
PREGAME_ABSTRACT_STATES = frozenset({"PREVIEW"})
AUTHORITY = "EVIDENCE_ONLY_NOT_MODEL_P_NOT_TRUTH_GATE_NOT_OFFICIAL"


class MlbPropForwardEvidenceError(ValueError):
    pass


def _parse_utc(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MlbPropForwardEvidenceError(f"invalid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MlbPropForwardEvidenceError(f"timestamp must be offset-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def source_url(game_pk: int | str) -> str:
    return MLB_LIVE_FEED_URL.format(game_pk=int(game_pk))


def _game_meta(feed: Mapping[str, Any]) -> tuple[int, datetime, str, str]:
    if not isinstance(feed, Mapping):
        raise MlbPropForwardEvidenceError("feed must be an object")
    game_data = feed.get("gameData")
    if not isinstance(game_data, Mapping):
        raise MlbPropForwardEvidenceError("feed missing gameData")
    game = game_data.get("game")
    status = game_data.get("status")
    date_time = game_data.get("datetime")
    if not isinstance(game, Mapping) or not isinstance(status, Mapping) or not isinstance(date_time, Mapping):
        raise MlbPropForwardEvidenceError("feed missing game/status/datetime metadata")
    game_pk = game.get("pk")
    if game_pk in (None, ""):
        game_pk = feed.get("gamePk")
    try:
        game_pk_int = int(game_pk)
    except (TypeError, ValueError) as exc:
        raise MlbPropForwardEvidenceError("feed missing numeric gamePk") from exc
    scheduled = _parse_utc(date_time.get("dateTime"))
    abstract = str(status.get("abstractGameState") or "").strip().upper()
    detailed = str(status.get("detailedState") or "").strip()
    if not abstract:
        raise MlbPropForwardEvidenceError("feed missing abstract game state")
    return game_pk_int, scheduled, abstract, detailed


def build_pregame_receipt(*, feed: Mapping[str, Any], captured_at_utc: str) -> dict[str, Any]:
    game_pk, scheduled, abstract, detailed = _game_meta(feed)
    captured = _parse_utc(captured_at_utc)
    if captured >= scheduled:
        raise MlbPropForwardEvidenceError("BLOCKED_CAPTURE_AT_OR_AFTER_SCHEDULED_START")
    if abstract not in PREGAME_ABSTRACT_STATES:
        raise MlbPropForwardEvidenceError(f"BLOCKED_NOT_PREGAME:{abstract}")
    digest = canonical_sha256(feed)
    return {
        "schema_version": 1,
        "status": "CAPTURED",
        "authority": AUTHORITY,
        "game_pk": game_pk,
        "source_url": source_url(game_pk),
        "source_sha256": digest,
        "captured_at_utc": _iso_utc(captured),
        "scheduled_start_utc": _iso_utc(scheduled),
        "source_abstract_state": abstract,
        "source_detailed_state": detailed,
    }


def missed_receipt(*, feed: Mapping[str, Any], observed_at_utc: str, reason: str) -> dict[str, Any]:
    game_pk, scheduled, abstract, detailed = _game_meta(feed)
    observed = _parse_utc(observed_at_utc)
    return {
        "schema_version": 1,
        "status": "MISSED_OR_BLOCKED",
        "authority": AUTHORITY,
        "reason": str(reason),
        "game_pk": game_pk,
        "source_url": source_url(game_pk),
        "source_sha256": canonical_sha256(feed),
        "observed_at_utc": _iso_utc(observed),
        "scheduled_start_utc": _iso_utc(scheduled),
        "source_abstract_state": abstract,
        "source_detailed_state": detailed,
    }


def _all_plays(feed: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    live_data = feed.get("liveData")
    plays_obj = live_data.get("plays") if isinstance(live_data, Mapping) else None
    plays = plays_obj.get("allPlays") if isinstance(plays_obj, Mapping) else None
    if not isinstance(plays, list):
        raise MlbPropForwardEvidenceError("final feed missing liveData.plays.allPlays")
    return [play for play in plays if isinstance(play, Mapping)]


def _player_rows(feed: Mapping[str, Any], stat_name: str) -> list[dict[str, Any]]:
    live_data = feed.get("liveData")
    boxscore = live_data.get("boxscore") if isinstance(live_data, Mapping) else None
    teams = boxscore.get("teams") if isinstance(boxscore, Mapping) else None
    if not isinstance(teams, Mapping):
        raise MlbPropForwardEvidenceError("final feed missing boxscore teams")
    rows: list[dict[str, Any]] = []
    for side in ("away", "home"):
        team = teams.get(side)
        players = team.get("players") if isinstance(team, Mapping) else None
        if not isinstance(players, Mapping):
            continue
        for player in players.values():
            if not isinstance(player, Mapping):
                continue
            person = player.get("person")
            stats = player.get("stats")
            stat = stats.get(stat_name) if isinstance(stats, Mapping) else None
            if not isinstance(person, Mapping) or not isinstance(stat, Mapping):
                continue
            player_id = person.get("id")
            try:
                player_id = int(player_id)
            except (TypeError, ValueError):
                continue
            rows.append({
                "player_id": player_id,
                "name": str(person.get("fullName") or ""),
                "team_side": side,
                "stats": dict(stat),
            })
    return sorted(rows, key=lambda row: (row["team_side"], row["player_id"]))


def _hitter_pa(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    counts: dict[tuple[int, str], int] = {}
    names: dict[int, str] = {}
    for play in _all_plays(feed):
        matchup = play.get("matchup")
        batter = matchup.get("batter") if isinstance(matchup, Mapping) else None
        about = play.get("about")
        if not isinstance(batter, Mapping):
            continue
        batter_id = batter.get("id")
        try:
            batter_id = int(batter_id)
        except (TypeError, ValueError):
            continue
        half = str(about.get("halfInning") or "").lower() if isinstance(about, Mapping) else ""
        team_side = "away" if half == "top" else "home" if half == "bottom" else "unknown"
        counts[(batter_id, team_side)] = counts.get((batter_id, team_side), 0) + 1
        names[batter_id] = str(batter.get("fullName") or names.get(batter_id, ""))
    return [
        {
            "player_id": player_id,
            "name": names.get(player_id, ""),
            "team_side": team_side,
            "plate_appearances": plate_appearances,
        }
        for (player_id, team_side), plate_appearances in sorted(counts.items())
    ]


def _event_type(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, play in enumerate(_all_plays(feed)):
        matchup = play.get("matchup")
        result = play.get("result")
        about = play.get("about")
        batter = matchup.get("batter") if isinstance(matchup, Mapping) else None
        if not isinstance(result, Mapping) or not isinstance(batter, Mapping):
            continue
        batter_id = batter.get("id")
        try:
            batter_id = int(batter_id)
        except (TypeError, ValueError):
            continue
        rows.append({
            "sequence": index,
            "at_bat_index": play.get("atBatIndex"),
            "inning": about.get("inning") if isinstance(about, Mapping) else None,
            "half_inning": about.get("halfInning") if isinstance(about, Mapping) else None,
            "batter_id": batter_id,
            "event": str(result.get("event") or ""),
            "event_type": str(result.get("eventType") or ""),
        })
    return rows


def _run_sequence(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, play in enumerate(_all_plays(feed)):
        about = play.get("about")
        runners = play.get("runners")
        if not isinstance(runners, list):
            continue
        for runner in runners:
            if not isinstance(runner, Mapping):
                continue
            details = runner.get("details")
            movement = runner.get("movement")
            runner_obj = details.get("runner") if isinstance(details, Mapping) else None
            if not isinstance(movement, Mapping) or str(movement.get("end") or "").lower() != "score":
                continue
            if not isinstance(runner_obj, Mapping):
                continue
            runner_id = runner_obj.get("id")
            try:
                runner_id = int(runner_id)
            except (TypeError, ValueError):
                continue
            rows.append({
                "sequence": index,
                "at_bat_index": play.get("atBatIndex"),
                "inning": about.get("inning") if isinstance(about, Mapping) else None,
                "half_inning": about.get("halfInning") if isinstance(about, Mapping) else None,
                "runner_id": runner_id,
            })
    return rows


def _home_run_order(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, play in enumerate(_all_plays(feed)):
        result = play.get("result")
        matchup = play.get("matchup")
        about = play.get("about")
        if not isinstance(result, Mapping) or not isinstance(matchup, Mapping):
            continue
        event_type = str(result.get("eventType") or "").lower()
        event = str(result.get("event") or "").lower()
        if event_type != "home_run" and event != "home run":
            continue
        batter = matchup.get("batter")
        if not isinstance(batter, Mapping):
            continue
        batter_id = batter.get("id")
        try:
            batter_id = int(batter_id)
        except (TypeError, ValueError):
            continue
        rows.append({
            "order": len(rows) + 1,
            "sequence": index,
            "at_bat_index": play.get("atBatIndex"),
            "inning": about.get("inning") if isinstance(about, Mapping) else None,
            "half_inning": about.get("halfInning") if isinstance(about, Mapping) else None,
            "batter_id": batter_id,
        })
    return rows


def _pitcher_workload(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    keys = ("inningsPitched", "outs", "numberOfPitches", "battersFaced", "gamesStarted")
    rows = []
    for player in _player_rows(feed, "pitching"):
        stats = player["stats"]
        if not any(key in stats for key in keys):
            continue
        rows.append({
            "player_id": player["player_id"],
            "name": player["name"],
            "team_side": player["team_side"],
            **{key: stats.get(key) for key in keys},
        })
    return rows


def _pitcher_allowed(feed: Mapping[str, Any]) -> list[dict[str, Any]]:
    keys = ("hits", "runs", "earnedRuns", "homeRuns", "baseOnBalls", "strikeOuts")
    rows = []
    for player in _player_rows(feed, "pitching"):
        stats = player["stats"]
        if not any(key in stats for key in keys):
            continue
        rows.append({
            "player_id": player["player_id"],
            "name": player["name"],
            "team_side": player["team_side"],
            **{key: stats.get(key) for key in keys},
        })
    return rows


def derive_group_observations(feed: Mapping[str, Any]) -> dict[str, Any]:
    observations = {
        "HITTER_PA": _hitter_pa(feed),
        "HITTER_EVENT_TYPE": _event_type(feed),
        "HITTER_RUN_SEQUENCE": _run_sequence(feed),
        "FIRST_HR_ORDERING": _home_run_order(feed),
        "PITCHER_WORKLOAD": _pitcher_workload(feed),
        "PITCHER_EVENT_ALLOWED": _pitcher_allowed(feed),
    }
    if set(observations) != set(EVIDENCE_GROUPS):
        raise MlbPropForwardEvidenceError("internal evidence group mapping mismatch")
    return observations


def build_settlement_receipt(
    *,
    feed: Mapping[str, Any],
    pregame_receipt: Mapping[str, Any],
    settled_at_utc: str,
) -> dict[str, Any]:
    game_pk, scheduled, abstract, detailed = _game_meta(feed)
    settled = _parse_utc(settled_at_utc)
    if abstract not in FINAL_ABSTRACT_STATES:
        raise MlbPropForwardEvidenceError(f"BLOCKED_NOT_FINAL:{abstract}")
    if not isinstance(pregame_receipt, Mapping) or pregame_receipt.get("status") != "CAPTURED":
        raise MlbPropForwardEvidenceError("BLOCKED_MISSING_PREGAME_RECEIPT")
    if int(pregame_receipt.get("game_pk", -1)) != game_pk:
        raise MlbPropForwardEvidenceError("BLOCKED_PREGAME_GAME_ID_MISMATCH")
    captured = _parse_utc(pregame_receipt.get("captured_at_utc"))
    if captured >= scheduled:
        raise MlbPropForwardEvidenceError("BLOCKED_PREGAME_NOT_BEFORE_START")

    observations = derive_group_observations(feed)
    final_source_sha = canonical_sha256(feed)
    groups: dict[str, Any] = {}
    for group in sorted(EVIDENCE_GROUPS):
        observation = observations[group]
        groups[group] = {
            "status": "OBSERVED",
            "evidence_group": group,
            "market_identities": list(expected_market_identities(group)),
            "observation_sha256": canonical_sha256(observation),
            "observation": observation,
        }

    return {
        "schema_version": 1,
        "status": "SETTLED_OBSERVATION_ONLY",
        "authority": AUTHORITY,
        "game_pk": game_pk,
        "source_url": source_url(game_pk),
        "source_sha256": final_source_sha,
        "pregame_source_sha256": str(pregame_receipt.get("source_sha256") or ""),
        "captured_at_utc": _iso_utc(captured),
        "settled_at_utc": _iso_utc(settled),
        "scheduled_start_utc": _iso_utc(scheduled),
        "source_abstract_state": abstract,
        "source_detailed_state": detailed,
        "groups": groups,
    }
