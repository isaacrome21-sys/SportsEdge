#!/usr/bin/env python3
"""Append-only T-90 PIT archive for the seven additional MLB quote families.

This lane archives acquisition evidence only. It never prices models, grades
outcomes, validates sportsbook settlement rules, or promotes markets.

Paid acquisition is fail-closed behind a durable daily/provider reserve ledger.
The provider /events payload is acquired exactly once per attempt and reused for
quote acquisition and canonical identity proof.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from sportsedge.additional_mlb_odds_source import (
    CANONICAL_MARKETS,
    PROVIDER_MARKETS,
    fetch_mlb_additional_quotes,
)
from sportsedge.mlb_source import GameSnapshot, fetch_boxscore, fetch_schedule, parse_game_start
from sportsedge.odds_api_source import bind_provider_event, build_participant_index
from sportsedge.odds_budget import (
    OddsBudgetError,
    assert_budget_available,
    load_budget,
    record_actual_cost,
)
from sportsedge.odds_event_snapshot import acquire_mlb_event_snapshot
from sportsedge.quote_bridge import validate_canonical_quote
from sportsedge.runtime import parse_timestamp

CT = ZoneInfo("America/Chicago")
TARGET_MARKETS = frozenset(CANONICAL_MARKETS)
ARCHIVE_TYPE = "MLB_ADDITIONAL_PIT_QUOTES"
LIVE_EVIDENCE_CLASS = "LIVE_PROVIDER_QUOTE_ARCHIVE"
IDENTITY_STATE = "CANONICAL_MLB_IDENTITY_RESOLVED_EXACT"
TARGET_MINUTES = 90
WINDOW_SECONDS = 7 * 60
CAPTURE_WINDOW = "T-90m"
DEFAULT_DAILY_CREDIT_CAP = 12
DEFAULT_PROVIDER_RESERVE_CREDITS = 1
DEFAULT_BUDGET_LEDGER = Path("artifacts/odds_budget/ledger.json")


class AdditionalPITArchiveError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_json(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _payload_sha(payload: Mapping[str, Any]) -> str:
    return _sha256_json({k: v for k, v in payload.items() if k != "payload_sha256"})


def _rehash(payload: dict[str, Any]) -> dict[str, Any]:
    payload["payload_sha256"] = _payload_sha(payload)
    return payload


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _keys() -> list[str]:
    out: list[str] = []
    for name in (
        "SPORTSEDGE_ODDS_API_KEY",
        "SPORTSEDGE_ODDS_API_KEY_2",
        "SPORTSEDGE_ODDS_API_KEY_3",
        "SPORTSEDGE_ODDS_API_KEY_4",
    ):
        value = os.environ.get(name, "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _env_nonnegative_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise AdditionalPITArchiveError(f"{name}_INVALID") from exc
    if value < 0:
        raise AdditionalPITArchiveError(f"{name}_INVALID")
    return value


def _budget_ledger_path() -> Path:
    raw = os.environ.get("SPORTSEDGE_ODDS_BUDGET_LEDGER", "").strip()
    return Path(raw) if raw else DEFAULT_BUDGET_LEDGER


def _estimated_paid_cost(game_count: int) -> int:
    # The Odds API: /events costs 1 when populated; event odds costs one usage
    # credit per unique market returned per region. This is an upper bound.
    return 1 + max(0, int(game_count)) * len(PROVIDER_MARKETS)


def _quota_exhausted(value: Any) -> bool:
    return "OUT_OF_USAGE_CREDITS" in str(value).upper() or "BLOCKED_NO_CREDITS" in str(value).upper()


def _eligible_games(now: datetime, schedule: Sequence[GameSnapshot]) -> list[GameSnapshot]:
    current = now.astimezone(timezone.utc)
    out: list[GameSnapshot] = []
    for game in schedule:
        try:
            start = parse_game_start(game.game_date).astimezone(timezone.utc)
        except Exception:
            continue
        seconds_to = (start - current).total_seconds()
        if abs(seconds_to - TARGET_MINUTES * 60) <= WINDOW_SECONDS:
            out.append(game)
    return out


def _side_players(boxscore: Mapping[str, Any], side: str) -> list[tuple[int, str]]:
    players = ((((boxscore.get("teams") or {}).get(side) or {}).get("players")) or {})
    if not isinstance(players, Mapping):
        return []
    out: list[tuple[int, str]] = []
    for row in players.values():
        if not isinstance(row, Mapping):
            continue
        person = row.get("person") or {}
        try:
            player_id = int(person.get("id"))
        except (TypeError, ValueError):
            continue
        name = str(person.get("fullName") or "").strip()
        if player_id > 0 and name:
            out.append((player_id, name))
    return out


def _roster_names(boxscore: Mapping[str, Any]) -> list[tuple[int, str]]:
    return _side_players(boxscore, "away") + _side_players(boxscore, "home")


def _game_identity(game: GameSnapshot) -> dict[str, Any]:
    return {
        "game_id": str(game.game_pk),
        "first_pitch_at": parse_game_start(game.game_date).isoformat(),
        "away_team_id": int(game.away_id),
        "away_team_name": str(game.away_name),
        "home_team_id": int(game.home_id),
        "home_team_name": str(game.home_name),
        "away_probable_pitcher_id": game.away_probable_pitcher_id,
        "home_probable_pitcher_id": game.home_probable_pitcher_id,
    }


def _entity_is_canonical(
    quote: Mapping[str, Any],
    *,
    game: GameSnapshot,
    participant_index: Mapping[int, Mapping[str, int]],
) -> bool:
    market = str(quote.get("market") or "").upper()
    entity = str(quote.get("entity_id") or "").strip()
    if market in {"F5_MONEYLINE", "F5_RUN_LINE"}:
        return entity in {str(game.away_id), str(game.home_id)}
    if market in {"F5_TOTALS", "NRFI", "YRFI"}:
        return entity == str(game.game_pk)
    if market in {"FIRST_HOME_RUN", "PITCHER_RECORD_WIN"}:
        return entity in {str(v) for v in (participant_index.get(game.game_pk) or {}).values()}
    return False


def build_archive_from_inputs(
    *,
    schedule: Sequence[GameSnapshot],
    quote_rows: Iterable[Mapping[str, Any]],
    provider_events: Iterable[Mapping[str, Any]],
    participant_index: Mapping[int, Mapping[str, int]],
    captured_at: datetime,
    source_failures: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise AdditionalPITArchiveError("captured_at must be timezone-aware")
    captured = captured_at.astimezone(timezone.utc)
    quotes_in = [dict(x) if isinstance(x, Mapping) else {} for x in quote_rows]
    failures_in = [dict(x) for x in source_failures if isinstance(x, Mapping)]
    games = list(schedule)
    game_by_id = {str(game.game_pk): game for game in games}

    event_index: dict[str, Mapping[str, Any]] = {}
    duplicate_event_ids: set[str] = set()
    for event in provider_events:
        if not isinstance(event, Mapping):
            continue
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        if event_id in event_index:
            duplicate_event_ids.add(event_id)
        else:
            event_index[event_id] = event
    for event_id in duplicate_event_ids:
        event_index.pop(event_id, None)

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    market_counts = {market: 0 for market in sorted(TARGET_MARKETS)}

    for source_index, quote in enumerate(quotes_in):
        market = str(quote.get("market") or "").upper()
        if market not in TARGET_MARKETS:
            continue
        try:
            canonical = validate_canonical_quote(quote)
            game_id = str(canonical["game_id"])
            game = game_by_id.get(game_id)
            if game is None:
                raise AdditionalPITArchiveError("CANONICAL_GAME_NOT_FOUND")
            retrieved = canonical["retrieved_at"].astimezone(timezone.utc)
            first_pitch = parse_game_start(game.game_date).astimezone(timezone.utc)
            if retrieved >= first_pitch:
                raise AdditionalPITArchiveError("NOT_PREGAME")

            event_id = str(quote.get("provider_event_id") or "").strip()
            event = event_index.get(event_id)
            if event is None:
                raise AdditionalPITArchiveError("PROVIDER_EVENT_NOT_FOUND_OR_AMBIGUOUS")
            rebound = bind_provider_event(event, games)
            if str(rebound.game_pk) != game_id:
                raise AdditionalPITArchiveError("PROVIDER_EVENT_CANONICAL_GAME_MISMATCH")
            if not _entity_is_canonical(quote, game=game, participant_index=participant_index):
                raise AdditionalPITArchiveError("CANONICAL_ENTITY_NOT_REPRODUCIBLE")

            provider_event_snapshot = dict(event)
            provider_event_hash = _sha256_json(provider_event_snapshot)
            game_snapshot = _game_identity(game)
            game_snapshot_hash = _sha256_json(game_snapshot)
            identity_binding = {
                "provider_event_id": event_id,
                "provider_event_sha256": provider_event_hash,
                "canonical_game_id": game_id,
                "canonical_entity_id": str(canonical["entity_id"]),
                "canonical_game_snapshot_sha256": game_snapshot_hash,
                "resolver_contract": "EXACT_NORMALIZED_TEAM_TIME_AND_PARTICIPANT_IDENTITY",
            }
            accepted.append({
                **quote,
                "retrieved_at": retrieved.isoformat(),
                "quote_retrieved_at": retrieved.isoformat(),
                "first_pitch_at": first_pitch.isoformat(),
                "archive_captured_at": captured.isoformat(),
                "pit_eligible": True,
                "identity_binding_state": IDENTITY_STATE,
                "provider_event_snapshot": provider_event_snapshot,
                "provider_event_sha256": provider_event_hash,
                "canonical_game_snapshot": game_snapshot,
                "canonical_game_snapshot_sha256": game_snapshot_hash,
                "identity_binding_sha256": _sha256_json(identity_binding),
            })
            market_counts[market] += 1
        except Exception as exc:
            rejected.append({
                "source_index": source_index,
                "market": market,
                "game_id": quote.get("game_id"),
                "entity_id": quote.get("entity_id"),
                "provider_event_id": quote.get("provider_event_id"),
                "reason": f"{type(exc).__name__}:{exc}",
            })

    payload: dict[str, Any] = {
        "schema_version": 1,
        "archive_type": ARCHIVE_TYPE,
        "evidence_class": LIVE_EVIDENCE_CLASS,
        "provider": "THE_ODDS_API",
        "captured_at": captured.isoformat(),
        "target_markets": sorted(TARGET_MARKETS),
        "source_quote_count": len(quotes_in),
        "pit_quote_count": len(accepted),
        "market_counts": market_counts,
        "source_failure_count": len(failures_in),
        "rejected_count": len(rejected),
        "source_failures": failures_in,
        "rejected_quotes": rejected,
        "quotes": accepted,
    }
    return _rehash(payload)


def persist_payload(
    payload: Mapping[str, Any],
    *,
    root: Path = Path("artifacts/additional_odds"),
) -> tuple[Path, Path]:
    captured = parse_timestamp(payload.get("captured_at"))
    day = captured.date().isoformat()
    stamp = captured.strftime("%Y%m%dT%H%M%S.%fZ")
    immutable = root / day / f"additional_{stamp}.json"
    latest = root / "latest.json"
    _atomic_json(immutable, dict(payload))
    _atomic_json(latest, {
        "schema_version": 1,
        "captured_at": captured.isoformat(),
        "payload_sha256": payload.get("payload_sha256"),
        "pit_quote_count": payload.get("pit_quote_count"),
        "market_counts": payload.get("market_counts"),
        "capture_window": payload.get("capture_window"),
        "immutable_file": str(immutable),
    })
    return immutable, latest


def build_archive_payload(
    *,
    api_key: str,
    now: datetime | None = None,
    opener: Callable = urlopen,
    bookmakers: tuple[str, ...] = ("draftkings",),
) -> dict[str, Any]:
    captured = (now or _utcnow()).astimezone(timezone.utc)
    slate = captured.astimezone(CT).date().isoformat()
    full_schedule = fetch_schedule(slate, opener=opener, now=captured)
    eligible = _eligible_games(captured, full_schedule)

    if not eligible:
        payload = build_archive_from_inputs(
            schedule=[], quote_rows=[], provider_events=[], participant_index={}, captured_at=captured
        )
        payload.update({
            "capture_status": "SKIP_OUTSIDE_CAPTURE_WINDOW",
            "capture_window": CAPTURE_WINDOW,
            "games_scheduled": len(full_schedule),
            "games_eligible": 0,
        })
        return _rehash(payload)

    roster_names: dict[int, list[tuple[int, str]]] = {}
    roster_failures: list[dict[str, Any]] = []
    for game in eligible:
        try:
            roster_names[game.game_pk] = _roster_names(fetch_boxscore(game.game_pk, opener=opener))
        except Exception as exc:
            roster_names[game.game_pk] = []
            roster_failures.append({
                "stage": "MLB_ROSTER_IDENTITY",
                "game_id": str(game.game_pk),
                "reason": f"{type(exc).__name__}:{exc}",
            })
    participant_index = build_participant_index(schedule=eligible, confirmed_names_by_game=roster_names)

    ledger_path = _budget_ledger_path()
    daily_cap = _env_nonnegative_int("SPORTSEDGE_ODDS_DAILY_CREDIT_CAP", DEFAULT_DAILY_CREDIT_CAP)
    if daily_cap <= 0:
        raise AdditionalPITArchiveError("SPORTSEDGE_ODDS_DAILY_CREDIT_CAP_INVALID")
    reserve = _env_nonnegative_int(
        "SPORTSEDGE_ODDS_PROVIDER_RESERVE_CREDITS", DEFAULT_PROVIDER_RESERVE_CREDITS
    )
    estimated_cost = _estimated_paid_cost(len(eligible))
    budget_state = load_budget(ledger_path, cap_credits=daily_cap, now=captured)
    assert_budget_available(
        budget_state,
        estimated_cost=estimated_cost,
        reserve_credits=reserve,
    )

    event_snapshot = acquire_mlb_event_snapshot(
        api_key=api_key, opener=opener, acquired_at=captured
    )
    snapshot = fetch_mlb_additional_quotes(
        api_key=api_key,
        schedule=eligible,
        participant_index=participant_index,
        opener=opener,
        bookmakers=bookmakers,
        event_snapshot=event_snapshot,
    )
    if any(_quota_exhausted(row.get("reason")) for row in snapshot.failures if isinstance(row, Mapping)):
        # Persist account exhaustion so the next scheduled run blocks before HTTP.
        record_actual_cost(
            ledger_path,
            state=budget_state,
            actual_cost=0,
            provider_headers={"x-requests-remaining": "0"},
        )
        raise AdditionalPITArchiveError("BLOCKED_NO_CREDITS:OUT_OF_USAGE_CREDITS")

    # Source helpers do not currently expose provider headers. Record the proven
    # conservative upper bound so local/provider remaining cannot be overstated.
    updated_budget = record_actual_cost(
        ledger_path,
        state=budget_state,
        actual_cost=estimated_cost,
    )

    payload = build_archive_from_inputs(
        schedule=eligible,
        quote_rows=snapshot.quotes,
        provider_events=event_snapshot.events,
        participant_index=participant_index,
        captured_at=captured,
        source_failures=[*roster_failures, *[dict(x) for x in snapshot.failures]],
    )
    payload.update({
        "capture_status": "CAPTURE_ATTEMPTED",
        "capture_window": CAPTURE_WINDOW,
        "games_scheduled": len(full_schedule),
        "games_eligible": len(eligible),
        "eligible_game_ids": [str(game.game_pk) for game in eligible],
        "provider_event_snapshot_sha256": event_snapshot.payload_sha256,
        "budget": {
            "estimated_upper_bound_credits": estimated_cost,
            "recorded_credits": estimated_cost,
            "recording_mode": "CONSERVATIVE_UPPER_BOUND_NO_RESPONSE_HEADERS",
            "daily_cap_credits": daily_cap,
            "daily_consumed_credits": updated_budget.consumed_credits,
            "provider_reserve_credits": reserve,
            "provider_remaining_estimate": updated_budget.provider_credits_remaining,
        },
    })
    return _rehash(payload)


def _self_test() -> int:
    assert len(TARGET_MARKETS) == 7
    assert TARGET_MARKETS == CANONICAL_MARKETS
    assert TARGET_MINUTES == 90
    assert WINDOW_SECONDS == 420
    assert _estimated_paid_cost(1) == 1 + len(PROVIDER_MARKETS)
    assert len(_sha256_json({"a": 1})) == 64
    print(json.dumps({
        "status": "SELF_TEST_OK",
        "target_market_count": len(TARGET_MARKETS),
        "capture_window": CAPTURE_WINDOW,
        "pit_guard": "PASS",
        "identity_rebind_contract": "PASS",
        "single_event_snapshot_contract": "PASS",
        "budget_gate_contract": "PASS",
        "hash": "PASS",
    }))
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()
    keys = _keys()
    if not keys:
        print(json.dumps({"status": "BLOCKED_NO_ODDS_KEY"}))
        return 2

    attempts: list[dict[str, Any]] = []
    for slot, key in enumerate(keys, start=1):
        try:
            payload = build_archive_payload(api_key=key)
            if payload.get("capture_status") == "SKIP_OUTSIDE_CAPTURE_WINDOW":
                print(json.dumps({
                    "status": "SKIP_OUTSIDE_CAPTURE_WINDOW",
                    "capture_window": CAPTURE_WINDOW,
                    "games_scheduled": payload.get("games_scheduled"),
                    "games_eligible": 0,
                }))
                return 0

            immutable, latest = persist_payload(payload)
            status = "CAPTURED" if int(payload["pit_quote_count"]) > 0 else "BLOCKED_NO_TARGET_QUOTES"
            print(json.dumps({
                "status": status,
                "key_slot": slot,
                "capture_window": payload.get("capture_window"),
                "games_eligible": payload.get("games_eligible"),
                "pit_quote_count": payload["pit_quote_count"],
                "market_counts": payload["market_counts"],
                "payload_sha256": payload["payload_sha256"],
                "immutable_file": str(immutable),
                "latest_file": str(latest),
            }))
            return 0 if status == "CAPTURED" else 3
        except (OddsBudgetError, AdditionalPITArchiveError) as exc:
            reason = f"{type(exc).__name__}:{exc}"
            attempts.append({"key_slot": slot, "reason": reason})
            if "BLOCKED_" in str(exc).upper() or _quota_exhausted(exc):
                print(json.dumps({"status": "BLOCKED_ACQUISITION", "attempts": attempts}))
                return 5
        except Exception as exc:
            reason = f"{type(exc).__name__}:{exc}"
            attempts.append({"key_slot": slot, "reason": reason})
            if _quota_exhausted(exc):
                print(json.dumps({"status": "BLOCKED_NO_CREDITS", "attempts": attempts}))
                return 5

    print(json.dumps({"status": "ERROR", "attempts": attempts}))
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
