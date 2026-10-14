"""In-run verified gamePk resolution for canonical-card F5 rows.

The F5 quote binder (sportsedge.mlb_f5_quote_binding) refuses any F5
quote that carries no verified MLB gamePk identity
(F5_FIXTURE_BINDING_MISSING, its gate 2.5) -- and it only VERIFIES a
claimed gamePk (its own fixture_resolver cross-checks the claim
against the official StatsAPI schedule: team names, first pitch
within 120s, strictly-pregame capture). Nothing upstream of the
binder ever produced that claim on the canonical card path: DK text
boards carry no gamePk, and the staged RUN IT drivers verified the
gamePk externally, outside the path. This module is the in-run
resolution the canonical path was missing.

Resolution contract (fail closed everywhere):

* The gamePk originates ONLY from a live MLB StatsAPI schedule read
  performed inside the run -- the same sportsedge.mlb_source
  fetch_schedule read the binder's own resolver verifies against --
  keyed by the fixture's two team names and the board's stated first
  pitch. It NEVER comes from board text, a board header, or any
  caller-supplied identity.
* Exactly one schedule game matching both team names (binder-style
  normalization) on the fixture's slate date -> stamp its gamePk.
* Several matches (a doubleheader) -> disambiguate by the stated
  first pitch vs the scheduled first pitches, using the binder's own
  120-second tolerance: exactly one candidate inside the tolerance
  stamps; zero or several inside it stamps NOTHING.
* Zero matches, a missing/unparseable fixture context, or a failed
  schedule read -> stamp NOTHING. The rows then stop at the binder's
  gate 2.5 exactly as they did before this module existed.
* A row that already carries a parseable positive game_pk/game_id
  claim is passed through untouched: this module never overwrites an
  intake claim. The binder's fixture resolver verifies claims (a
  wrong-fixture claim refuses F5_FIXTURE_BINDING_MISMATCH there), and
  overwriting would mask exactly the disagreement that gate exists
  to catch.
* Only F5 rows (the binder's normalize_f5_market set) are stamped.
  Every other row passes through as the identical object; inputs are
  never mutated.

Provenance: each stamped row copy carries a game_pk_provenance
record (resolution source, resolution timestamp, slate date, matched
first pitch), and the function returns one receipt per fixture group
for the run record. The binder ignores the provenance key (proven by
test); its canonical quote is built from verified fields only.

This module grants no pricing authority: stamped rows still face the
binder's fixture verification, pairing and settlement-basis gates,
and finally the F5 deployment eligibility gate
(F5_DEPLOYMENT_NOT_ELIGIBLE while config/deployments.json holds the
F5 markets ineligible). Research only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .mlb_f5_quote_binding import normalize_f5_market, opener_from_getter
from .mlb_source import fetch_schedule, parse_game_start

RESOLUTION_VERSION = "MLB_F5_FIXTURE_RESOLUTION_V1"
RESOLUTION_SOURCE = "STATSAPI_SCHEDULE"
CHICAGO_TZ = ZoneInfo("America/Chicago")
# Mirrors the binder's FIRST_PITCH_TOLERANCE_SECONDS: the resolution
# disambiguates a doubleheader by the same bound the binder will use
# to cross-check the stamped fixture.
FIRST_PITCH_TOLERANCE_SECONDS = 120

STATUS_RESOLVED = "RESOLVED"
STATUS_PREEXISTING = "PREEXISTING_GAME_PK"
STATUS_NO_MATCH = "NO_MATCH"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_NO_CONTEXT = "NO_FIXTURE_CONTEXT"
STATUS_FETCH_FAILED = "FETCH_FAILED"
STATUS_UNAVAILABLE = "RESOLUTION_UNAVAILABLE"


def _norm_name(value: Any) -> str:
    """Team-name normalization identical to the binder's _norm_name."""
    return " ".join(
        str(value or "").strip().lower().replace(".", "").split())


