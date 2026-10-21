"""Check A R1 cohort assembly from our own DraftKings capture records.

Assembles candidate pairs for the merged numeric instrument
(sportsedge.oddspapi_numeric_admission_ad, PR #2446) from DraftKings
capture files committed under dk_line_archive (e.g. the Oct 20, 2026 NBA
1023_ct.json / 1722_ct.json scheduled captures). Each assembled sample
fills the `dk` side of a #2446 pair from a real capture row and leaves
`oddspapi` as None (unpaired): pairing happens only when the admission
run joins these samples to a frozen OddsPapi pull. An unpaired sample is
an honest denominator member, never a pass.

Identity and market conventions (assembly choices, recorded in the build
report; the #2446 instrument treats both as opaque exact-match strings):
  canonical_event_id = "<SPORT>:<game_date>:<AWAY>_AT_<HOME>"
                       (charset restricted to the #2446 instrument's
                       canonical-id pattern, which admits no "@")
  market_id          = SPREAD | MONEYLINE | TOTAL |
                       TEAM_TOTAL:<TEAM_ABBR> | PROP_<STAT>:<PLAYER_SLUG>
Each quote's source_sha256 is the SHA-256 of the canonical JSON of the
exact capture sub-object the quote was read from, so every assembled row
traces to a byte-stable slice of a committed capture file.

Fail-closed: a present-but-malformed market row refuses the whole
assembly with a named code. Absent markets are skipped and counted.
Outputs are EVIDENCE PACKETS ONLY (NOT_ADMITTED / NO_VERDICT); nothing
here certifies the cohort complete or any quote authentic.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from sportsedge.oddspapi_numeric_admission_ad import (
    VERSION as NUMERIC_DRYRUN_VERSION,
)

VERSION = "ODDSPAPI_R1_COHORT_V1"
BOOKMAKER = "draftkings"
_SLUG = re.compile(r"[^A-Z0-9]+")
_PROP_MARKETS = {
    "points": "PROP_POINTS",
    "rebounds": "PROP_REBOUNDS",
    "assists": "PROP_ASSISTS",
    "pra": "PROP_PRA",
}


class CohortAssemblyRefusal(ValueError):
    """Stable refusal code; never include raw capture text."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _source_sha(source_row: Any) -> str:
    return sha256(_canonical_json(source_row)).hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _price(value: Any) -> int:
    if not _is_int(value):
        raise CohortAssemblyRefusal("R1_PRICE_INVALID")
    return value


def _line(value: Any, *, required: bool) -> Any:
    if value is None:
        if required:
            raise CohortAssemblyRefusal("R1_LINE_MISSING")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CohortAssemblyRefusal("R1_LINE_INVALID")
    return value


