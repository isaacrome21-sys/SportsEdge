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

def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Untrusted nested source object -> mapping; any other type -> ``{}``.

    A wrong-typed nested object is treated as absent, so the field-level
    fail-closed checks below (missing ID, missing date, unknown status)
    name the failure instead of an AttributeError escaping.
    """
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    """Untrusted source array -> list; any other type -> ``[]``."""
    return list(value) if isinstance(value, (list, tuple)) else []


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


# --------------------------------------------------------------------------
# Clock bounds (reuses #2166's trusted-clock / receipt-bound semantics).
# --------------------------------------------------------------------------

def _receipt_bounds():
    from sportsedge import mlb_source as _ms
    return _ms


def _check_clock_bounds(
    value: datetime, *, what: str, anchor: datetime | None
) -> datetime:
    """Refuse clock readings outside a sane window.

    Floor and skew are #2166's ``RECEIPT_PLAUSIBLE_FLOOR`` (2020-01-01 UTC)
    and ``RECEIPT_CLOCK_SKEW``. A reset clock (e.g. 2000-01-01) or a reading
    in the future of the trusted anchor can never become a receipt time.
    """
    ms = _receipt_bounds()
    value = _require_aware(value, what=what)
    if value < ms.RECEIPT_PLAUSIBLE_FLOOR:
        raise StarterCaptureError(f"CAPTURE_CLOCK_IMPLAUSIBLY_OLD:{what}")
    if anchor is not None and value > anchor + ms.RECEIPT_CLOCK_SKEW:
        raise StarterCaptureError(f"CAPTURE_CLOCK_IN_FUTURE:{what}")
    return value


def _check_fetch_span(started: datetime, received: datetime) -> None:
    ms = _receipt_bounds()
    if received < started:
        raise StarterCaptureError("CAPTURE_CLOCK_WENT_BACKWARDS")
    if received - started > ms.RECEIPT_MAX_FETCH_SPAN:
        raise StarterCaptureError("CAPTURE_FETCH_SPAN_UNBOUNDED")


def _trusted_anchor() -> datetime:
    return _receipt_bounds()._trusted_now()


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
    if not isinstance(payload, Mapping):
        raise StarterCaptureError("SCHEDULE_PAYLOAD_NOT_OBJECT")
    rows: list[dict[str, Any]] = []
    for block in _as_list(payload.get("dates")):
        for game in _as_list(_as_mapping(block).get("games")):
            if not isinstance(game, Mapping):
                continue  # cannot be keyed by gamePk: same as a missing gamePk
            game_pk = _positive_statsapi_id(game.get("gamePk"))
            if game_pk is None:
                continue
            teams = _as_mapping(game.get("teams"))
            away = _as_mapping(teams.get("away"))
            home = _as_mapping(teams.get("home"))
            away_team = _as_mapping(away.get("team"))
            home_team = _as_mapping(home.get("team"))
            status = _as_mapping(game.get("status"))
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
    if not isinstance(plan_game, Mapping):
        raise StarterCaptureError("PLAN_GAME_NOT_OBJECT")
    if not isinstance(slot_id, str):
        raise StarterCaptureError("SLOT_ID_INVALID")
    for slot in _as_list(plan_game.get("slots")):
        if isinstance(slot, Mapping) and slot.get("slot_id") == slot_id:
            return slot
    raise StarterCaptureError(f"SLOT_NOT_IN_PLAN:{slot_id}")


# --------------------------------------------------------------------------
# Snapshot capture.
# --------------------------------------------------------------------------

def _slot_disposition(completed: datetime, slot: Mapping[str, Any]) -> str:
    start = _parse_iso(slot.get("window_start_utc"))
    end = _parse_iso(slot.get("window_end_utc"))
    if start is None or end is None:
        # A plan slot without a parseable window can never be ON_TIME.
        return "WINDOW_INVALID"
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
    anchor: ClockFn | None = None,
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
    if _positive_statsapi_id(plan_game.get("game_pk")) is None:
        raise StarterCaptureError("PLAN_GAME_PK_INVALID")
    url = schedule_url(str(plan_game.get("official_date")))
    base = {
        "game_pk": plan_game["game_pk"],
        "game_type": plan_game.get("game_type"),
        "slot_id": slot_id,
        "slot_due_at_utc": slot["due_at_utc"],
        "planned_first_pitch_utc": plan_game.get("game_date_utc"),
        "source_url": url,
    }
    # Clock bounds: the fetch start is read before the fetch and the
    # receipt after it; both must sit inside #2166's sane window
    # (>= 2020-01-01 UTC, <= trusted anchor + skew when an anchor is
    # supplied; production always supplies the trusted system anchor).
    fetch_started = _check_clock_bounds(
        clock(), what="fetch_started_at",
        anchor=_require_aware(anchor(), what="anchor") if anchor else None,
    )
    base["fetch_started_at_utc"] = _iso(fetch_started)

    def _received(what: str) -> datetime:
        value = _check_clock_bounds(
            clock(), what=what,
            anchor=_require_aware(anchor(), what="anchor") if anchor else None,
        )
        _check_fetch_span(fetch_started, value)
        return value

    try:
        raw = fetcher(url)
    except Exception as exc:  # network/HTTP failure: record the attempt
        failed_at = _received("attempt_failed_at")
        return {
            "schema": SCHEMA_ATTEMPT_FAILED,
            "record_type": "CAPTURE_ATTEMPT_FAILED",
            **base,
            "attempted_at_utc": _iso(failed_at),
            "failure_reason": "FETCH_FAILED",
            "failure_detail": f"{type(exc).__name__}: {exc}"[:200],
        }
    if isinstance(raw, bytearray):
        raw = bytes(raw)
    if not isinstance(raw, bytes):
        failed_at = _received("attempt_failed_at")
        return {
            "schema": SCHEMA_ATTEMPT_FAILED,
            "record_type": "CAPTURE_ATTEMPT_FAILED",
            **base,
            "attempted_at_utc": _iso(failed_at),
            "failure_reason": "RESPONSE_NOT_BYTES",
            "failure_detail": type(raw).__name__[:200],
        }
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"schedule payload is {type(payload).__name__}, not object")
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        failed_at = _received("attempt_failed_at")
        return {
            "schema": SCHEMA_ATTEMPT_FAILED,
            "record_type": "CAPTURE_ATTEMPT_FAILED",
            **base,
            "attempted_at_utc": _iso(failed_at),
            "failure_reason": "RESPONSE_UNPARSEABLE",
            "failure_detail": f"{type(exc).__name__}: {exc}"[:200],
        }

    completed = _received("captured_at")
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
        anchor=_trusted_anchor,
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
    if not isinstance(plan, Mapping):
        raise StarterCaptureError("PLAN_NOT_OBJECT")
    if not isinstance(records, (list, tuple)):
        raise StarterCaptureError("RECORDS_NOT_SEQUENCE")
    plan_games = plan.get("games")
    if not isinstance(plan_games, (list, tuple)):
        raise StarterCaptureError("PLAN_GAMES_INVALID")
    for game in plan_games:
        if (
            not isinstance(game, Mapping)
            or _positive_statsapi_id(game.get("game_pk")) is None
            or not isinstance(game.get("slots"), (list, tuple))
            or not all(
                isinstance(slot, Mapping) and isinstance(slot.get("slot_id"), str)
                for slot in game["slots"]
            )
        ):
            raise StarterCaptureError("PLAN_GAME_INVALID")
    planned_at = _parse_iso(plan.get("planned_at_utc"))
    plan_first_pitch: dict[Any, Any] = {
        game.get("game_pk"): game.get("game_date_utc")
        for game in plan_games
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
        if not isinstance(record, Mapping):
            continue  # a non-object record satisfies and explains nothing
        record_pk = _positive_statsapi_id(record.get("game_pk"))
        record_slot = record.get("slot_id")
        if record_pk is None or not isinstance(record_slot, str):
            continue  # unkeyable record counts toward no plan slot
        key = (record_pk, record_slot)
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
    for game in plan_games:
        for slot in game["slots"]:
            key = (game["game_pk"], slot["slot_id"])
            if key in satisfied or key in already_missed:
                continue
            window_end = _parse_iso(slot.get("window_end_utc"))
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
                    "slot_due_at_utc": slot.get("due_at_utc"),
                    "window_end_utc": slot.get("window_end_utc"),
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
    if not isinstance(records, (list, tuple)):
        raise StarterCaptureError("RECORDS_NOT_SEQUENCE")
    snapshots = [
        r
        for r in records
        if isinstance(r, Mapping)
        and r.get("record_type") == "SNAPSHOT"
        and r.get("game_date_utc")
        # An unkeyable game_pk (text, bool, float, <=0) cannot be grouped
        # with anything; it derives no event rather than crashing or being
        # coerced (int("12") / int(True) would forge a grouping).
        and _positive_statsapi_id(r.get("game_pk")) is not None
    ]
    by_game: dict[int, list[Mapping[str, Any]]] = {}
    for record in snapshots:
        by_game.setdefault(record["game_pk"], []).append(record)

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


def _as_path(value: Any, *, what: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise StarterCaptureError(f"PATH_INVALID:{what}")
    return Path(value)


def _read_objects(path: Path, *, what: str) -> list[dict[str, Any]]:
    out = []
    for index, line in enumerate(_read_lines(path), start=1):
        try:
            obj = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise StarterCaptureError(f"{what}_LINE_UNPARSEABLE:{index}") from None
        if not isinstance(obj, dict):
            raise StarterCaptureError(f"{what}_LINE_NOT_OBJECT:{index}")
        out.append(obj)
    return out


def read_records(capture_path: Path) -> list[dict[str, Any]]:
    return _read_objects(_as_path(capture_path, what="capture"), what="CAPTURE")


def read_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    return _read_objects(_as_path(manifest_path, what="manifest"), what="MANIFEST")


def append_record(
    capture_path: Path, manifest_path: Path, record: Mapping[str, Any],
    *, verifier_now: datetime | None = None,
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

    if not isinstance(record, Mapping):
        raise StarterCaptureError("RECORD_NOT_OBJECT")
    try:
        canonical_line(record)
    except (TypeError, ValueError, RecursionError):
        raise StarterCaptureError("RECORD_NOT_JSON_SERIALIZABLE") from None
    capture_path = _as_path(capture_path, what="capture").resolve()
    manifest_path = _as_path(manifest_path, what="manifest").resolve()
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
            reason = _record_clock_failure(record, verifier_now)
            if reason is not None:
                raise StarterCaptureError(f"CAPTURE_RECORD_CLOCK_INVALID:{reason}")
            checked = verify_capture_chain(
                capture_path, manifest_path, verifier_now=verifier_now
            )
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


_RECORD_TIME_FIELDS = {
    "SNAPSHOT": "captured_at_utc",
    "CAPTURE_ATTEMPT_FAILED": "attempted_at_utc",
}


def _record_clock_failure(
    record: Mapping[str, Any], verifier_now: datetime | None
) -> str | None:
    """Return a failure reason when a record's clock stamps are out of bounds.

    Snapshot / attempt records must carry their receipt stamp; any stamp
    present (receipt or ``fetch_started_at_utc``) must be >= 2020-01-01 UTC
    and <= the trusted verifier clock + skew, and the fetch span must be
    ordered and bounded. Fails closed; never repairs a timestamp.
    """
    if not isinstance(record, Mapping):
        return "RECORD_NOT_OBJECT"
    try:
        now = _require_aware(
            verifier_now if verifier_now is not None else _trusted_anchor(),
            what="verifier_now",
        )
    except StarterCaptureError:
        return "VERIFIER_CLOCK_UNVERIFIED"
    field = _RECORD_TIME_FIELDS.get(record.get("record_type"))
    stamps = {}
    for name in filter(None, (field, "fetch_started_at_utc")):
        raw = record.get(name)
        if raw is None:
            if name == field:
                return f"TIMESTAMP_MISSING:{name}"
            continue
        parsed = _parse_iso(raw)
        if parsed is None or parsed.tzinfo is None:
            return f"TIMESTAMP_UNPARSEABLE:{name}"
        try:
            stamps[name] = _check_clock_bounds(parsed, what=name, anchor=now)
        except StarterCaptureError as exc:
            return str(exc)
    if field in stamps and "fetch_started_at_utc" in stamps:
        try:
            _check_fetch_span(stamps["fetch_started_at_utc"], stamps[field])
        except StarterCaptureError as exc:
            return str(exc)
    return None


def verify_capture_chain(
    capture_path: Path, manifest_path: Path, *, verifier_now: datetime | None = None
) -> dict[str, Any]:
    """Re-derive the hash chain from the capture file and compare.

    Returns ``{"ok": True, ...}`` only when every capture line's hash,
    every manifest entry, and every chain link recomputes exactly. Any
    edit, deletion, insertion, or reordering inside the capture file
    (or the manifest) fails at the first mismatching position with a
    named reason.
    """
    capture_path = _as_path(capture_path, what="capture")
    manifest_path = _as_path(manifest_path, what="manifest")
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
        clock_reason = _record_clock_failure(source_record, verifier_now)
        if clock_reason is not None:
            return failure(f"RECORD_CLOCK_INVALID:{clock_reason}", index)
        prev_chain = chain
    return {
        "ok": True,
        "records_checked": len(capture_lines),
        "manifest_entries": len(manifest_lines),
        "failure": None,
    }


# --------------------------------------------------------------------------
# Raw-response preservation (research-only, LOCAL and UNANCHORED).
# --------------------------------------------------------------------------
#
# Each SNAPSHOT record built from a response carries ``response_sha256``.
# The raw bytes are kept in a content-addressed local directory
# (``<sha256>.json``) and the record names them via ``raw_store_file`` /
# ``raw_sha256`` / ``raw_byte_length``. The record itself is inside the
# hash-chained capture/manifest pair, so the raw-file link is chain-covered.
# The link to #2166's receipt journal is by digest: a receipt entry whose
# ``sha256`` equals ``raw_sha256`` and whose ``url`` equals ``source_url``.
#
# This store is NOT retention-locked, NOT WORM, NOT externally anchored.
# It proves only local byte consistency at verification time.

RAW_STORE_KIND = "LOCAL_UNANCHORED_NOT_RETENTION_LOCKED"
_HEX = frozenset("0123456789abcdef")


def _is_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def store_raw_response(raw_dir: Path, raw: bytes) -> dict[str, Any]:
    """Write ``raw`` content-addressed under ``raw_dir``; never overwrite."""
    if not isinstance(raw, (bytes, bytearray)):
        raise StarterCaptureError("RAW_RESPONSE_NOT_BYTES")
    raw = bytes(raw)
    digest = _sha256_hex(raw)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    name = f"{digest}.json"
    dest = raw_dir / name
    if dest.is_symlink():
        raise StarterCaptureError("RAW_STORE_PATH_UNSAFE")
    if dest.exists():
        if dest.read_bytes() != raw:
            raise StarterCaptureError("RAW_STORE_COLLISION")
    else:
        tmp = raw_dir / f".{name}.tmp"
        with tmp.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            import os

            os.fsync(handle.fileno())
        tmp.replace(dest)
    return {
        "raw_store_file": name,
        "raw_sha256": digest,
        "raw_byte_length": len(raw),
        "raw_store_kind": RAW_STORE_KIND,
    }


def capture_snapshot_with_raw(
    plan_game: Mapping[str, Any],
    slot_id: str,
    *,
    fetcher: FetcherFn,
    clock: ClockFn,
    raw_dir: Path,
    anchor: ClockFn | None = None,
) -> dict[str, Any]:
    """:func:`capture_snapshot` plus preservation of the exact response bytes.

    The bytes stored are the same object the fetcher returned and the
    parser consumed; nothing is refetched. Times come only from
    :func:`capture_snapshot`'s clock handling; this wrapper adds none.
    """
    seen: list[bytes] = []

    def keeping_fetcher(url: str) -> bytes:
        raw = fetcher(url)
        seen.append(raw)
        return raw

    record = capture_snapshot(
        plan_game, slot_id, fetcher=keeping_fetcher, clock=clock, anchor=anchor
    )
    if seen and record.get("response_sha256") is not None:
        link = store_raw_response(raw_dir, seen[-1])
        if link["raw_sha256"] != record["response_sha256"]:
            raise StarterCaptureError("RAW_RESPONSE_DIGEST_DIVERGED")
        record.update(link)
    return record


def verify_raw_store(capture_path: Path, raw_dir: Path) -> dict[str, Any]:
    """Fail closed unless every response-derived record's raw bytes verify."""
    raw_dir = Path(raw_dir)
    lines = _read_lines(Path(capture_path))

    def failure(reason: str, seq: int) -> dict[str, Any]:
        return {"ok": False, "records_checked": len(lines),
                "failure": {"reason": reason, "seq": seq},
                "raw_store_kind": RAW_STORE_KIND}

    verified = 0
    for index, line in enumerate(lines, start=1):
        try:
            record = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return failure("CAPTURE_RECORD_UNPARSEABLE", index)
        if not isinstance(record, dict):
            return failure("CAPTURE_RECORD_NOT_OBJECT", index)
        if record.get("response_sha256") is None:
            if any(k in record for k in ("raw_store_file", "raw_sha256")):
                return failure("RAW_LINK_WITHOUT_RESPONSE_DIGEST", index)
            continue  # attempt-failed records carry no response
        name = record.get("raw_store_file")
        digest = record.get("raw_sha256")
        length = record.get("raw_byte_length")
        if name is None or digest is None:
            return failure("RAW_LINK_MISSING", index)
        if record.get("raw_store_kind") != RAW_STORE_KIND:
            return failure("RAW_STORE_KIND_INVALID", index)
        if not _is_sha256_hex(digest) or digest != record["response_sha256"]:
            return failure("RAW_DIGEST_LINK_MISMATCH", index)
        if name != f"{digest}.json":
            return failure("RAW_STORE_PATH_UNSAFE", index)
        if type(length) is not int or length < 0:
            return failure("RAW_LENGTH_INVALID", index)
        path = raw_dir / name
        if path.is_symlink():
            return failure("RAW_STORE_PATH_UNSAFE", index)
        if not path.is_file():
            return failure("RAW_BYTES_MISSING", index)
        raw = path.read_bytes()
        if len(raw) != length or _sha256_hex(raw) != digest:
            return failure("RAW_BYTES_TAMPERED", index)
        verified += 1
    return {"ok": True, "records_checked": len(lines), "raw_verified": verified,
            "failure": None, "raw_store_kind": RAW_STORE_KIND}