def _parse_instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(
                str(value or "").strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _claimed_game_pk(row: Mapping[str, Any]) -> int | None:
    """The row's own parseable positive gamePk claim, if it has one --
    the same parse the binder's gate 2.5 applies."""
    raw = row.get("game_pk")
    if raw in (None, ""):
        raw = row.get("game_id")
    try:
        pk = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return pk if pk > 0 else None


def _is_f5_row(row: Mapping[str, Any]) -> bool:
    if normalize_f5_market(row.get("market")) is None:
        return False
    sport = str(row.get("sport") or "").strip().upper()
    return sport in ("", "MLB")


def stamp_f5_game_pks(rows: Sequence[Mapping[str, Any]], *,
                      getter: Callable | None = None,
                      opener: Callable | None = None,
                      resolved_at: datetime | None = None
                      ) -> tuple[list, list[dict[str, Any]]]:
    """Stamp verified gamePk identity onto F5 rows, in-run.

    Returns (rows_out, receipts): rows_out is aligned with the input
    (unstamped rows are the identical objects; stamped rows are
    copies) and receipts carries one provenance record per fixture
    group for the run record. NEVER raises: any failure leaves the
    rows unstamped, which is exactly the pre-existing fail-closed
    behavior at the binder's gate 2.5.
    """
    resolved_at = resolved_at or datetime.now(timezone.utc)
    if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
        resolved_at = datetime.now(timezone.utc)
    out: list = list(rows)
    receipts: list[dict[str, Any]] = []
    try:
        _stamp(rows, out, receipts, getter=getter, opener=opener,
               resolved_at=resolved_at)
    except Exception as exc:  # resolution must never kill the run
        receipts.append({
            "source": RESOLUTION_VERSION, "status": STATUS_UNAVAILABLE,
            "detail": f"{type(exc).__name__}: {exc}",
            "rows_stamped": 0,
        })
        return list(rows), receipts
    return out, receipts


def _stamp(rows, out, receipts, *, getter, opener, resolved_at) -> None:
    # Group the F5 rows that need resolution by fixture context.
    groups: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping) or not _is_f5_row(row):
            continue
        if _claimed_game_pk(row) is not None:
            key = ("claimed", i)
            groups[key] = {"claimed": True, "indices": [i], "row": row}
            order.append(key)
            continue
        kickoff = _parse_instant(
            row.get("kickoff") or row.get("commence_time"))
        away = _norm_name(row.get("away"))
        home = _norm_name(row.get("home"))
        if kickoff is None or not away or not home:
            key = ("context", i)
            groups[key] = {"claimed": False, "context_missing": True,
                           "indices": [i], "row": row}
            order.append(key)
            continue
        key = ("fixture", away, home, kickoff.isoformat())
        if key not in groups:
            groups[key] = {
                "claimed": False, "context_missing": False,
                "indices": [], "away": row.get("away"),
                "home": row.get("home"), "kickoff": kickoff,
                "slate_date": kickoff.astimezone(
                    CHICAGO_TZ).date().isoformat(),
            }
            order.append(key)
        groups[key]["indices"].append(i)

    if opener is None and any(
            not g["claimed"] and not g["context_missing"]
            for g in groups.values()):
        if getter is not None:
            opener = opener_from_getter(getter)
        else:
            from urllib.request import urlopen
            opener = urlopen

    schedules: dict[str, Any] = {}  # slate_date -> games list | Exception

    def _schedule_for(slate_date: str):
        if slate_date not in schedules:
            try:
                schedules[slate_date] = fetch_schedule(
                    slate_date, opener=opener)
            except Exception as exc:  # fail closed per date, never raise
                schedules[slate_date] = exc
        return schedules[slate_date]

    for key in order:
        group = groups[key]
        receipt: dict[str, Any] = {
            "source": RESOLUTION_VERSION,
            "rows": len(group["indices"]),
            "rows_stamped": 0,
        }
        receipts.append(receipt)
        if group["claimed"]:
            receipt["status"] = STATUS_PREEXISTING
            receipt["detail"] = (
                "row carries its own gamePk claim; resolution never "
                "overwrites an intake claim -- the binder's fixture "
                "resolver verifies it")
            continue
        if group["context_missing"]:
            receipt["status"] = STATUS_NO_CONTEXT
            receipt["detail"] = (
                "row lacks a parseable timezone-aware kickoff or a "
                "team name, so no fixture can be resolved for it")
            continue
        receipt.update({
            "away": group["away"], "home": group["home"],
            "kickoff": group["kickoff"].isoformat(),
            "slate_date": group["slate_date"],
        })
        games = _schedule_for(group["slate_date"])
        if isinstance(games, Exception):
            receipt["status"] = STATUS_FETCH_FAILED
            receipt["detail"] = (
                f"StatsAPI schedule read failed for "
                f"{group['slate_date']}: {type(games).__name__}: {games}")
            continue
        candidates = [
            g for g in games
            if _norm_name(g.away_name) == _norm_name(group["away"])
            and _norm_name(g.home_name) == _norm_name(group["home"])
        ]
        receipt["candidates_matched"] = len(candidates)
        chosen = None
        basis = None
        if len(candidates) == 1:
            chosen, basis = candidates[0], "SOLE_NAME_MATCH"
        elif len(candidates) > 1:
            in_tolerance = []
            for game in candidates:
                try:
                    pitch = parse_game_start(game.game_date)
                except Exception:
                    continue
                if abs((pitch - group["kickoff"]).total_seconds()) \
                        <= FIRST_PITCH_TOLERANCE_SECONDS:
                    in_tolerance.append(game)
            if len(in_tolerance) == 1:
                chosen, basis = in_tolerance[0], \
                    "FIRST_PITCH_DISAMBIGUATION"
        if chosen is None:
            receipt["status"] = (STATUS_NO_MATCH if not candidates
                                 else STATUS_AMBIGUOUS)
            receipt["detail"] = (
                "no schedule game matches both team names on the slate "
                "date" if not candidates else
                f"{len(candidates)} schedule games match the fixture "
                "and the stated first pitch does not select exactly "
                "one inside the 120s tolerance; refusing to guess")
            continue
        first_pitch = parse_game_start(chosen.game_date)
        receipt.update({
            "status": STATUS_RESOLVED, "basis": basis,
            "game_pk": int(chosen.game_pk),
            "matched_first_pitch_at": first_pitch.isoformat(),
            "resolution_source": RESOLUTION_SOURCE,
            "resolved_at": resolved_at.isoformat(),
        })
        for i in group["indices"]:
            stamped = dict(rows[i])
            stamped["game_pk"] = int(chosen.game_pk)
            stamped["game_pk_provenance"] = {
                "source": RESOLUTION_SOURCE,
                "resolved_at": resolved_at.isoformat(),
                "slate_date": group["slate_date"],
                "matched_first_pitch_at": first_pitch.isoformat(),
                "basis": basis,
            }
            out[i] = stamped
            receipt["rows_stamped"] += 1
