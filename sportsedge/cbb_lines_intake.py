"""DraftKings CBB lines-issue intake — the [CBB LINES] grammar.

The CBB forward runners (PR #2907) consume the shared intake parser's
output shape through ``games_from_board``, but the shared parser had
no CBB adapter: ``adapter_for("CBB")`` raised and no live [CBB LINES]
body could be parsed at all. The adapter itself lives in
``sportsedge/pipeline/adapters.py`` (market/team name mapping only,
mirroring the CFB table). This module is the CBB-specific intake
wrapper around it, in the pattern of ``nfl_lines_intake`` and
``nba_period_lines_intake``:

* Priced lines parse through the shared parser with
  ``strict_unknown=True`` — a priced body line whose market label the
  CBB adapter does not know FAILS the game with
  ``CBB_INTAKE_UNRECOGNIZED`` instead of being skipped with a warning
  (the NFL lesson: a silently dropped priced line is a corrupted
  capture). The adapter registers exactly the four markets the
  forward runners consume: MONEYLINE, SPREAD, TOTAL, TEAM_TOTAL.
  Everything else DK shows (first-half lines, player props, TD-style
  specials, SGP material) belongs in the line-3 HTML comment, where
  the parser strips it; the CBB_CAPTURE_V1 census manifest is a
  separate grammar (``sportsedge/cbb_capture_scope.py``), not this
  one.

Grammar (one game block, exactly as the lane posts it)::

    Notre Dame Fighting Irish @ Villanova Wildcats
    Captured: 2026-11-01T07:26:00-06:00
    <!-- DK event: 33221100; ESPN event: 401920982; ... -->
    ML +110 -130
    Spread +2.5 -110 -110
    Total 141.5 -110 -110
    TeamTotal Notre Dame Fighting Irish 69.5 -110 -110
    TeamTotal Villanova Wildcats 72.5 -110 -110

* Event ids: the shared parser strips HTML comments before parsing,
  so this wrapper scans the raw body's comments itself and carries
  each game's ``DK event:`` and ``ESPN event:`` ids onto the capture.
  The ESPN event id is what the Nov 1 pre-check joins the DK slate to
  the admitted crosswalk (PR #2898) with; DK display names are NOT
  identity and no name-based join is invented here — a body whose
  comment carries no ESPN event id yields ``espn_event_id=None``,
  stamped, never backfilled. Two comments in one game carrying
  different ids for the same kind refuse ``CBB_INTAKE_EVENT_ID_CONFLICT``;
  a comment id that disagrees with the fixture's refuses
  ``CBB_INTAKE_EVENT_ID_MISMATCH``.

* Identity and the Illinois exclusion: identity is fixture-supplied —
  ``fixtures`` is the same table the runners' ``games_from_board``
  consumes, keyed on the board's "AWAY@HOME" display-name pair, with
  ``espn_event_id``, ``away_espn_id`` / ``home_espn_id`` and
  ``institution_state_away`` / ``institution_state_home`` per game
  (plus optional ``capture_excluded_illinois_away`` / ``_home`` flags
  sourced from the crosswalk). When a fixture covers a game, a team
  the capture-scope rule excludes refuses the whole parse with
  ``CBB_INTAKE_ILLINOIS_COLLEGE_EXCLUDED``. The rule is the scope
  module's (``sportsedge/cbb_capture_scope.py``): an ESPN ID on its
  denylist denies, an Illinois institution state denies, the
  crosswalk's exclusion flag denies. The denylist is IMPORTED from
  that module — never copied — so intake excludes exactly what the
  scope module excludes. A game with no fixture is stamped
  ``identity_state="UNVERIFIED"``: names alone cannot apply an
  ESPN-ID rule, and nothing here pretends otherwise (the runners
  re-apply the same exclusion at pricing time).

This module records captures only. It prices nothing, starts no
clock, and confers no eligibility.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

from sportsedge.cbb_capture_scope import (
    _ILLINOIS_ESPN_MBB_2027_DENYLIST as ILLINOIS_ESPN_DENYLIST,
)
from sportsedge.pipeline.intake import (
    SharedIntakeError,
    SharedMarket,
    parse_header,
    parse_issue,
)


class CbbLinesIntakeError(ValueError):
    pass


REFUSAL_ILLINOIS_EXCLUDED = "CBB_INTAKE_ILLINOIS_COLLEGE_EXCLUDED"
REFUSAL_EVENT_ID_CONFLICT = "CBB_INTAKE_EVENT_ID_CONFLICT"
REFUSAL_EVENT_ID_MISMATCH = "CBB_INTAKE_EVENT_ID_MISMATCH"
REFUSAL_EVENT_ALIGNMENT = "CBB_INTAKE_EVENT_ALIGNMENT_FAILED"

IDENTITY_FIXTURE_SUPPLIED = "FIXTURE_SUPPLIED"
IDENTITY_UNVERIFIED = "UNVERIFIED"

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_EVENT_PATTERNS = (
    ("espn_event_id", re.compile(r"\bESPN\s+event\s*:\s*([0-9]+)", re.IGNORECASE)),
    ("dk_event_id", re.compile(r"\bDK\s+event\s*:\s*([0-9]+)", re.IGNORECASE)),
)


@dataclass
class CbbGameCapture:
    away: str
    home: str
    header: str
    captured_at: Optional[str]
    espn_event_id: Optional[str]    # from the issue comment; None when absent
    dk_event_id: Optional[str]      # from the issue comment; None when absent
    identity_state: str             # FIXTURE_SUPPLIED | UNVERIFIED
    markets: list = field(default_factory=list)   # list[SharedMarket]

    def to_dict(self) -> dict[str, Any]:
        """The SharedGame dict shape (away/home/header/captured_at/
        markets), plus the comment-carried event ids and the identity
        state as additive keys."""
        return {"away": self.away, "home": self.home,
                "header": self.header, "captured_at": self.captured_at,
                "espn_event_id": self.espn_event_id,
                "dk_event_id": self.dk_event_id,
                "identity_state": self.identity_state,
                "markets": [asdict(m) for m in self.markets]}


@dataclass
class CbbBoardCapture:
    sport: str
    games: list = field(default_factory=list)     # list[CbbGameCapture]
    warnings: list = field(default_factory=list)
    board_captured_at: Optional[str] = None

    def to_board_dict(self) -> dict[str, Any]:
        """The SharedBoard.to_dict() shape the CBB forward runners
        consume through games_from_board, with each game additionally
        carrying its comment-stated event ids and identity state."""
        return {"sport": self.sport,
                "games": [g.to_dict() for g in self.games],
                "warnings": list(self.warnings),
                "board_captured_at": self.board_captured_at}


def _norm_name(text: str) -> str:
    return " ".join(str(text).split())


def _comment_buckets(body: str) -> list[dict[str, Any]]:
    """Walk the raw body once, in body order, mirroring the shared
    parser's own game detection: a header line (the parser's
    ``parse_header`` on non-comment text) opens a new bucket; an HTML
    comment attaches to the bucket it falls in. Comments before the
    first header attach to bucket 0 (the title-fallback game). Each
    bucket: {"header": (away, home) | None, "espn_event_id": ...,
    "dk_event_id": ...} with id keys present only when carried."""
    buckets: list[dict[str, Any]] = []
    current = -1

    def note_text(text: str) -> None:
        nonlocal current
        for raw in text.splitlines():
            line = raw.strip().strip("`").strip()
            if not line:
                continue
            header = parse_header(line)
            if header:
                buckets.append({"header": header})
                current = len(buckets) - 1

    def note_comment(comment: str) -> None:
        idx = current if current >= 0 else 0
        while len(buckets) <= idx:
            buckets.append({"header": None})
        bucket = buckets[idx]
        for kind, pattern in _EVENT_PATTERNS:
            match = pattern.search(comment)
            if match:
                value = match.group(1)
                if kind in bucket and bucket[kind] != value:
                    raise CbbLinesIntakeError(
                        f"{REFUSAL_EVENT_ID_CONFLICT}:{kind}:"
                        f"{bucket[kind]} vs {value}")
                bucket[kind] = value

    pos = 0
    for match in _COMMENT.finditer(body):
        note_text(body[pos:match.start()])
        note_comment(match.group(0))
        pos = match.end()
    note_text(body[pos:])
    return buckets


def _illinois_excluded(espn_id: Any, institution_state: Any,
                       capture_excluded_flag: Any) -> bool:
    """The capture-scope module's exclusion rule, in its fail-closed
    form: an Illinois ESPN ID denies (the denylist is imported from
    sportsedge.cbb_capture_scope, never copied, so it cannot drift);
    an Illinois institution state denies; the crosswalk's
    capture_excluded_illinois flag denies."""
    if espn_id is not None and str(espn_id) in ILLINOIS_ESPN_DENYLIST:
        return True
    if (institution_state is not None
            and str(institution_state).strip().upper() == "IL"):
        return True
    return bool(capture_excluded_flag)


def parse_cbb_lines(body: str, *, title: str | None = None,
                    fixtures: Mapping[str, Mapping[str, Any]] | None = None
                    ) -> CbbBoardCapture:
    """Parse one [CBB LINES] issue body, strict.

    ``fixtures`` (optional) is the fixture identity table the forward
    runners consume, keyed on the board's "AWAY@HOME" display-name
    pair. When it covers a game, its ESPN event id must agree with
    the comment's, and neither team may be Illinois-excluded under
    the capture-scope rule — both failures refuse the whole parse.
    Games the table does not cover are stamped UNVERIFIED and are
    never priced downstream (games_from_board skips them)."""
    try:
        board = parse_issue(body, "CBB", title=title, strict_unknown=True)
    except SharedIntakeError as exc:
        raise CbbLinesIntakeError(str(exc)) from exc

    buckets = _comment_buckets(body)
    if buckets and len(buckets) != len(board.games):
        raise CbbLinesIntakeError(
            f"{REFUSAL_EVENT_ALIGNMENT}:{len(buckets)} comment buckets "
            f"vs {len(board.games)} parsed games")

    captures: list[CbbGameCapture] = []
    for idx, game in enumerate(board.games):
        bucket = buckets[idx] if idx < len(buckets) else {"header": None}
        header = bucket.get("header")
        if header is not None and (
                _norm_name(header[0]) != game.away
                or _norm_name(header[1]) != game.home):
            raise CbbLinesIntakeError(
                f"{REFUSAL_EVENT_ALIGNMENT}:{header} vs "
                f"{game.away} @ {game.home}")
        espn_event_id = bucket.get("espn_event_id")
        dk_event_id = bucket.get("dk_event_id")

        identity_state = IDENTITY_UNVERIFIED
        if fixtures is not None:
            fixture = fixtures.get(f"{game.away}@{game.home}")
            if fixture is not None:
                identity_state = IDENTITY_FIXTURE_SUPPLIED
                fixture_event = fixture.get("espn_event_id")
                if (espn_event_id is not None and fixture_event is not None
                        and str(fixture_event) != espn_event_id):
                    raise CbbLinesIntakeError(
                        f"{REFUSAL_EVENT_ID_MISMATCH}:"
                        f"{game.away} @ {game.home}: comment "
                        f"{espn_event_id} vs fixture {fixture_event}")
                for side, name in (("away", game.away), ("home", game.home)):
                    if _illinois_excluded(
                            fixture.get(f"{side}_espn_id"),
                            fixture.get(f"institution_state_{side}"),
                            fixture.get(
                                f"capture_excluded_illinois_{side}", False)):
                        raise CbbLinesIntakeError(
                            f"{REFUSAL_ILLINOIS_EXCLUDED}:"
                            f"{game.away} @ {game.home}:{side}:{name}")
        captures.append(CbbGameCapture(
            away=game.away, home=game.home, header=game.header,
            captured_at=game.captured_at,
            espn_event_id=espn_event_id, dk_event_id=dk_event_id,
            identity_state=identity_state,
            markets=list(game.markets)))
    return CbbBoardCapture(sport=board.sport, games=captures,
                           warnings=list(board.warnings),
                           board_captured_at=board.board_captured_at)


__all__ = [
    "CbbBoardCapture",
    "CbbGameCapture",
    "CbbLinesIntakeError",
    "IDENTITY_FIXTURE_SUPPLIED",
    "IDENTITY_UNVERIFIED",
    "REFUSAL_EVENT_ALIGNMENT",
    "REFUSAL_EVENT_ID_CONFLICT",
    "REFUSAL_EVENT_ID_MISMATCH",
    "REFUSAL_ILLINOIS_EXCLUDED",
    "parse_cbb_lines",
]
