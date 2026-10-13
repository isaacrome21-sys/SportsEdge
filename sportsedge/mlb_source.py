from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace, dataclass, asdict
from datetime import datetime, timedelta, timezone
import hashlib
import uuid
import time as _time
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterator
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .source_lineage import canonical_game_identity

BASE = "https://statsapi.mlb.com"
SAVANT_PREVIEW_BASE = "https://baseballsavant.mlb.com/preview"
CHICAGO_TZ = ZoneInfo("America/Chicago")


class MLBSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GameSnapshot:
    game_pk: int
    game_date: str
    status: str
    away_id: int
    away_name: str
    home_id: int
    home_name: str
    away_probable_pitcher_id: int | None
    away_probable_pitcher_name: str | None
    home_probable_pitcher_id: int | None
    home_probable_pitcher_name: str | None
    retrieved_at: str
    source: str = "MLB_STATSAPI_SCHEDULE"
    game_number: int | None = None
    double_header: str | None = None
    venue_id: int | None = None
    official_date: str | None = None
    detailed_status: str | None = None
    game_type: str | None = None
    # Caller's own timestamp (e.g. run as-of); never receipt evidence. Bounded in fetch_schedule.
    caller_asserted_at: str | None = None


RECEIPT_CLOCK_SKEW = timedelta(seconds=5)
# A claimed fetch receipt older than this cannot be certified by the current
# independent system clock. This is a transport-ingestion limit, not evidence
# that data were present at a historical game as-of instant.
RECEIPT_ANCHOR_MAX_AGE = timedelta(seconds=30)
RECEIPT_MAX_FETCH_SPAN = timedelta(seconds=30)


def _trusted_now() -> datetime:
    """Trusted system clock for fetch start / receipt. Not injectable by callers or
    recorders; only tests monkeypatch this module attribute."""
    return _DATETIME.fromtimestamp(_time.time_ns() / 1e9, tz=timezone.utc)


_utc_clock = _trusted_now  # backward-compatible name; same trusted source


_DATETIME = datetime  # unpatched type for isinstance checks


def _aware(value: Any, label: str) -> datetime:
    if not isinstance(value, _DATETIME) or value.tzinfo is None or value.utcoffset() is None:
        raise MLBSourceError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def bound_caller_time(value: datetime, *, fetch_started_at: datetime, received_at: datetime,
                      skew: timedelta = RECEIPT_CLOCK_SKEW) -> datetime:
    """Fail closed unless fetch_started_at <= value <= received_at + skew."""
    v = _aware(value, "caller-supplied time")
    if v < fetch_started_at:
        raise MLBSourceError("CALLER_TIME_BEFORE_FETCH_START")
    if v > received_at + skew:
        raise MLBSourceError("CALLER_TIME_IN_FUTURE")
    return v


@dataclass(frozen=True)
class MLBSourceCaptureRecord:
    sequence: int
    source_kind: str
    url: str
    observed_at_utc: str
    sha256: str
    path: str
    byte_length: int
    game_pk: int | None = None
    # Persisted receipt bounds from the trusted module clock. observed_at_utc is
    # ALWAYS equal to received_at_utc (post-read completion), never earlier.
    fetch_started_at_utc: str | None = None
    received_at_utc: str | None = None
    # Non-evidentiary: the injectable recorder clock's own assertion, kept only
    # for diagnostics. Never used as a receipt or PIT time.
    recorder_clock_assertion_utc: str | None = None
    receipt_nonce: str | None = None
    prev_record_sha256: str | None = None
    record_sha256: str | None = None


RECEIPT_JOURNAL_NAME = "receipt_journal.jsonl"
GENESIS_SHA256 = "0" * 64
RECEIPT_PLAUSIBLE_FLOOR = datetime(2020, 1, 1, tzinfo=timezone.utc)
_HASHED_FIELDS = (
    "sequence", "source_kind", "url", "observed_at_utc", "sha256", "file_name",
    "byte_length", "game_pk", "fetch_started_at_utc", "received_at_utc",
    "recorder_clock_assertion_utc", "receipt_nonce", "prev_record_sha256",
)