# --------------------------------------------------------------------------
# Crash-safe, cross-process write-ahead commit (research-only, LOCAL).
# --------------------------------------------------------------------------
#
# Protocol, all under the manifest's never-unlinked fcntl lock:
#   1. append + fsync an INTENT line (``<manifest>.intent.jsonl``) carrying
#      the full canonical record, its digest, the raw digest, and the
#      #2166 receipt link keys (raw sha256 + source url);
#   2. raw bytes -> unique temp file, fsync, os.replace, fsync the directory;
#   3. append + fsync the capture line, then the manifest entry;
#   4. append + fsync a COMMIT line.
# ``recover_capture_store`` (also run before every commit) rolls a pending
# intent forward only when its raw bytes verify, or aborts it with a reason.
# Orphan blobs, temp files and torn terminal lines are MOVED to a quarantine
# directory with a reason file, never deleted. Anything not explained by an
# intent fails closed. No timestamps are written by this layer.
# This is local crash consistency, NOT an external anchor or WORM store.

SCHEMA_INTENT = "mlb_starter_capture_intent_v1"
SCHEMA_QUARANTINE = "mlb_starter_capture_quarantine_v1"


def _fsync_dir(path: Path) -> None:
    import os

    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _store_paths(manifest_path: Path, raw_dir: Path, quarantine_dir: Path | None):
    manifest_path = Path(manifest_path).resolve()
    raw_dir = Path(raw_dir).resolve()
    q = Path(quarantine_dir).resolve() if quarantine_dir else raw_dir.with_name(raw_dir.name + ".quarantine")
    return (manifest_path.with_name(manifest_path.name + ".lock"),
            manifest_path.with_name(manifest_path.name + ".intent.jsonl"), q)


