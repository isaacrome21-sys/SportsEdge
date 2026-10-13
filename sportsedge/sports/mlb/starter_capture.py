"""Point-in-time MLB probable-starter capture (offline module; NOT activated).

Implements the owner-approved design in
``docs/MLB_PROBABLE_STARTER_CAPTURE_DESIGN_20261013.md`` (PR #2156 review,
Oct 13, 2026): five planned pregame snapshots per game — T-24H, T-6H,
T-90M, T-30M, T-5M relative to first pitch — recording the announced
starting pitchers from the free MLB StatsAPI schedule as immutable
point-in-time evidence, replacing retrospective probable-starter identity.

Honesty contract (owner requirements, Oct 13, 2026):

- ``captured_at_utc`` is the time the capture actually COMPLETED. The
  injected clock is read only *after* the fetch returns; a scheduled or
  assumed time is never recorded as a receipt time, and a naive clock
  reading is refused (``CAPTURE_CLOCK_UNVERIFIED``). Caller-supplied
  timestamps are confined (owner audit point, Oct 13, 2026): the only
  production entry point, :func:`capture_snapshot_production`, takes
  no clock or fetcher parameter at all — it hard-wires the StatsAPI
  fetcher and the real system clock — so no caller-supplied time value
  can reach an emitted record in a production call chain. Clock and
  fetcher injection exist only on :func:`capture_snapshot` itself,
  below that wrapper, as the offline test seam.
- A missed slot stays missed. ``evaluate_missed_slots`` computes missed
  slots forward-only, from the plan versus what was actually captured;
  a late or out-of-window capture is stored and labeled, but never
  stands in for the slot it missed. Nothing here backfills, reconstructs
  retrospectively, or represents the final T-5M snapshot as guaranteed
  (scheduled runners can be delayed or dropped).
- Captures belong to the plan epoch they were taken under. Every
  snapshot/attempt record carries ``planned_first_pitch_utc`` — the
  scheduled first pitch of the plan it served — and a record counts
  toward a plan (satisfaction, failure attribution, missed-slot
  idempotency) only when that stamp equals the plan's first pitch for
  the game. When a game is rescheduled and replanned, the old plan's
  captures satisfy nothing in the new plan (owner finding, PR #2163,
  Oct 13, 2026: an old capture was reproduced satisfying a rescheduled
  game's new slot). The stamp is additive; a record without it (older
  evidence) fails closed and counts toward no plan.
- Identity is fail-closed and ID-only. Teams and starters bind by MLB
  StatsAPI IDs (``teams.*.team.id``, ``teams.*.probablePitcher.id``).
  Pitcher and team *names* are never read into a record and never
  accepted as identity. Two unbound cases are distinguished (owner
  ruling, Oct 13, 2026): a side the source does not announce at all is
  a valid OBSERVED record — the observation and its receipt timestamp
  are evidence of the announcement state, but they bind no pitcher
  identity and are never treated as one; a side the source purports to
  identify (a probable is present) from which no valid pitcher ID can
  be extracted is an unusable binding and fails closed as a FAILED
  record carrying a named reason. Either way the observation itself
  remains in the immutable evidence record.
- Evidence integrity is anchored outside the capture file. Every record
  appended through :func:`append_record` is hashed into a separate
  append-only hash-chain manifest; :func:`verify_capture_chain`
  re-derives the chain from the capture file's exact bytes and fails on
  any edit, deletion, insertion, or reordering.
- This module creates source evidence only. It creates no Model_P, no
  validation PASS, no eligibility, and no pricing authority. The
  production fetcher is provided for a future, separately approved
  activation; nothing in this module is scheduled, and no test invokes
  the network.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://statsapi.mlb.com"

SCHEMA_PLAN = "SPORTSEDGE_MLB_STARTER_CAPTURE_PLAN_V1"
SCHEMA_SNAPSHOT = "SPORTSEDGE_MLB_STARTER_SNAPSHOT_V1"
SCHEMA_MISSED_SLOT = "SPORTSEDGE_MLB_STARTER_MISSED_SLOT_V1"
SCHEMA_CHANGE_EVENT = "SPORTSEDGE_MLB_STARTER_CHANGE_EVENT_V1"
SCHEMA_ATTEMPT_FAILED = "SPORTSEDGE_MLB_STARTER_CAPTURE_ATTEMPT_V1"
SCHEMA_MANIFEST_ENTRY = "SPORTSEDGE_MLB_STARTER_CAPTURE_MANIFEST_V1"

# All StatsAPI game types from the approved design: regular season plus
# the full postseason ladder and the remaining exhibition/all-star types.
# The capture never filters by type; cohort filters belong to evaluation.
GAME_TYPES = ("R", "F", "D", "L", "W", "A", "S", "E")

# (slot_id, offset_minutes_before_first_pitch, tolerance_minutes).
# Windows are inclusive: [due - tolerance, due + tolerance].
SLOTS = (
    ("T-24H", 1440, 30),
    ("T-6H", 360, 15),
    ("T-90M", 90, 10),
    ("T-30M", 30, 5),
    ("T-5M", 5, 2),
)

GENESIS_CHAIN_SHA256 = "0" * 64

ClockFn = Callable[[], datetime]
FetcherFn = Callable[[str], bytes]


class StarterCaptureError(ValueError):
    """Fail-closed refusal raised by the starter-capture module."""


# --------------------------------------------------------------------------
# Small primitives (mirroring the repo's receipt/archiver conventions).
# --------------------------------------------------------------------------

def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_aware(value: Any, *, what: str) -> datetime:
    """Return ``value`` as an aware UTC datetime or refuse.

    A naive clock reading can never be turned into a receipt timestamp:
    that is the Form 2 clock lesson, enforced here at every entry point
    that accepts a time (injected clock, plan time, evaluation time).
    """
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise StarterCaptureError(f"CAPTURE_CLOCK_UNVERIFIED:{what}")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def canonical_line(record: Mapping[str, Any]) -> bytes:
    """The exact bytes of a record as one JSONL line (no trailing newline)."""
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


def record_sha256(record: Mapping[str, Any]) -> str:
    return _sha256_hex(canonical_line(record))


# --------------------------------------------------------------------------
# StatsAPI schedule: URL, production fetcher (never invoked by tests), parse.
# --------------------------------------------------------------------------

def schedule_url(slate_date: str) -> str:
    """Schedule URL covering every game type, postseason included."""
    params = {
        "sportId": 1,
        "gameType": ",".join(GAME_TYPES),
        "date": slate_date,
        "hydrate": "probablePitcher,lineups",
    }
    return BASE + "/api/v1/schedule?" + urlencode(params)


def fetch_statsapi(url: str, *, opener=urlopen, timeout: int = 20) -> bytes:
    """Production fetcher. Provided for a future approved activation only."""
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "SportsEdge-MLB-Starter-Capture/1.0",
        },
    )
    with opener(req, timeout=timeout) as response:
        return response.read()


def _positive_statsapi_id(value: Any) -> int | None:
    """An ID is a real positive JSON integer; never coerce booleans or text."""
    return value if type(value) is int and value > 0 else None


def _probable(row_team: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one side's probablePitcher to presence + ID only.

    The pitcher's name is deliberately never read: identity is the ID,
    and a present-but-ID-less probable is a binding failure, not a name
    waiting to be trusted.
    """
    probable = row_team.get("probablePitcher")
    if probable is None:
        return {"present": False, "id": None}
    # Present but malformed is NOT a legitimate "not announced" state.
    # This distinction makes bare strings, lists, booleans and numbers
    # fail as ID_MISSING rather than silently become usable evidence.
    if not isinstance(probable, dict):
        return {"present": True, "id": None}
    return {"present": True, "id": _positive_statsapi_id(probable.get("id"))}