def _record_hash(entry: dict[str, Any]) -> str:
    body = {k: entry.get(k) for k in _HASHED_FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MLBSourceError(f"RECEIPT_FIELD_MISSING:{label}")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MLBSourceError(f"RECEIPT_FIELD_INVALID:{label}") from exc
    if dt.tzinfo is None:
        raise MLBSourceError(f"RECEIPT_FIELD_NAIVE:{label}")
    return dt.astimezone(timezone.utc)


def verify_receipt_journal(root: str | Path, *, verifier_now: datetime | None = None) -> list[dict[str, Any]]:
    """Independently re-verify a persisted capture directory (fresh process / restart).

    Fails closed on: missing fields, broken hash chain, edited entries, raw byte
    tamper, observed != received, received < fetch start, fetch span over the limit,
    implausible (pre-2020 or future vs verifier clock) receipts, duplicate nonces or
    duplicate receipt tuples. The chain is local tamper-evidence only; it is NOT an
    external, independently anchored timestamp.
    """
    root = Path(root)
    journal = root / RECEIPT_JOURNAL_NAME
    if not journal.exists():
        return []
    now = _aware(verifier_now, "verifier clock") if verifier_now is not None else _aware(_trusted_now(), "verifier clock")
    entries: list[dict[str, Any]] = []
    prev = GENESIS_SHA256
    nonces: set[str] = set()
    keys: set[tuple[str, str, str, str]] = set()
    for lineno, line in enumerate(journal.read_text().splitlines(), start=1):
        if not line.strip():
            raise MLBSourceError(f"RECEIPT_JOURNAL_BLANK_LINE:{lineno}")
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MLBSourceError(f"RECEIPT_JOURNAL_CORRUPT:{lineno}") from exc
        for field in _HASHED_FIELDS + ("record_sha256",):
            if field not in entry or (entry[field] is None and field not in ("game_pk", "recorder_clock_assertion_utc")):
                raise MLBSourceError(f"RECEIPT_FIELD_MISSING:{field}")
        if entry["sequence"] != lineno:
            raise MLBSourceError("RECEIPT_SEQUENCE_GAP")
        if entry["prev_record_sha256"] != prev:
            raise MLBSourceError("RECEIPT_CHAIN_BROKEN")
        if _record_hash(entry) != entry["record_sha256"]:
            raise MLBSourceError("RECEIPT_RECORD_TAMPERED")
        start = _parse_utc(entry["fetch_started_at_utc"], "fetch_started_at_utc")
        received = _parse_utc(entry["received_at_utc"], "received_at_utc")
        observed = _parse_utc(entry["observed_at_utc"], "observed_at_utc")
        if observed != received:
            raise MLBSourceError("RECEIPT_OBSERVED_NOT_POST_READ")
        if received < start:
            raise MLBSourceError("RECEIPT_CLOCK_WENT_BACKWARDS")
        if received - start > RECEIPT_MAX_FETCH_SPAN:
            raise MLBSourceError("RECEIPT_FETCH_SPAN_UNBOUNDED")
        if start < RECEIPT_PLAUSIBLE_FLOOR:
            raise MLBSourceError("RECEIPT_IMPLAUSIBLY_OLD")
        if received > now + RECEIPT_CLOCK_SKEW:
            raise MLBSourceError("RECEIPT_FUTURE_VS_VERIFIER")
        key = (entry["url"], entry["sha256"], entry["fetch_started_at_utc"], entry["received_at_utc"])
        if entry["receipt_nonce"] in nonces or key in keys:
            raise MLBSourceError("RECEIPT_DUPLICATE_REPLAY")
        nonces.add(entry["receipt_nonce"]); keys.add(key)
        raw_path = root / entry["file_name"]
        if not raw_path.exists():
            raise MLBSourceError("RECEIPT_RAW_BYTES_MISSING")
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"] or len(raw) != entry["byte_length"]:
            raise MLBSourceError("RECEIPT_RAW_BYTES_TAMPERED")
        prev = entry["record_sha256"]
        entries.append(entry)
    return entries


def receipt_supports_as_of(entry: dict[str, Any], as_of: datetime) -> bool:
    """A receipt can only evidence pregame availability if bytes were received at or
    before ``as_of``. A schedule fetched today for an old game is never as-of proof."""
    received = _parse_utc(entry.get("received_at_utc") if isinstance(entry, dict) else None, "received_at_utc")
    return received <= _aware(as_of, "as_of")


class MLBSourceCapture:
    """Append-only recorder for the exact StatsAPI bytes consumed by inference.

    Capture is opt-in. Existing callers behave identically when no capture context
    is active. A recorder never refetches a source; it persists the bytes returned
    by the same response object that is subsequently JSON-decoded by the model.
    """

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None):
        self.root = Path(root)
        self.clock = clock or (lambda: _trusted_now())
        self.records: list[MLBSourceCaptureRecord] = []
        self._used_receipts: set[tuple[str, str, str, str]] = set()
        self._used_nonces: set[str] = set()
        self._prev_sha = GENESIS_SHA256
        self._sequence = 0
        # Restart: reload and re-verify persisted state so a new recorder at the
        # same root cannot re-admit a receipt tuple already in the journal.
        for entry in verify_receipt_journal(self.root):
            self._used_receipts.add((entry["url"], entry["sha256"], entry["fetch_started_at_utc"], entry["received_at_utc"]))
            self._used_nonces.add(entry["receipt_nonce"])
            self._prev_sha = entry["record_sha256"]
            self._sequence = entry["sequence"]

    @staticmethod
    def _identity(url: str) -> tuple[str, int | None]:
        if "/api/v1/schedule" in url:
            return "MLB_STATSAPI_SCHEDULE", None
        match = re.search(r"/api/v1/game/(\d+)/boxscore(?:\?|$)", url)
        if match:
            return "MLB_STATSAPI_BOXSCORE", int(match.group(1))
        return "MLB_STATSAPI_OTHER", None

    def record(self, *, url: str, raw: bytes, fetch_started_at: datetime,
               received_at: datetime) -> MLBSourceCaptureRecord:
        """Require an independent system-time anchor, not the recorder clock.

        Caller-provided fetch bounds alone are not evidence. Reject stale,
        future, implausibly long and duplicate receipt claims before writing.
        This still is not a signed cross-process PIT receipt or proof of a
        historical sportsbook/StatsAPI state; all capture remains research.
        """
        try:
            observed = _aware(self.clock(), "source capture clock")
        except MLBSourceError:
            raise MLBSourceError("source capture clock must return timezone-aware datetime")
        start = _aware(fetch_started_at, "trusted fetch start")
        receipt = _aware(received_at, "trusted receipt")
        if receipt < start:
            raise MLBSourceError("RECEIPT_CLOCK_WENT_BACKWARDS")
        bound_caller_time(observed, fetch_started_at=start, received_at=receipt)
        try:
            anchor = _aware(_trusted_now(), "independent system receipt anchor")
        except Exception as exc:
            raise MLBSourceError("RECEIPT_ANCHOR_UNAVAILABLE") from exc
        if receipt > anchor + RECEIPT_CLOCK_SKEW:
            raise MLBSourceError("RECEIPT_FUTURE_VS_SYSTEM_ANCHOR")
        if receipt < anchor - RECEIPT_ANCHOR_MAX_AGE:
            raise MLBSourceError("RECEIPT_STALE_OR_REPLAYED")
        if receipt - start > RECEIPT_MAX_FETCH_SPAN:
            raise MLBSourceError("RECEIPT_FETCH_SPAN_UNBOUNDED")
        source_kind, game_pk = self._identity(url)
        digest = hashlib.sha256(raw).hexdigest()
        receipt_key = (url, digest, start.isoformat(), receipt.isoformat())
        if receipt_key in self._used_receipts:
            raise MLBSourceError("RECEIPT_DUPLICATE_REPLAY")
        if start < RECEIPT_PLAUSIBLE_FLOOR:
            raise MLBSourceError("RECEIPT_IMPLAUSIBLY_OLD")
        nonce = uuid.uuid4().hex
        while nonce in self._used_nonces:
            nonce = uuid.uuid4().hex
        sequence = self._sequence + 1
        suffix = f"game_{game_pk}" if game_pk is not None else source_kind.lower()
        name = f"{sequence:04d}_{suffix}_{digest}.json"
        destination = self.root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != raw:
            raise MLBSourceError("immutable raw source capture collision")
        destination.write_bytes(raw)
        entry = {
            "sequence": sequence, "source_kind": source_kind, "url": url,
            # Canonical observation == trusted post-read completion. Never earlier.
            "observed_at_utc": receipt.isoformat(), "sha256": digest, "file_name": name,
            "byte_length": len(raw), "game_pk": game_pk,
            "fetch_started_at_utc": start.isoformat(), "received_at_utc": receipt.isoformat(),
            "recorder_clock_assertion_utc": observed.isoformat(), "receipt_nonce": nonce,
            "prev_record_sha256": self._prev_sha,
        }
        entry["record_sha256"] = _record_hash(entry)
        with open(self.root / RECEIPT_JOURNAL_NAME, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()
        record = MLBSourceCaptureRecord(
            sequence=sequence, source_kind=source_kind, url=url,
            observed_at_utc=entry["observed_at_utc"], sha256=digest, path=str(destination),
            byte_length=len(raw), game_pk=game_pk,
            fetch_started_at_utc=entry["fetch_started_at_utc"], received_at_utc=entry["received_at_utc"],
            recorder_clock_assertion_utc=entry["recorder_clock_assertion_utc"], receipt_nonce=nonce,
            prev_record_sha256=entry["prev_record_sha256"], record_sha256=entry["record_sha256"],
        )
        self.records.append(record)
        self._used_receipts.add(receipt_key)
        self._used_nonces.add(nonce)
        self._prev_sha = entry["record_sha256"]
        self._sequence = sequence
        return record

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": "MLB_SAME_FETCH_PIT_SOURCE_CAPTURE_V1",
            "receipt_schema_version": 2,
            "receipt_journal": RECEIPT_JOURNAL_NAME,
            "receipt_chain_head_sha256": self._prev_sha,
            "receipt_time_semantics": "OBSERVED_EQUALS_TRUSTED_POST_READ_RECEIPT",
            "external_time_anchor": False,
            "capture_semantics": "SAME_RESPONSE_BYTES_CONSUMED_BY_MODEL",
            "promotion_authority": False,
            "retroactive_point_in_time_claim": False,
            "records": [asdict(record) for record in self.records],
        }