def _quarantine_bytes(qdir: Path, label: str, data: bytes, reason: str) -> str:
    import os

    qdir.mkdir(parents=True, exist_ok=True)
    digest = _sha256_hex(data)
    base = f"{label}.{digest[:16]}.{os.getpid()}.{len(list(qdir.iterdir()))}"
    blob = qdir / (base + ".bin")
    with blob.open("wb") as h:
        h.write(data); h.flush(); os.fsync(h.fileno())
    meta = {"schema": SCHEMA_QUARANTINE, "label": label, "reason": reason,
            "sha256": digest, "byte_length": len(data)}
    with (qdir / (base + ".reason.json")).open("wb") as h:
        h.write(canonical_line(meta)); h.flush(); os.fsync(h.fileno())
    _fsync_dir(qdir)
    return base


def _quarantine_move(qdir: Path, path: Path, reason: str) -> str:
    import os

    data = path.read_bytes()
    base = _quarantine_bytes(qdir, path.name.lstrip("."), data, reason)
    os.unlink(path)
    _fsync_dir(path.parent)
    return base


def _repair_torn_tail(path: Path, qdir: Path, label: str) -> bool:
    """Move an unterminated final line to quarantine, truncate, fsync."""
    import os

    if not path.exists():
        return False
    raw = path.read_bytes()
    if not raw or raw.endswith(b"\n"):
        return False
    cut = raw.rfind(b"\n") + 1
    _quarantine_bytes(qdir, label, raw[cut:], f"TORN_TERMINAL_LINE:{path.name}")
    with path.open("r+b") as h:
        h.truncate(cut); h.flush(); os.fsync(h.fileno())
    return True