def _captured_at(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise CohortAssemblyRefusal("R1_CAPTURED_AT_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CohortAssemblyRefusal("R1_CAPTURED_AT_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CohortAssemblyRefusal("R1_CAPTURED_AT_OFFSET_REQUIRED")
    return value


def _field(row: Mapping[str, Any], key: str) -> Any:
    if key not in row:
        raise CohortAssemblyRefusal("R1_QUOTE_FIELD_MISSING:" + key)
    return row[key]


class _Assembler:
    def __init__(self, capture_index: int, sport: str) -> None:
        self.capture_index = capture_index
        self.sport = sport
        self.samples: list[dict] = []
        self.skipped: dict[str, int] = {}

    def _skip(self, what: str) -> None:
        self.skipped[what] = self.skipped.get(what, 0) + 1

    def _add(self, event: str, market: str, side: str, line: Any,
             price: Any, captured_at: Any, source_row: Any) -> None:
        quote = {
            "canonical_event_id": event,
            "market_id": market,
            "bookmaker": BOOKMAKER,
            "side": side,
            "line": line,
            "captured_at_utc": _captured_at(captured_at),
            "american_price": _price(price),
            "source_sha256": _source_sha(source_row),
        }
        self.samples.append({
            "sample_id": f"R1-{self.capture_index:02d}-{len(self.samples):04d}",
            "dk": quote,
            "oddspapi": None,
        })

    def _two_sided(self, event: str, market: str, row: Mapping[str, Any],
                   first: tuple[str, str, str], second: tuple[str, str, str],
                   *, line_required: bool) -> None:
        for side, line_key, price_key in (first, second):
            line = _line(_field(row, line_key), required=line_required) \
                if line_key else None
            self._add(event, market, side, line, _field(row, price_key),
                      _field(row, "captured_at"), row)

    def game(self, game: Any) -> None:
        if not isinstance(game, Mapping):
            raise CohortAssemblyRefusal("R1_GAME_ROW_MALFORMED")
        for key in ("game_date", "away", "home", "away_name", "home_name"):
            if not isinstance(game.get(key), str) or not game.get(key):
                raise CohortAssemblyRefusal("R1_GAME_IDENTITY_INVALID:" + key)
        event = (f"{self.sport}:{game['game_date']}:"
                 f"{game['away']}_AT_{game['home']}")

        spread = game.get("spread")
        if isinstance(spread, Mapping):
            self._two_sided(event, "SPREAD", spread,
                            ("AWAY", "away_line", "away_price"),
                            ("HOME", "home_line", "home_price"),
                            line_required=True)
        else:
            self._skip("spread")
        moneyline = game.get("moneyline")
        if isinstance(moneyline, Mapping):
            self._two_sided(event, "MONEYLINE", moneyline,
                            ("AWAY", "", "away_price"),
                            ("HOME", "", "home_price"),
                            line_required=False)
        else:
            self._skip("moneyline")
        total = game.get("total")
        if isinstance(total, Mapping):
            self._two_sided(event, "TOTAL", total,
                            ("OVER", "line", "over_price"),
                            ("UNDER", "line", "under_price"),
                            line_required=True)
        else:
            self._skip("total")

        abbr_by_name = {game["home_name"]: game["home"],
                        game["away_name"]: game["away"]}
        team_totals = game.get("team_totals")
        if isinstance(team_totals, list):
            for entry in team_totals:
                if not isinstance(entry, Mapping):
                    raise CohortAssemblyRefusal("R1_TEAM_TOTAL_ROW_MALFORMED")
                team = entry.get("team")
                if team not in abbr_by_name:
                    raise CohortAssemblyRefusal("R1_TEAM_TOTAL_TEAM_UNKNOWN")
                self._two_sided(event, f"TEAM_TOTAL:{abbr_by_name[team]}",
                                entry,
                                ("OVER", "line", "over_price"),
                                ("UNDER", "line", "under_price"),
                                line_required=True)
        else:
            self._skip("team_totals")

        props = game.get("player_props")
        if isinstance(props, Mapping):
            for stat, market_prefix in _PROP_MARKETS.items():
                rows = props.get(stat)
                if not isinstance(rows, list):
                    continue
                for entry in rows:
                    if not isinstance(entry, Mapping):
                        raise CohortAssemblyRefusal("R1_PROP_ROW_MALFORMED")
                    player = entry.get("player")
                    if not isinstance(player, str) or not player:
                        raise CohortAssemblyRefusal("R1_PROP_PLAYER_MISSING")
                    slug = _SLUG.sub("_", player.upper()).strip("_")
                    self._two_sided(event, f"{market_prefix}:{slug}", entry,
                                    ("OVER", "line", "over_price"),
                                    ("UNDER", "line", "under_price"),
                                    line_required=True)
        else:
            self._skip("player_props")


def assemble_cohort(capture_paths: Sequence[str | Path]) -> dict:
    """Assemble #2446-shaped candidate pairs from DK capture files."""
    if not capture_paths:
        raise CohortAssemblyRefusal("R1_CAPTURE_LIST_EMPTY")
    all_samples: list[dict] = []
    files_meta = []
    totals = {"games": 0, "skipped": {}}
    for index, raw_path in enumerate(capture_paths):
        path = Path(raw_path)
        if not path.is_file():
            raise CohortAssemblyRefusal("R1_CAPTURE_FILE_MISSING")
        raw = path.read_bytes()
        try:
            capture = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CohortAssemblyRefusal("R1_CAPTURE_JSON_INVALID") from exc
        if not isinstance(capture, Mapping) \
                or not isinstance(capture.get("games"), list) \
                or not isinstance(capture.get("sport"), str):
            raise CohortAssemblyRefusal("R1_CAPTURE_SCHEMA_INVALID")
        assembler = _Assembler(index, capture["sport"].upper())
        # The same fixture legitimately appears in several captures
        # (AM entry + PM close are distinct samples of one event), so a
        # duplicate is a defect only WITHIN one capture file.
        seen_in_file: set[str] = set()
        for game in capture["games"]:
            assembler.game(game)
            event = (f"{assembler.sport}:{game['game_date']}:"
                     f"{game['away']}_AT_{game['home']}")
            if event in seen_in_file:
                raise CohortAssemblyRefusal(
                    "R1_DUPLICATE_EVENT_IN_CAPTURE:" + event)
            seen_in_file.add(event)
            totals["games"] += 1
        for what, count in assembler.skipped.items():
            totals["skipped"][what] = totals["skipped"].get(what, 0) + count
        all_samples.extend(assembler.samples)
        files_meta.append({"name": path.name, "sha256": sha256(raw).hexdigest(),
                           "bytes": len(raw)})
    manifest = sha256(_canonical_json([
        {"sample_id": s["sample_id"], "source_sha256": s["dk"]["source_sha256"]}
        for s in all_samples
    ])).hexdigest()
    return {
        "version": VERSION,
        "admission": "NOT_ADMITTED",
        "verdict": "NO_VERDICT",
        "evidence_state": "R1_COHORT_UNVERIFIED",
        "dk_cohort_manifest_sha256": manifest,
        "capture_files": files_meta,
        "counts": {"samples": len(all_samples), "games": totals["games"],
                   "skipped": totals["skipped"]},
        "dk_samples": all_samples,
    }


def build_numeric_dryrun_envelope(cohort: Mapping[str, Any],
                                  close_candidates: Sequence[Mapping[str, Any]]
                                  ) -> dict:
    """Emit exactly the fixed envelope the #2446 instrument consumes:
    {version, dk_cohort_manifest_sha256, dk_samples, close_candidates}."""
    if not isinstance(cohort, Mapping) \
            or cohort.get("version") != VERSION \
            or not isinstance(cohort.get("dk_samples"), list) \
            or not cohort.get("dk_samples"):
        raise CohortAssemblyRefusal("R1_COHORT_INVALID")
    return {
        "version": NUMERIC_DRYRUN_VERSION,
        "dk_cohort_manifest_sha256": cohort["dk_cohort_manifest_sha256"],
        "dk_samples": cohort["dk_samples"],
        "close_candidates": list(close_candidates),
    }


def build_close_candidate(provider_close: Mapping[str, Any],
                          instrument_anchor: Mapping[str, Any] | None) -> dict:
    """Assemble one #2446 close candidate from a provider close record
    plus an instrument-shaped first-play anchor (see
    oddspapi_first_play_anchors.to_instrument_anchor). A missing anchor
    is carried explicitly as None, which the #2446 instrument scores as
    D_INDEPENDENT_ACTUAL_FIRST_PLAY_NOT_SUPPLIED — never inferred."""
    if not isinstance(provider_close, Mapping):
        raise CohortAssemblyRefusal("R1_CLOSE_RECORD_INVALID")
    for key in ("canonical_event_id", "market_id", "provider_created_at_utc",
                "candidate_sha256"):
        if key not in provider_close:
            raise CohortAssemblyRefusal("R1_CLOSE_FIELD_MISSING:" + key)
    return {
        "canonical_event_id": provider_close["canonical_event_id"],
        "market_id": provider_close["market_id"],
        "bookmaker": BOOKMAKER,
        "provider_created_at_utc": provider_close["provider_created_at_utc"],
        "candidate_sha256": provider_close["candidate_sha256"],
        "actual_first_play": instrument_anchor,
    }