_ACTIVE_SOURCE_CAPTURE: ContextVar[MLBSourceCapture | None] = ContextVar(
    "sportsedge_mlb_source_capture", default=None
)


@contextmanager
def capture_mlb_source_bytes(
    root: str | Path,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Iterator[MLBSourceCapture]:
    """Capture exact MLB source bytes used inside this context, without refetching."""
    recorder = MLBSourceCapture(Path(root), clock=clock)
    token = _ACTIVE_SOURCE_CAPTURE.set(recorder)
    try:
        yield recorder
    finally:
        _ACTIVE_SOURCE_CAPTURE.reset(token)


def _get_json(url: str, opener: Callable = urlopen) -> dict[str, Any]:
    recorder = _ACTIVE_SOURCE_CAPTURE.get()
    started = _trusted_now()
    try:
        with opener(url, timeout=15) as r:
            raw = r.read()
        if not isinstance(raw, (bytes, bytearray)):
            raise MLBSourceError("MLB response body must be bytes")
        raw_bytes = bytes(raw)
        if recorder is not None:
            recorder.record(url=url, raw=raw_bytes, fetch_started_at=started, received_at=_trusted_now())
        return json.loads(raw_bytes.decode("utf-8"))
    except MLBSourceError:
        raise
    except Exception as exc:
        raise MLBSourceError(f"MLB fetch failed: {exc}") from exc


def _pitcher(team: dict[str, Any]) -> tuple[int | None, str | None]:
    p = team.get("probablePitcher") or {}
    return p.get("id"), p.get("fullName")


def parse_game_start(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MLBSourceError("schedule game missing gameDate")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBSourceError(f"invalid MLB gameDate: {value}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBSourceError("MLB gameDate must be timezone-aware")
    return dt.astimezone(timezone.utc)


def game_time_chicago(value: str | GameSnapshot) -> str:
    raw = value.game_date if isinstance(value, GameSnapshot) else value
    return parse_game_start(raw).astimezone(CHICAGO_TZ).isoformat()


def savant_preview_url(snapshot: GameSnapshot) -> str:
    """Return the canonical Baseball Savant Statcast Game Preview URL for a game."""
    if snapshot.official_date:
        try:
            game_day = datetime.fromisoformat(snapshot.official_date).date()
        except ValueError as exc:
            raise MLBSourceError(f"invalid MLB officialDate: {snapshot.official_date}") from exc
    else:
        game_day = parse_game_start(snapshot.game_date).astimezone(CHICAGO_TZ).date()
    return (
        f"{SAVANT_PREVIEW_BASE}?game_pk={snapshot.game_pk}"
        f"&game_date={game_day.strftime('%m/%d/%Y')}"
    )


def _optional_positive_int(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise MLBSourceError(f"{name} must be a positive integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBSourceError(f"{name} must be a positive integer") from exc
    if out <= 0:
        raise MLBSourceError(f"{name} must be a positive integer")
    return out


def parse_schedule(payload: dict[str, Any], retrieved_at: datetime) -> list[GameSnapshot]:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise MLBSourceError("retrieved_at must be timezone-aware")
    out: list[GameSnapshot] = []
    seen_game_pks: set[int] = set()
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            if not all((game.get("gamePk"), away_team.get("id"), home_team.get("id"))):
                raise MLBSourceError("schedule game missing identity")
            game_pk = int(game["gamePk"])
            if game_pk in seen_game_pks:
                raise MLBSourceError(f"duplicate gamePk in schedule: {game_pk}")
            seen_game_pks.add(game_pk)
            game_start = parse_game_start(game.get("gameDate"))
            apid, apname = _pitcher(away)
            hpid, hpname = _pitcher(home)
            status_obj = game.get("status") or {}
            abstract_status = status_obj.get("abstractGameState")
            if abstract_status not in {"Preview", "Live", "Final"}:
                raise MLBSourceError("GAME_STATE_MISSING_OR_INVALID")
            game_type = game.get("gameType")
            if game_type is not None and (type(game_type) is not str or not game_type or len(game_type) > 2):
                raise MLBSourceError("GAME_TYPE_INVALID")
            detailed_status = status_obj.get("detailedState")
            if detailed_status is not None:
                detailed_status = str(detailed_status)
            game_number = _optional_positive_int("gameNumber", game.get("gameNumber"))
            double_header = game.get("doubleHeader")
            if double_header is not None:
                double_header = str(double_header)
                if double_header not in {"Y", "N", "S"}:
                    raise MLBSourceError("doubleHeader must be Y, N, S, or null")
            if double_header in {"Y", "S"} and game_number is None:
                raise MLBSourceError("doubleheader game missing gameNumber")
            venue_id = _optional_positive_int("venue.id", (game.get("venue") or {}).get("id"))
            official_date = game.get("officialDate") or date_block.get("date")
            if official_date is not None:
                official_date = str(official_date)
            out.append(GameSnapshot(
                game_pk, game_start.isoformat(), str(abstract_status),
                int(away_team["id"]), str(away_team.get("name", "")),
                int(home_team["id"]), str(home_team.get("name", "")),
                apid, apname, hpid, hpname,
                retrieved_at.astimezone(timezone.utc).isoformat(),
                game_number=game_number, double_header=double_header,
                venue_id=venue_id, official_date=official_date,
                detailed_status=detailed_status,
                game_type=game_type,
            ))
    out.sort(key=lambda g: (parse_game_start(g.game_date), g.game_pk))
    return out


def fetch_schedule(date_iso: str, opener: Callable = urlopen, now: datetime | None = None) -> list[GameSnapshot]:
    """retrieved_at is ALWAYS the post-fetch clock. A caller-supplied ``now`` is kept
    only as ``caller_asserted_at`` and must satisfy fetch_start <= now <= receipt + skew."""
    url = (
        f"{BASE}/api/v1/schedule?sportId=1&date={date_iso}"
        "&gameType=R,F,D,L,W,A,S,E&hydrate=probablePitcher,team"
    )
    fetch_started_at = _aware(_trusted_now(), "receipt clock")
    payload = _get_json(url, opener)
    retrieved_at = _aware(_trusted_now(), "receipt clock")
    if retrieved_at < fetch_started_at:
        raise MLBSourceError("RECEIPT_CLOCK_WENT_BACKWARDS")
    games = parse_schedule(payload, retrieved_at)
    if now is None:
        return games
    asserted = bound_caller_time(now, fetch_started_at=fetch_started_at, received_at=retrieved_at).isoformat()
    return [replace(g, caller_asserted_at=asserted) for g in games]


def parse_confirmed_lineup(boxscore: dict[str, Any], side: str) -> list[dict[str, Any]]:
    if side not in ("home", "away"):
        raise MLBSourceError("side must be home or away")
    team = ((boxscore.get("teams") or {}).get(side) or {})
    players = team.get("players") or {}
    lineup: list[dict[str, Any]] = []
    for player in players.values():
        order = player.get("battingOrder")
        person = player.get("person") or {}
        if order is None or int(order) <= 0:
            continue
        code = int(order)
        slot, sequence = divmod(code, 100)
        lineup.append({
            "player_id": person.get("id"),
            "name": person.get("fullName"),
            "batting_order_code": code,
            "slot": slot,
            "sequence": sequence,
            "substitution_evidence": sequence > 0,
        })
    lineup.sort(key=lambda x: (x["slot"], x["sequence"], x["player_id"] or 0))
    return lineup


def fetch_boxscore(game_pk: int, opener: Callable = urlopen) -> dict[str, Any]:
    return _get_json(f"{BASE}/api/v1/game/{int(game_pk)}/boxscore", opener)


def game_identity(snapshot: GameSnapshot):
    return canonical_game_identity(
        mlb_game_pk=snapshot.game_pk,
        scheduled_start=snapshot.game_date,
        away_team_id=snapshot.away_id,
        home_team_id=snapshot.home_id,
        game_number=snapshot.game_number,
    )


def snapshot_to_dict(snapshot: GameSnapshot) -> dict[str, Any]:
    out = asdict(snapshot)
    identity = game_identity(snapshot)
    out["game_time_utc"] = parse_game_start(snapshot.game_date).isoformat()
    out["game_time_ct"] = game_time_chicago(snapshot)
    out["sportsedge_game_id"] = identity.sportsedge_game_id
    out["mlb_game_pk"] = identity.mlb_game_pk
    out["savant_preview_url"] = savant_preview_url(snapshot)
    return out