def _read_intents(intent_path: Path) -> list[dict[str, Any]]:
    """Validate journal record structure before recovery reads any fields.

    A schema tag alone is insufficient: a truncated but valid JSON object
    previously escaped as KeyError during pending-intent detection/replay.
    Corrupt journals remain untouched and fail closed for manual inspection.
    """
    out = []
    for i, line in enumerate(_read_lines(intent_path), start=1):
        def unique_pairs(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise StarterCaptureError(f"INTENT_DUPLICATE_JSON_KEY:{i}")
                obj[key] = value
            return obj

        try:
            obj = json.loads(
                line.decode("utf-8"), object_pairs_hook=unique_pairs,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    StarterCaptureError(f"INTENT_NONFINITE_NUMBER:{i}")
                ),
            )
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise StarterCaptureError(f"INTENT_LINE_UNPARSEABLE:{i}") from None
        if not isinstance(obj, dict) or obj.get("schema") != SCHEMA_INTENT:
            raise StarterCaptureError(f"INTENT_LINE_INVALID:{i}")
        state = obj.get("state")
        if state not in ("BEGIN", "COMMIT", "ABORT") or not _is_sha256_hex(obj.get("intent_id")):
            raise StarterCaptureError(f"INTENT_LINE_INVALID:{i}")
        if state == "BEGIN":
            base = obj.get("base_seq")
            raw_digest = obj.get("raw_sha256")
            receipt = obj.get("receipt_link")
            if (type(base) is not int or base < 0
                    or not _is_sha256_hex(obj.get("record_sha256"))
                    or not isinstance(obj.get("record_line"), str)
                    or (raw_digest is not None and not _is_sha256_hex(raw_digest))
                    or not isinstance(receipt, dict)
                    or receipt.get("sha256") != raw_digest
                    or (receipt.get("url") is not None
                        and not isinstance(receipt.get("url"), str))):
                raise StarterCaptureError(f"INTENT_LINE_INVALID:{i}")
        out.append(obj)
    return out