def parse_schedule_games(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize a StatsAPI schedule payload to one row per game.

    Rows are keyed by ``gamePk`` (doubleheaders are distinct games with
    distinct gamePks, never date+team composites). A row missing its
    gamePk cannot be keyed and is dropped by the parser; every other
    deficiency is carried on the row so the plan/capture layers can fail
    closed with a named reason instead of guessing.
    """
    rows: list[dict[str, Any]] = []
    for block in payload.get("dates", []) or []:
        for game in (block or {}).get("games", []) or []:
            game_pk = _positive_statsapi_id(game.get("gamePk"))
            if game_pk is None:
                continue
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            status = game.get("status") or {}
            first_pitch = _parse_iso(game.get("gameDate"))
            rows.append(
                {
                    "game_pk": game_pk,
                    "game_type": game.get("gameType"),
                    "official_date": game.get("officialDate"),
                    "game_date_utc": _iso(first_pitch) if first_pitch else None,
                    "first_pitch": first_pitch,
                    "status_code": status.get("codedGameState"),
                    "detailed_state": status.get("detailedState"),
                    "abstract_state": status.get("abstractGameState"),
                    "double_header": game.get("doubleHeader"),
                    "game_number": game.get("gameNumber"),
                    "away_team_id": _positive_statsapi_id(away_team.get("id")),
                    "home_team_id": _positive_statsapi_id(home_team.get("id")),
                    "away_probable": _probable(away),
                    "home_probable": _probable(home),
                }
            )
    return rows


# --------------------------------------------------------------------------
# Plan generation.
# --------------------------------------------------------------------------

def build_plan(payload: Mapping[str, Any], *, planned_at: datetime) -> dict[str, Any]:
    """Build the five-slot capture plan for every game in a schedule payload.

    Forward-only: slots are keyed to each game's currently stated first
    pitch. Games that cannot be planned fail closed into ``issues``
    with a named reason; they are never silently dropped and never
    planned on partial identity.
    """
    planned = _require_aware(planned_at, what="planned_at")
    games: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    rows = parse_schedule_games(payload)
    counts: dict[int, int] = {}
    for row in rows:
        pk = row["game_pk"]
        counts[pk] = counts.get(pk, 0) + 1
    duplicate_issues: set[int] = set()
    for row in rows:
        pk = row["game_pk"]
        if counts[pk] != 1:
            if pk not in duplicate_issues:
                issues.append({"game_pk": pk, "reason": "DUPLICATE_GAME_PK"})
                duplicate_issues.add(pk)
            continue
        if row["game_type"] not in GAME_TYPES:
            issues.append({"game_pk": pk, "reason": "GAME_TYPE_UNRECOGNIZED"})
            continue
        if row["first_pitch"] is None:
            issues.append({"game_pk": row["game_pk"], "reason": "GAME_DATE_MISSING"})
            continue
        if row["away_team_id"] is None or row["home_team_id"] is None:
            issues.append({"game_pk": row["game_pk"], "reason": "TEAM_ID_MISSING"})
            continue
        slots = []
        for slot_id, offset, tolerance in SLOTS:
            due = row["first_pitch"] - timedelta(minutes=offset)
            slots.append(
                {
                    "slot_id": slot_id,
                    "offset_minutes": offset,
                    "tolerance_minutes": tolerance,
                    "due_at_utc": _iso(due),
                    "window_start_utc": _iso(due - timedelta(minutes=tolerance)),
                    "window_end_utc": _iso(due + timedelta(minutes=tolerance)),
                }
            )
        games.append(
            {
                "game_pk": row["game_pk"],
                "game_type": row["game_type"],
                "official_date": row["official_date"],
                "game_date_utc": row["game_date_utc"],
                "double_header": row["double_header"],
                "game_number": row["game_number"],
                "away_team_id": row["away_team_id"],
                "home_team_id": row["home_team_id"],
                "slots": slots,
            }
        )
    return {
        "schema": SCHEMA_PLAN,
        "planned_at_utc": _iso(planned),
        "source": "MLB_STATSAPI_SCHEDULE",
        "game_types": list(GAME_TYPES),
        "games": games,
        "issues": issues,
    }


def _slot_of(plan_game: Mapping[str, Any], slot_id: str) -> Mapping[str, Any]:
    for slot in plan_game.get("slots", []):
        if slot.get("slot_id") == slot_id:
            return slot
    raise StarterCaptureError(f"SLOT_NOT_IN_PLAN:{slot_id}")


# --------------------------------------------------------------------------
# Snapshot capture.
# --------------------------------------------------------------------------

def _slot_disposition(completed: datetime, slot: Mapping[str, Any]) -> str:
    start = _parse_iso(slot["window_start_utc"])
    end = _parse_iso(slot["window_end_utc"])
    if completed < start:
        return "EARLY"
    if completed > end:
        return "LATE"
    return "ON_TIME"


def _probable_identity_status(probable: Mapping[str, Any]) -> str:
    """One side's probable identity state: BOUND / NOT_ANNOUNCED / ID_MISSING.

    Owner ruling (Oct 13, 2026) — the two unbound states have different
    meanings and must not be conflated:

    - ``NOT_ANNOUNCED``: the payload carries no probable for the side
      (the key is absent or null — the payload's own representation of
      "no announcement"). There is no announcement to bind; the
      observation of that state is itself valid evidence.
    - ``ID_MISSING``: a probable is present — the source purports to
      identify the starter — but no valid pitcher ID can be extracted
      from it. That binding is unusable and fails closed.
    - ``BOUND``: a probable with a valid StatsAPI pitcher ID.
    """
    if not probable["present"]:
        return "NOT_ANNOUNCED"
    if probable["id"] is None:
        return "ID_MISSING"
    return "BOUND"


def capture_snapshot(
    plan_game: Mapping[str, Any],
    slot_id: str,
    *,
    fetcher: FetcherFn,
    clock: ClockFn,
) -> dict[str, Any]:
    """Capture one planned slot for one game and return its record.

    The fetcher is called first; the clock is read only after the fetch
    returns, so ``captured_at_utc`` is the actual completion time. A
    fetch failure produces a CAPTURE_ATTEMPT_FAILED record (the attempt
    is evidence too — it is what later explains a missed slot), never an
    exception swallowed into silence and never a fabricated snapshot.

    This injectable core is the offline test seam. Production callers
    must use :func:`capture_snapshot_production`, which hard-wires the
    fetcher and the system clock so no caller-supplied time value can
    reach a record.

    The record is stamped with ``planned_first_pitch_utc`` — the
    scheduled first pitch of the plan this capture serves. That stamp
    is the capture's plan-epoch binding: :func:`evaluate_missed_slots`
    counts the record toward a plan only when the stamp equals that
    plan's first pitch for the game, so a capture taken under a
    superseded schedule can never satisfy a replanned game's slot.
    (A plan game without a stated first pitch stamps ``None``, which
    matches no plan and fails closed.)
    """
    slot = _slot_of(plan_game, slot_id)
    url = schedule_url(str(plan_game.get("official_date")))
    base = {
        "game_pk": plan_game["game_pk"],
        "game_type": plan_game.get("game_type"),
        "slot_id": slot_id,
        "slot_due_at_utc": slot["due_at_utc"],
        "planned_first_pitch_utc": plan_game.get("game_date_utc"),
        "source_url": url,
    }
    try:
        raw = fetcher(url)
    except Exception as exc:  # network/HTTP failure: record the attempt
        failed_at = _require_aware(clock(), what="attempt_failed_at")
        return {
            "schema": SCHEMA_ATTEMPT_FAILED,
            "record_type": "CAPTURE_ATTEMPT_FAILED",
            **base,
            "attempted_at_utc": _iso(failed_at),
            "failure_reason": "FETCH_FAILED",
            "failure_detail": f"{type(exc).__name__}: {exc}"[:200],
        }
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        failed_at = _require_aware(clock(), what="attempt_failed_at")
        return {
            "schema": SCHEMA_ATTEMPT_FAILED,
            "record_type": "CAPTURE_ATTEMPT_FAILED",
            **base,
            "attempted_at_utc": _iso(failed_at),
            "failure_reason": "RESPONSE_UNPARSEABLE",
            "failure_detail": f"{type(exc).__name__}: {exc}"[:200],
        }

    completed = _require_aware(clock(), what="captured_at")
    plan_pk = _positive_statsapi_id(plan_game.get("game_pk"))
    matches = [
        row for row in parse_schedule_games(payload)
        if plan_pk is not None and row["game_pk"] == plan_pk
    ]
    if len(matches) != 1:
        return {
            "schema": SCHEMA_SNAPSHOT,
            "record_type": "SNAPSHOT",
            **base,
            "captured_at_utc": _iso(completed),
            "slot_disposition": _slot_disposition(completed, slot),
            "record_status": "FAILED",
            "failure_reason": (
                "DUPLICATE_GAME_PK_IN_RESPONSE" if len(matches) > 1
                else "GAME_NOT_IN_SCHEDULE_RESPONSE"
            ),
            "response_sha256": _sha256_hex(raw),
        }
    row = matches[0]

    probable_status = {
        side: _probable_identity_status(row[f"{side}_probable"])
        for side in ("away", "home")
    }
    observation_details = [
        f"PROBABLE_PITCHER_NOT_ANNOUNCED:{side.upper()}"
        for side in ("away", "home")
        if probable_status[side] == "NOT_ANNOUNCED"
    ]
    record: dict[str, Any] = {
        "schema": SCHEMA_SNAPSHOT,
        "record_type": "SNAPSHOT",
        **base,
        "official_date": row["official_date"],
        "game_date_utc": row["game_date_utc"],
        "captured_at_utc": _iso(completed),
        "minutes_to_first_pitch": (
            round((row["first_pitch"] - completed).total_seconds() / 60.0, 1)
            if row["first_pitch"] is not None
            else None
        ),
        "status_code": row["status_code"],
        "detailed_state": row["detailed_state"],
        "away_team_id": row["away_team_id"],
        "home_team_id": row["home_team_id"],
        "away_probable_id": row["away_probable"]["id"],
        "home_probable_id": row["home_probable"]["id"],
        "away_probable_status": probable_status["away"],
        "home_probable_status": probable_status["home"],
        "observation_details": observation_details,
        "double_header": row["double_header"],
        "game_number": row["game_number"],
        "slot_disposition": _slot_disposition(completed, slot),
        "record_status": "CAPTURED",
        "failure_reason": None,
        "response_sha256": _sha256_hex(raw),
    }
    if row["first_pitch"] is None:
        record["record_status"] = "FAILED"
        record["failure_reason"] = "GAME_DATE_MISSING"
        return record
    if completed >= row["first_pitch"]:
        # A "pregame" snapshot completed at/after first pitch is not
        # pregame evidence; fail closed rather than let it masquerade.
        record["record_status"] = "FAILED"
        record["failure_reason"] = "CAPTURE_COMPLETED_AFTER_FIRST_PITCH"
        return record
    if row["away_team_id"] is None or row["home_team_id"] is None:
        record["record_status"] = "FAILED"
        record["failure_reason"] = "TEAM_ID_MISSING"
        return record
    if row["game_type"] not in GAME_TYPES:
        record["record_status"] = "FAILED"
        record["failure_reason"] = "GAME_TYPE_UNRECOGNIZED"
        return record
    # gamePk alone cannot authorize a response that quietly substitutes
    # opponents, schedule epoch, postseason type, or doubleheader identity.
    # Preserve the untrusted observation on a FAILED record for auditing,
    # but do not let any of its pitcher IDs count as a bound starter.
    fixture_fields = (
        ("away_team_id", "FIXTURE_TEAM_ID_MISMATCH"),
        ("home_team_id", "FIXTURE_TEAM_ID_MISMATCH"),
        ("game_type", "FIXTURE_GAME_TYPE_MISMATCH"),
        ("official_date", "FIXTURE_OFFICIAL_DATE_MISMATCH"),
        ("game_date_utc", "FIXTURE_FIRST_PITCH_MISMATCH"),
        ("double_header", "FIXTURE_DOUBLEHEADER_MISMATCH"),
        ("game_number", "FIXTURE_GAME_NUMBER_MISMATCH"),
    )
    for field, reason in fixture_fields:
        if row[field] != plan_game.get(field):
            record["record_status"] = "FAILED"
            record["failure_reason"] = reason
            return record
    # A postponed game is a valid observation of a schedule change, not
    # evidence that a starter was confirmed pregame. Preserve the existing
    # epoch/change-detection contract; reject live/final/unknown states.
    postponed = (
        row["status_code"] == "D"
        and row["detailed_state"] == "Postponed"
        and row["abstract_state"] == "Preview"
    )
    pregame = (
        row["abstract_state"] == "Preview"
        and row["status_code"] in ("S", "P")
        and row["detailed_state"] in ("Scheduled", "Pre-Game", "Warmup")
    )
    if not (pregame or postponed):
        record["record_status"] = "FAILED"
        record["failure_reason"] = "GAME_STATUS_NOT_PREGAME"
        return record
    id_missing = [
        side for side in ("away", "home") if probable_status[side] == "ID_MISSING"
    ]
    if id_missing:
        # The source purports to identify this side's starter but no
        # valid ID can be extracted: the binding is unusable and the
        # record fails closed (owner ruling, Oct 13, 2026). Per-side
        # detail is preserved in the *_probable_status fields even
        # though the record as a whole is FAILED.
        record["record_status"] = "FAILED"
        record["failure_reason"] = (
            f"PROBABLE_PITCHER_ID_MISSING:{id_missing[0].upper()}"
        )
    elif observation_details:
        # A valid observation of an unannounced starter (owner ruling,
        # Oct 13, 2026): the record is immutable evidence of the
        # announcement state at its receipt time. It binds no pitcher
        # identity for the unannounced side(s) — the *_probable_id
        # fields stay None and the *_probable_status fields say
        # NOT_ANNOUNCED explicitly — and it is never identity evidence.
        record["record_status"] = "OBSERVED"
    return record


def system_utc_now() -> datetime:
    """The production clock: the real system clock, read in UTC."""
    return datetime.now(timezone.utc)


def capture_snapshot_production(
    plan_game: Mapping[str, Any],
    slot_id: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Production entry point for one slot capture — timestamps confined.

    This is the only supported production call chain. It takes **no
    clock and no fetcher parameter**: the fetcher is the module's own
    :func:`fetch_statsapi` and the clock is :func:`system_utc_now`,
    read inside :func:`capture_snapshot` only after the fetch
    completes, so every timestamp on an emitted record
    (``captured_at_utc``, or ``attempted_at_utc`` on a failed attempt)
    is the system clock's post-fetch reading and no caller-supplied
    time value can reach a record. Clock/fetcher injection exists only
    on :func:`capture_snapshot`, below this wrapper, for offline tests.

    ``opener`` is :func:`fetch_statsapi`'s transport seam (kept for
    offline testability of this wrapper): it can change which bytes
    arrive — the response is hashed into the record either way — and
    it cannot influence any timestamp. Provided for a future,
    separately approved activation; nothing here is scheduled.
    """
    return capture_snapshot(
        plan_game,
        slot_id,
        fetcher=lambda url: fetch_statsapi(url, opener=opener),
        clock=system_utc_now,
    )


# --------------------------------------------------------------------------
# Missed-slot evaluation (forward-only; absence is recorded, never silent).
# --------------------------------------------------------------------------

def evaluate_missed_slots(
    plan: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return MISSED_SLOT records for slots whose window closed unsatisfied.

    A slot is satisfied only by a snapshot record with
    ``slot_disposition == "ON_TIME"`` for the same (game, slot) in the
    record stream whose capture actually ran: ``record_status ==
    "CAPTURED"`` (identity bound) or ``record_status == "OBSERVED"``
    (an on-time observation of an unannounced starter — the slot was
    captured; the announcement state, not a pitcher, is what was
    observed, per the Oct 13, 2026 owner ruling). Late captures, failed
    captures, and failed fetch attempts never satisfy a slot.
    Evaluation is idempotent: a slot already carrying a MISSED_SLOT
    record is not reported twice.

    All three judgments — satisfaction, failure attribution, and
    idempotency — are scoped to the plan epoch. A record counts toward
    this plan only when its epoch stamp matches the plan's first pitch
    for the game: snapshot and attempt records carry the stamp as
    ``planned_first_pitch_utc``; MISSED_SLOT records are generated from
    a plan, so their ``game_date_utc`` is the stamp of the plan that
    produced them. A capture taken under a superseded schedule (the
    game was rescheduled and replanned) therefore satisfies nothing
    here, its failures explain nothing here, and a MISSED_SLOT from
    another epoch suppresses nothing here. Records without a stamp
    (evidence written before the stamp existed) fail closed the same
    way: they count toward no plan.
    """
    evaluated_at = _require_aware(now, what="evaluated_at")
    planned_at = _parse_iso(plan.get("planned_at_utc"))
    plan_first_pitch: dict[Any, Any] = {
        game.get("game_pk"): game.get("game_date_utc")
        for game in plan.get("games", [])
    }

    def epoch_matches(record: Mapping[str, Any]) -> bool:
        stamp = record.get("planned_first_pitch_utc")
        return stamp is not None and stamp == plan_first_pitch.get(
            record.get("game_pk")
        )

    satisfied: set[tuple[int, str]] = set()
    already_missed: set[tuple[int, str]] = set()
    failed_attempts: dict[tuple[int, str], str] = {}
    for record in records:
        key = (record.get("game_pk"), record.get("slot_id"))
        if record.get("record_type") == "SNAPSHOT":
            if (
                record.get("record_status") in ("CAPTURED", "OBSERVED")
                and record.get("slot_disposition") == "ON_TIME"
                and epoch_matches(record)
            ):
                satisfied.add(key)  # type: ignore[arg-type]
            elif record.get("record_status") == "FAILED" and epoch_matches(record):
                failed_attempts.setdefault(key, str(record.get("failure_reason")))  # type: ignore[arg-type]
        elif record.get("record_type") == "CAPTURE_ATTEMPT_FAILED":
            if epoch_matches(record):
                failed_attempts.setdefault(key, str(record.get("failure_reason")))  # type: ignore[arg-type]
        elif record.get("record_type") == "MISSED_SLOT":
            missed_stamp = record.get("game_date_utc")
            if missed_stamp is not None and missed_stamp == plan_first_pitch.get(
                record.get("game_pk")
            ):
                already_missed.add(key)  # type: ignore[arg-type]

    missed: list[dict[str, Any]] = []
    for game in plan.get("games", []):
        for slot in game.get("slots", []):
            key = (game["game_pk"], slot["slot_id"])
            if key in satisfied or key in already_missed:
                continue
            window_end = _parse_iso(slot["window_end_utc"])
            if window_end is None or evaluated_at <= window_end:
                continue  # window still open: nothing is missed yet
            if planned_at is not None and window_end <= planned_at:
                # The slot's window had already closed before the plan
                # first saw this game (the design's T-24H case).
                reason = "NOT_YET_SCHEDULED"
            elif key in failed_attempts:
                reason = f"CAPTURE_FAILED:{failed_attempts[key]}"
            else:
                reason = "NO_CAPTURE_IN_WINDOW"
            missed.append(
                {
                    "schema": SCHEMA_MISSED_SLOT,
                    "record_type": "MISSED_SLOT",
                    "game_pk": game["game_pk"],
                    "game_type": game.get("game_type"),
                    "slot_id": slot["slot_id"],
                    "slot_due_at_utc": slot["due_at_utc"],
                    "window_end_utc": slot["window_end_utc"],
                    "game_date_utc": game.get("game_date_utc"),
                    "evaluated_at_utc": _iso(evaluated_at),
                    "reason": reason,
                }
            )
    return missed


# --------------------------------------------------------------------------
# Change detection across snapshots.
# --------------------------------------------------------------------------

def _is_postponed_observation(record: Mapping[str, Any]) -> bool:
    return "Postpon" in str(record.get("detailed_state") or "")


def _same_starter_epoch(
    prev: Mapping[str, Any], curr: Mapping[str, Any]
) -> bool:
    """Whether two consecutive snapshots' starter states are comparable.

    Starter states are comparable only inside one plan epoch observing
    one scheduled occurrence. The pair is an epoch boundary — the
    pre-reschedule capture is the prior epoch's baseline, and the
    later capture becomes the new epoch's baseline — whenever any of
    these hold:

    - either capture's plan-epoch stamp (``planned_first_pitch_utc``)
      is absent (older evidence: comparability cannot be established,
      so it fails closed) or the stamps differ (the captures served
      different plans, i.e. the game was replanned);
    - the observed first pitch (``game_date_utc``) differs — the
      schedule itself moved between the two observations, even under
      one plan, so the later announcement state belongs to a different
      scheduled occurrence;
    - either observation is a postponement — probables cleared in the
      shadow of a postponement are the postponement's artifact, not a
      starter decision; the SCHEDULE_CHANGE/POSTPONED event is the
      record of that fact.

    Across a boundary no STARTER_CHANGE is derived: a probable that
    vanishes because the game moved is not a REMOVED, and one that
    appears on the new schedule is not an ANNOUNCED against the old
    baseline. SCHEDULE_CHANGE events are unaffected — they describe
    the boundary itself and are always derived from the observed
    schedule states.
    """
    prev_stamp = prev.get("planned_first_pitch_utc")
    curr_stamp = curr.get("planned_first_pitch_utc")
    if prev_stamp is None or curr_stamp is None or prev_stamp != curr_stamp:
        return False
    if prev.get("game_date_utc") != curr.get("game_date_utc"):
        return False
    return not (
        _is_postponed_observation(prev) or _is_postponed_observation(curr)
    )


def detect_changes(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Derive change events from consecutive snapshot observations per game.

    Pure function of the record stream (ordered by ``captured_at_utc``):
    starter announcements/changes/removals and schedule changes (first
    pitch moved, status changed — including postponements) become
    first-class CHANGE_EVENT records. Attempt-failed records carry no
    observation and never take part. An OBSERVED record takes part as
    starter-state None for its unannounced side(s): it is evidence of
    the announcement state, never of an identity, so a later binding
    capture yields the STARTER_CHANGE/ANNOUNCED event and the OBSERVED
    record itself is never upgraded. Events are derived, never edited
    into earlier records: the append-only stream stays intact.

    STARTER_CHANGE events are derived only between snapshots of the
    same plan epoch observing the same scheduled occurrence (see
    :func:`_same_starter_epoch`): across a reschedule the earlier
    capture is the prior epoch's baseline — it produces the
    SCHEDULE_CHANGE events for the move and no starter event, and the
    first capture under the new plan becomes the new baseline against
    which later announcements and changes are measured.
    """
    snapshots = [
        r
        for r in records
        if r.get("record_type") == "SNAPSHOT" and r.get("game_date_utc")
    ]
    by_game: dict[int, list[Mapping[str, Any]]] = {}
    for record in snapshots:
        by_game.setdefault(int(record["game_pk"]), []).append(record)

    events: list[dict[str, Any]] = []
    for game_pk in sorted(by_game):
        ordered = sorted(
            by_game[game_pk], key=lambda r: str(r.get("captured_at_utc"))
        )
        for prev, curr in zip(ordered, ordered[1:]):
            base = {
                "schema": SCHEMA_CHANGE_EVENT,
                "record_type": "CHANGE_EVENT",
                "game_pk": game_pk,
                "game_type": curr.get("game_type"),
                "previous_captured_at_utc": prev.get("captured_at_utc"),
                "captured_at_utc": curr.get("captured_at_utc"),
            }
            if _same_starter_epoch(prev, curr):
                for side in ("away", "home"):
                    before = prev.get(f"{side}_probable_id")
                    after = curr.get(f"{side}_probable_id")
                    if before == after:
                        continue
                    if before is None:
                        detail = "ANNOUNCED"
                    elif after is None:
                        detail = "REMOVED"
                    else:
                        detail = "CHANGED"
                    events.append(
                        {
                            **base,
                            "change_kind": "STARTER_CHANGE",
                            "change_detail": detail,
                            "side": side,
                            "from_value": before,
                            "to_value": after,
                        }
                    )
            # Else: the pair straddles an epoch boundary (reschedule,
            # postponement, or a plan change). Starter states are not
            # compared across it — the SCHEDULE_CHANGE events below are
            # the record of the boundary itself.
            if prev.get("game_date_utc") != curr.get("game_date_utc"):
                events.append(
                    {
                        **base,
                        "change_kind": "SCHEDULE_CHANGE",
                        "change_detail": "FIRST_PITCH_MOVED",
                        "side": None,
                        "from_value": prev.get("game_date_utc"),
                        "to_value": curr.get("game_date_utc"),
                    }
                )
            prev_status = (prev.get("status_code"), prev.get("detailed_state"))
            curr_status = (curr.get("status_code"), curr.get("detailed_state"))
            if prev_status != curr_status:
                detailed = str(curr.get("detailed_state") or "")
                events.append(
                    {
                        **base,
                        "change_kind": "SCHEDULE_CHANGE",
                        "change_detail": (
                            "POSTPONED" if "Postpon" in detailed else "STATUS_CHANGED"
                        ),
                        "side": None,
                        "from_value": {
                            "status_code": prev_status[0],
                            "detailed_state": prev_status[1],
                        },
                        "to_value": {
                            "status_code": curr_status[0],
                            "detailed_state": curr_status[1],
                        },
                    }
                )
    return events


# --------------------------------------------------------------------------
# Append-only store + external hash-chain manifest.
# --------------------------------------------------------------------------

def _read_lines(path: Path) -> list[bytes]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw:
        return []
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return lines


def _append_line(path: Path, line: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(line + b"\n")
        handle.flush()
        import os

        os.fsync(handle.fileno())


def read_records(capture_path: Path) -> list[dict[str, Any]]:
    records = []
    for line in _read_lines(Path(capture_path)):
        records.append(json.loads(line.decode("utf-8")))
    return records


def read_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    entries = []
    for line in _read_lines(Path(manifest_path)):
        entries.append(json.loads(line.decode("utf-8")))
    return entries


def append_record(
    capture_path: Path, manifest_path: Path, record: Mapping[str, Any]
) -> dict[str, Any]:
    """Serialize cooperating writers and fail closed on partial pair appends.

    The stable, never-unlinked POSIX lock is shared by all appenders of a
    manifest. Under the lock we validate *both* files before deriving a
    sequence number; a damaged/incomplete pair is not extended or
    silently repaired. Ordinary write exceptions roll back both files
    to their prior byte lengths and fsync the rollback.

    POSIX flock protects cooperating appenders, not unsynchronized readers.
    Two files cannot be made crash-atomic: a process/power failure between
    the two durable appends can leave a mismatch which a later append
    must refuse. This is a research-only writer, NOT live-activation
    approval or a claim of crash-atomic, externally anchored evidence.
    """
    import fcntl
    import os

    capture_path = Path(capture_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    if capture_path == manifest_path:
        raise StarterCaptureError("CAPTURE_AND_MANIFEST_PATH_COLLIDE")
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = manifest_path.with_name(manifest_path.name + ".lock")

    # Never unlink this file: changing its inode would permit separate
    # processes to hold distinct locks while both believe they are alone.
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            checked = verify_capture_chain(capture_path, manifest_path)
            if not checked["ok"]:
                reason = checked["failure"]["reason"]
                raise StarterCaptureError(
                    f"CAPTURE_CHAIN_PREAPPEND_INVALID:{reason}"
                )

            line = canonical_line(record)
            digest = _sha256_hex(line)
            existing = read_manifest(manifest_path)
            prev_chain = (
                str(existing[-1]["chain_sha256"])
                if existing else GENESIS_CHAIN_SHA256
            )
            seq = len(existing) + 1
            chain = _sha256_hex(f"{prev_chain}:{digest}".encode("utf-8"))
            entry = {
                "schema": SCHEMA_MANIFEST_ENTRY,
                "seq": seq,
                "record_sha256": digest,
                "record_type": record.get("record_type"),
                "game_pk": record.get("game_pk"),
                "slot_id": record.get("slot_id"),
                "prev_chain_sha256": prev_chain,
                "chain_sha256": chain,
            }
            before = {
                capture_path: capture_path.stat().st_size if capture_path.exists() else 0,
                manifest_path: manifest_path.stat().st_size if manifest_path.exists() else 0,
            }
            try:
                _append_line(capture_path, line)
                _append_line(manifest_path, canonical_line(entry))
            except BaseException:
                rollback_errors = []
                for path, length in before.items():
                    try:
                        if path.exists():
                            with path.open("r+b") as handle:
                                handle.truncate(length)
                                handle.flush()
                                os.fsync(handle.fileno())
                    except OSError as exc:
                        rollback_errors.append(f"{path.name}:{type(exc).__name__}")
                if rollback_errors:
                    raise StarterCaptureError(
                        "CAPTURE_APPEND_ROLLBACK_FAILED:" +
                        ",".join(rollback_errors)
                    )
                raise
            return entry
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def verify_capture_chain(capture_path: Path, manifest_path: Path) -> dict[str, Any]:
    """Re-derive the hash chain from the capture file and compare.

    Returns ``{"ok": True, ...}`` only when every capture line's hash,
    every manifest entry, and every chain link recomputes exactly. Any
    edit, deletion, insertion, or reordering inside the capture file
    (or the manifest) fails at the first mismatching position with a
    named reason.
    """
    capture_path = Path(capture_path)
    manifest_path = Path(manifest_path)
    capture_lines = _read_lines(capture_path)
    manifest_lines = _read_lines(manifest_path)

    def failure(reason: str, seq: int | None) -> dict[str, Any]:
        return {
            "ok": False,
            "records_checked": len(capture_lines),
            "manifest_entries": len(manifest_lines),
            "failure": {"reason": reason, "seq": seq},
        }

    # A JSONL final line without a newline can appear valid to a splitlines
    # reader but the next append would concatenate two separate records.
    # Treat an interrupted terminal write as a failed archive, not a
    # successfully chained record awaiting silent continuation.
    if capture_path.exists() and capture_path.stat().st_size and not capture_path.read_bytes().endswith(b"\n"):
        return failure("CAPTURE_LINE_UNTERMINATED", len(capture_lines))
    if manifest_path.exists() and manifest_path.stat().st_size and not manifest_path.read_bytes().endswith(b"\n"):
        return failure("MANIFEST_LINE_UNTERMINATED", len(manifest_lines))
    if len(capture_lines) != len(manifest_lines):
        return failure("RECORD_COUNT_MISMATCH", None)
    prev_chain = GENESIS_CHAIN_SHA256
    for index, (line, manifest_line) in enumerate(
        zip(capture_lines, manifest_lines), start=1
    ):
        try:
            entry = json.loads(manifest_line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return failure("MANIFEST_LINE_UNPARSEABLE", index)
        if not isinstance(entry, dict):
            return failure("MANIFEST_RECORD_TYPE_INVALID", index)
        digest = _sha256_hex(line)
        if entry.get("record_sha256") != digest:
            return failure("CAPTURE_RECORD_HASH_MISMATCH", index)
        if entry.get("prev_chain_sha256") != prev_chain:
            return failure("MANIFEST_CHAIN_BROKEN", index)
        chain = _sha256_hex(f"{prev_chain}:{digest}".encode("utf-8"))
        if entry.get("chain_sha256") != chain or entry.get("seq") != index:
            return failure("MANIFEST_HASH_MISMATCH", index)
        try:
            source_record = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return failure("CAPTURE_RECORD_UNPARSEABLE", index)
        if not isinstance(source_record, dict) or not isinstance(entry, dict):
            return failure("MANIFEST_RECORD_TYPE_INVALID", index)
        expected_entry = {
            "schema": SCHEMA_MANIFEST_ENTRY,
            "seq": index,
            "record_sha256": digest,
            "record_type": source_record.get("record_type"),
            "game_pk": source_record.get("game_pk"),
            "slot_id": source_record.get("slot_id"),
            "prev_chain_sha256": prev_chain,
            "chain_sha256": chain,
        }
        if entry != expected_entry:
            return failure("MANIFEST_METADATA_MISMATCH", index)
        if manifest_line != canonical_line(entry):
            return failure("MANIFEST_ENCODING_MISMATCH", index)
        prev_chain = chain
    return {
        "ok": True,
        "records_checked": len(capture_lines),
        "manifest_entries": len(manifest_lines),
        "failure": None,
    }