def _pending(intents: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Reject orphan/duplicate transitions instead of trusting terminal markers.

    An unpaired COMMIT must never hide a missing BEGIN; repeated BEGINs and
    duplicate closes likewise make journal integrity indeterminate. An ID may
    be retried only after its prior transaction has explicitly closed.
    """
    open_intents: dict[str, Mapping[str, Any]] = {}
    for intent in intents:
        ident = intent["intent_id"]  # _read_intents checked structural validity
        state = intent["state"]
        if state == "BEGIN":
            if ident in open_intents:
                raise StarterCaptureError("INTENT_DUPLICATE_BEGIN")
            open_intents[ident] = intent
        elif state in ("COMMIT", "ABORT"):
            if ident not in open_intents:
                raise StarterCaptureError("INTENT_ORPHAN_TERMINAL")
            del open_intents[ident]
        else:
            raise StarterCaptureError("INTENT_STATE_INVALID")
    return list(open_intents.values())


def _manifest_entry(record_line: bytes, record: Mapping[str, Any], seq: int, prev: str):
    digest = _sha256_hex(record_line)
    return {
        "schema": SCHEMA_MANIFEST_ENTRY, "seq": seq, "record_sha256": digest,
        "record_type": record.get("record_type"), "game_pk": record.get("game_pk"),
        "slot_id": record.get("slot_id"), "prev_chain_sha256": prev,
        "chain_sha256": _sha256_hex(f"{prev}:{digest}".encode("utf-8")),
    }


def _write_raw_atomic(raw_dir: Path, raw: bytes) -> str:
    import os

    digest = _sha256_hex(raw)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{digest}.json"
    if dest.is_symlink():
        raise StarterCaptureError("RAW_STORE_PATH_UNSAFE")
    if dest.exists():
        if dest.read_bytes() != raw:
            raise StarterCaptureError("RAW_STORE_COLLISION")
        return dest.name
    tmp = raw_dir / f".{dest.name}.{os.getpid()}.tmp"
    with tmp.open("wb") as h:
        h.write(raw); h.flush(); os.fsync(h.fileno())
    os.replace(tmp, dest)
    _fsync_dir(raw_dir)
    return dest.name


def _referenced_raw(capture_path: Path) -> set[str]:
    refs = set()
    for line in _read_lines(capture_path):
        try:
            rec = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(rec, dict) and isinstance(rec.get("raw_store_file"), str):
            refs.add(rec["raw_store_file"])
    return refs


def _recover_locked(capture_path, manifest_path, raw_dir, intent_path, qdir, verifier_now):
    import os

    actions: list[str] = []
    if _repair_torn_tail(intent_path, qdir, "intent_tail"):
        actions.append("QUARANTINED_TORN_INTENT_LINE")
    intents = _read_intents(intent_path)
    pend = _pending(intents)
    if len(pend) > 1:
        raise StarterCaptureError("INTENT_MULTIPLE_PENDING")
    if pend:
        # Torn capture/manifest tails are only repairable when an intent
        # explains them; otherwise verify_capture_chain fails closed.
        for p, label in ((capture_path, "capture_tail"), (manifest_path, "manifest_tail")):
            if _repair_torn_tail(p, qdir, label):
                actions.append(f"QUARANTINED_TORN_LINE:{p.name}")
        it = pend[0]
        line = it["record_line"].encode("utf-8")
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise StarterCaptureError("INTENT_RECORD_UNPARSEABLE") from None
        if not isinstance(record, dict):
            raise StarterCaptureError("INTENT_RECORD_NOT_OBJECT")
        if _sha256_hex(line) != it["record_sha256"] or canonical_line(record) != line:
            raise StarterCaptureError("INTENT_RECORD_DIGEST_MISMATCH")
        caps, mans = _read_lines(capture_path), _read_lines(manifest_path)
        base = it["base_seq"]
        raw_ok = True
        if it.get("raw_sha256") is not None:
            rp = raw_dir / f"{it['raw_sha256']}.json"
            raw_ok = rp.is_file() and not rp.is_symlink() and _sha256_hex(rp.read_bytes()) == it["raw_sha256"]
        state = None
        if len(caps) == base and len(mans) == base:
            state = "ROLL_FORWARD_FULL" if raw_ok else "ABORT_RAW_MISSING"
        elif len(caps) == base + 1 and caps[-1] == line and len(mans) in (base, base + 1):
            state = "ROLL_FORWARD_TAIL" if raw_ok else None
        if state is None:
            raise StarterCaptureError("INTENT_STATE_UNEXPLAINED")
        if state.startswith("ROLL_FORWARD"):
            prev = json.loads(mans[base - 1])["chain_sha256"] if base else GENESIS_CHAIN_SHA256
            entry = _manifest_entry(line, record, base + 1, prev)
            if len(caps) == base:
                _append_line(capture_path, line)
            if len(_read_lines(manifest_path)) == base:
                _append_line(manifest_path, canonical_line(entry))
            elif _read_lines(manifest_path)[-1] != canonical_line(entry):
                raise StarterCaptureError("INTENT_MANIFEST_DIVERGED")
            _append_line(intent_path, canonical_line({**_intent_head(it), "state": "COMMIT", "recovery": state}))
        else:
            _append_line(intent_path, canonical_line({**_intent_head(it), "state": "ABORT", "reason": state}))
        actions.append(state)
    # Temp files and unreferenced blobs: quarantine with reason, never drop.
    if raw_dir.exists():
        refs = _referenced_raw(capture_path)
        for p in sorted(raw_dir.iterdir()):
            if p.name.endswith(".tmp"):
                _quarantine_move(qdir, p, "RAW_TEMP_WITHOUT_RENAME")
                actions.append(f"QUARANTINED_TEMP:{p.name}")
            elif p.name not in refs:
                _quarantine_move(qdir, p, "RAW_ORPHAN_BLOB_UNREFERENCED")
                actions.append(f"QUARANTINED_ORPHAN:{p.name}")
    checked = verify_capture_chain(capture_path, manifest_path, verifier_now=verifier_now)
    if not checked["ok"]:
        raise StarterCaptureError(f"RECOVERY_CHAIN_INVALID:{checked['failure']['reason']}")
    return actions


def _intent_head(it: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": SCHEMA_INTENT, "intent_id": it["intent_id"]}


def _locked(lock_path: Path):
    import contextlib
    import fcntl

    @contextlib.contextmanager
    def cm():
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return cm()


def recover_capture_store(capture_path, manifest_path, raw_dir, *, quarantine_dir=None,
                          verifier_now: datetime | None = None) -> dict[str, Any]:
    """Roll forward / abort pending intents and quarantine orphans, under lock.

    Raises :class:`StarterCaptureError` (fail closed) on any state that no
    intent explains. Returns the list of actions taken."""
    capture_path, raw_dir = Path(capture_path).resolve(), Path(raw_dir).resolve()
    lock, intent, qdir = _store_paths(manifest_path, raw_dir, quarantine_dir)
    with _locked(lock):
        actions = _recover_locked(capture_path, Path(manifest_path).resolve(), raw_dir,
                                  intent, qdir, verifier_now)
    return {"ok": True, "actions": actions, "quarantine_dir": str(qdir)}


def commit_capture_atomic(capture_path, manifest_path, raw_dir, record: Mapping[str, Any],
                          raw: bytes | None, *, quarantine_dir=None,
                          verifier_now: datetime | None = None) -> dict[str, Any]:
    """Write-ahead, fcntl-serialized commit of raw bytes + capture + manifest.

    ``record`` comes from :func:`capture_snapshot`; this layer adds only the
    content-addressed raw link and never adds or alters a timestamp."""
    capture_path = Path(capture_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    raw_dir = Path(raw_dir).resolve()
    if capture_path == manifest_path:
        raise StarterCaptureError("CAPTURE_AND_MANIFEST_PATH_COLLIDE")
    record = dict(record)
    raw_digest = None
    if record.get("response_sha256") is not None:
        if not isinstance(raw, (bytes, bytearray)):
            raise StarterCaptureError("RAW_RESPONSE_NOT_BYTES")
        raw = bytes(raw)
        raw_digest = _sha256_hex(raw)
        if raw_digest != record["response_sha256"]:
            raise StarterCaptureError("RAW_RESPONSE_DIGEST_DIVERGED")
        record.update({"raw_store_file": f"{raw_digest}.json", "raw_sha256": raw_digest,
                       "raw_byte_length": len(raw), "raw_store_kind": RAW_STORE_KIND})
    elif raw is not None:
        raise StarterCaptureError("RAW_WITHOUT_RESPONSE_DIGEST")
    reason = _record_clock_failure(record, verifier_now)
    if reason is not None:
        raise StarterCaptureError(f"CAPTURE_RECORD_CLOCK_INVALID:{reason}")
    lock, intent_path, qdir = _store_paths(manifest_path, raw_dir, quarantine_dir)
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(lock):
        _recover_locked(capture_path, manifest_path, raw_dir, intent_path, qdir, verifier_now)
        line = canonical_line(record)
        mans = _read_lines(manifest_path)
        base = len(mans)
        prev = json.loads(mans[-1])["chain_sha256"] if mans else GENESIS_CHAIN_SHA256
        entry = _manifest_entry(line, record, base + 1, prev)
        intent_id = _sha256_hex(f"{prev}:{entry['record_sha256']}".encode())
        it = {"schema": SCHEMA_INTENT, "intent_id": intent_id, "state": "BEGIN",
              "base_seq": base, "record_sha256": entry["record_sha256"],
              "record_line": line.decode("utf-8"), "raw_sha256": raw_digest,
              "receipt_link": {"sha256": raw_digest, "url": record.get("source_url")}}
        _append_line(intent_path, canonical_line(it))                      # 1
        if raw_digest is not None:
            _write_raw_atomic(raw_dir, raw)                                 # 2
        _append_line(capture_path, line)                                    # 3a
        _append_line(manifest_path, canonical_line(entry))                  # 3b
        _append_line(intent_path, canonical_line({**_intent_head(it), "state": "COMMIT"}))  # 4
    return {**entry, "intent_id": intent_id, "record": record}


def verify_capture_store(capture_path, manifest_path, raw_dir, *, quarantine_dir=None,
                         verifier_now: datetime | None = None) -> dict[str, Any]:
    """Read-only. Fails closed on pending intents, orphans, temps, torn lines,
    chain or raw-byte failures. Does not repair; call recover_capture_store."""
    capture_path, raw_dir = Path(capture_path), Path(raw_dir)
    _, intent_path, _ = _store_paths(manifest_path, raw_dir, quarantine_dir)

    def fail(reason):
        return {"ok": False, "failure": {"reason": reason}, "raw_store_kind": RAW_STORE_KIND}

    if intent_path.exists() and intent_path.stat().st_size and not intent_path.read_bytes().endswith(b"\n"):
        return fail("INTENT_LINE_UNTERMINATED")
    try:
        if _pending(_read_intents(intent_path)):
            return fail("INTENT_UNCOMMITTED")
    except StarterCaptureError as exc:
        return fail(str(exc))
    if raw_dir.exists():
        refs = _referenced_raw(capture_path)
        for p in raw_dir.iterdir():
            if p.name.endswith(".tmp"):
                return fail("RAW_TEMP_PRESENT")
            if p.name not in refs:
                return fail("RAW_ORPHAN_BLOB")
    chain = verify_capture_chain(capture_path, manifest_path, verifier_now=verifier_now)
    if not chain["ok"]:
        return fail(chain["failure"]["reason"])
    raw = verify_raw_store(capture_path, raw_dir)
    if not raw["ok"]:
        return fail(raw["failure"]["reason"])
    return {"ok": True, "failure": None, "records_checked": chain["records_checked"],
            "raw_verified": raw["raw_verified"], "raw_store_kind": RAW_STORE_KIND}
