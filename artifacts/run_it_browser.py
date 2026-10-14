"""Browser-assisted RUN IT: pull DK lines via browser, run through the system.

Flow:
1. User says "run it [scope]" (e.g., "run it NFL", "run it Bills/Rams")
2. Assistant spawns browser task to pull lines from DK for that scope
3. Browser returns lines in structured format
4. This module parses the lines and runs them through run_it_full.py
5. Returns research cards

The browser task prompt should request lines in this format:
    SOURCE: <Sportsbook the lines were read from>
    EVENT_ID: <DraftKings event ID, from the event page URL>
    NOTE: EVENT_ID <id> read from the DraftKings event page <URL>
    GAME: <Away> @ <Home> | <Date/Time>
    SPREAD: <Away> <line> (<odds>) | <Home> <line> (<odds>)
    TOTAL: O <line> (<odds>) | U <line> (<odds>)
    ML: <Away> (<odds>) | <Home> (<odds>)
    F5_ML: <Away> (<odds>) | <Home> (<odds>)
    F5_SPREAD: <Away> <line> (<odds>) | <Home> <line> (<odds>)
    F5_TOTAL: O <line> (<odds>) | U <line> (<odds>)
    FIRST_INNING: O <line> (<odds>) | U <line> (<odds>)

Intake contract (Oct 13, 2026 defect fix):
- The sport is supplied by the caller from the board/context being
  parsed and is stamped on every row at parse time. There is NO
  default sport: omitting it is a TypeError, an unrecognized sport is
  refused (INTAKE_SPORT_UNRECOGNIZED). A row can never be silently
  mislabeled by a hardcoded default.
- GAME header datetimes are parsed at intake from the documented
  formats (see parse_kickoff_datetime) and normalized to UTC ISO.
  Anything else is refused with a named reason -- a raw datetime
  string is never passed downstream to be guessed at.
- F5_* and FIRST_INNING rows keep their market identity in the
  parsed structure (F5_MONEYLINE / F5_SPREAD / F5_TOTAL, and the
  NRFI/YRFI pair). A period-prefixed line that matches no documented
  shape is refused (INTAKE_PERIOD_LINE_UNPARSEABLE), never dropped.
- The board's source is a declared fact, never an assumption: a
  "SOURCE: <sportsbook>" header line on the capture (or the caller's
  explicit board_book) is stamped onto every parsed row as `book`,
  the field the F5 quote-binding gate reads first. A capture that
  declares no source stamps nothing -- its F5 rows keep failing
  closed at that gate (F5_SOURCE_MISSING). No book name is ever
  hardcoded into rows whose capture did not declare it.
- The board's DraftKings event ID is a declared fact of the same
  provenance class: an "EVENT_ID: <draftkings event id>" header (the
  trailing number of the event page URL the lines were read from; the
  capture records that URL on the board as a NOTE provenance line)
  or the caller's explicit board_event_id is stamped as `event_id`
  onto the board's F5 rows only (F5_MONEYLINE / F5_SPREAD / F5_TOTAL
  here; F5_TEAM_TOTAL via the extended parser) -- the field the
  binding gate's second check reads (F5_EVENT_ID_MISSING). Game rows,
  full-game team totals and the first-inning pair carry no event
  identity to the binder and keep their exact shape. A capture that
  declares no event ID stamps nothing. A present-but-malformed
  declaration (non-numeric, empty, whitespace, or duplicated) refuses
  the parse (INTAKE_EVENT_ID_UNPARSEABLE) -- declared identity facts
  are never guessed at or silently dropped -- and an ID detached
  from a parsed fixture refuses too: no GAME header at all
  (INTAKE_EVENT_ID_UNBOUND_NO_GAME_CONTEXT) or a second GAME header
  under one declared ID (INTAKE_EVENT_ID_MULTIPLE_FIXTURES; one book
  event ID names exactly one fixture, so a multi-game capture must
  not declare a board-level ID). The binder performs no DK-event-to-
  StatsAPI mapping of its own -- the ID is pairing-group identity
  and evidence there -- and this stamp supplies no fixture identity:
  a fully stamped F5 row still stops at the binder's next check,
  F5_FIXTURE_BINDING_MISSING (no verified MLB gamePk on the row),
  until a capture format carries verified fixture identity.
"""

from datetime import datetime, timedelta, timezone
import re
import sys
import os
from zoneinfo import ZoneInfo

# run_it_full.py sits beside this module in artifacts/.
_artifacts_dir = os.path.dirname(os.path.abspath(__file__))
if _artifacts_dir not in sys.path:
    sys.path.insert(0, _artifacts_dir)
from run_it_full import run_full

SUPPORTED_SPORTS = frozenset({"NFL", "MLB", "NBA", "CFB"})

# Fixed UTC offsets for the US zone abbreviations used on DK boards.
# These are the daylight offsets in force during the fall season --
# the same convention the extended parser has always documented.
_TZ_ABBREV_OFFSETS = {"ET": -4, "CT": -5, "MT": -6, "PT": -7,
                      "UTC": 0, "GMT": 0}
_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}

_GAME_HEADER = re.compile(r'GAME:\s*(.+?)\s*@\s*(.+?)\s*\|\s*(.+)$')
_SPREAD_SHAPE = (r':\s*(.+?)\s+([+-]?\d+\.?\d*)\s*\(([+-]?\d+)\)\s*\|\s*'
               r'(.+?)\s+([+-]?\d+\.?\d*)\s*\(([+-]?\d+)\)')
_TOTAL_SHAPE = r':\s*O\s*(\d+\.?\d*)\s*\(([+-]?\d+)\)\s*\|\s*U\s*(\d+\.?\d*)\s*\(([+-]?\d+)\)'
_ML_SHAPE = r':\s*(.+?)\s*\(([+-]?\d+)\)\s*\|\s*(.+?)\s*\(([+-]?\d+)\)'


def validate_sport(sport):
    """Return the canonical sport code or fail closed with a named reason."""
    if sport is None or not str(sport).strip():
        raise ValueError("INTAKE_SPORT_REQUIRED")
    code = str(sport).strip().upper()
    if code not in SUPPORTED_SPORTS:
        raise ValueError(f"INTAKE_SPORT_UNRECOGNIZED:{sport}")
    return code


def _fixed_tz(abbrev):
    return timezone(timedelta(hours=_TZ_ABBREV_OFFSETS[abbrev]))


def _coerce_zone(board_tz):
    """Accept an IANA name or a tzinfo; return a tzinfo or None."""
    if board_tz is None:
        return None
    if isinstance(board_tz, str):
        try:
            return ZoneInfo(board_tz)
        except Exception:
            raise ValueError(f"INTAKE_BOARD_TIMEZONE_UNRECOGNIZED:{board_tz}")
    return board_tz


def board_zone_from_quote_time(text):
    """Extract the IANA zone declared on a board's QUOTE_TIME line.

    DK board reads end with e.g.
    "QUOTE_TIME: 2026-10-13 5:08 AM CDT (America/Chicago)". That zone
    is what relative-day GAME headers ("Today 7:00 PM") are expressed
    in. Returns the zone name, or None when the board declares none.
    """
    m = re.search(
        r'QUOTE_TIME:[^\n]*\(([A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+)+)\)',
        text or "")
    if not m:
        return None
    try:
        ZoneInfo(m.group(1))
    except Exception:
        return None
    return m.group(1)


def board_source_from_header(text):
    """Extract the sportsbook a board capture declares for itself.

    DK board reads carry a header line "SOURCE: DraftKings" naming
    the book the lines were read from. That declaration is the ONLY
    provenance the intake may stamp onto rows (as `book`): it is what
    the capture itself asserts, quoted verbatim. Returns the declared
    name, or None when the capture declares no source.
    """
    m = re.search(r'(?m)^\s*SOURCE:\s*(\S.*?)\s*$', text or "")
    if not m:
        return None
    return m.group(1) or None


_EVENT_ID_HEADER = re.compile(r'(?m)^\s*EVENT_ID:\s*(.*?)\s*$')
_EVENT_ID_SHAPE = re.compile(r'\d+')


def board_event_id_from_header(text):
    """Extract the DraftKings event ID a board header declares.

    The ID is the trailing number of the event page URL the lines
    were read from; the capture records that URL on the board as a
    NOTE provenance line. Returns the ID verbatim as a string, or
    None when the board declares none. A present-but-malformed
    declaration -- non-numeric, empty, whitespace-only, or more than
    one EVENT_ID line -- refuses with INTAKE_EVENT_ID_UNPARSEABLE:
    a declared identity fact that does not parse is never guessed
    at or silently dropped (the kickoff strictness convention).
    """
    matches = _EVENT_ID_HEADER.findall(text or "")
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            "INTAKE_EVENT_ID_UNPARSEABLE:multiple EVENT_ID declarations")
    raw = matches[0]
    if not _EVENT_ID_SHAPE.fullmatch(raw):
        raise ValueError(f"INTAKE_EVENT_ID_UNPARSEABLE:{raw}")
    return raw


def _validate_board_event_id(value):
    """Validate an explicitly supplied board event ID the same way."""
    raw = str(value).strip()
    if not _EVENT_ID_SHAPE.fullmatch(raw):
        raise ValueError(f"INTAKE_EVENT_ID_UNPARSEABLE:{value}")
    return raw


def _hour_24(hour, ampm):
    hour = int(hour)
    if ampm.upper() == "PM" and hour != 12:
        hour += 12
    if ampm.upper() == "AM" and hour == 12:
        hour = 0
    return hour


def parse_kickoff_datetime(value, *, reference_now, board_tz=None):
    """Parse a GAME header datetime to a UTC ISO-8601 string.

    Documented formats (anything else fails closed):
    - ISO-8601 with a timezone offset or Z, e.g. "2026-10-13T20:15:00-04:00"
    - "2026-10-13 20:15 ET" (zone abbreviation optional; default ET)
    - "Oct 13, 2026 8:15 PM ET" (zone abbreviation optional; default ET)
    - "Today 7:00 PM" / "Tomorrow 1:05 PM ET" -- relative-day headers
      resolve against reference_now in the stated zone, else in
      board_tz (the QUOTE_TIME-declared board zone or the caller's
      explicit zone). With no zone available anywhere they are refused
      (INTAKE_KICKOFF_TIMEZONE_UNRESOLVED) rather than guessed.

    Raises ValueError with a named reason:
    INTAKE_KICKOFF_MISSING / INTAKE_KICKOFF_UNPARSEABLE:<raw> /
    INTAKE_KICKOFF_TIMEZONE_REQUIRED:<raw> (well-formed but naive) /
    INTAKE_KICKOFF_TIMEZONE_UNRESOLVED:<raw> (relative day, no zone).
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("INTAKE_KICKOFF_MISSING")
    # ISO-8601 with a 'T' separator (must carry a timezone; naive ISO
    # is refused, not guessed). The space-separated board format is
    # handled by the next branch, not this one.
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', raw):
        iso = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            raise ValueError(f"INTAKE_KICKOFF_UNPARSEABLE:{raw}")
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(f"INTAKE_KICKOFF_TIMEZONE_REQUIRED:{raw}")
        return dt.astimezone(timezone.utc).isoformat()
    # "2026-10-13 20:15 ET"
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})\s*'
                 r'(ET|CT|MT|PT|UTC|GMT)?$', raw, re.I)
    if m:
        year, month, day, hour, minute, abbrev = m.groups()
        zone = _fixed_tz((abbrev or "ET").upper())
        dt = datetime(int(year), int(month), int(day), int(hour),
                      int(minute), tzinfo=zone)
        return dt.astimezone(timezone.utc).isoformat()
    # "Oct 13, 2026 8:15 PM ET"
    m = re.match(r'^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})'
                 r'\s*(AM|PM)\s*(ET|CT|MT|PT|UTC|GMT)?$', raw, re.I)
    if m:
        month_s, day, year, hour, minute, ampm, abbrev = m.groups()
        month = _MONTHS.get(month_s[:3].upper())
        if month is None:
            raise ValueError(f"INTAKE_KICKOFF_UNPARSEABLE:{raw}")
        zone = _fixed_tz((abbrev or "ET").upper())
        dt = datetime(int(year), month, int(day), _hour_24(hour, ampm),
                      int(minute), tzinfo=zone)
        return dt.astimezone(timezone.utc).isoformat()
    # "Today 7:00 PM" / "Tomorrow 1:05 PM ET"
    m = re.match(r'^(Today|Tomorrow)\s+(\d{1,2}):(\d{2})\s*(AM|PM)'
                 r'(?:\s+(ET|CT|MT|PT|UTC|GMT))?$', raw, re.I)
    if m:
        day_word, hour, minute, ampm, abbrev = m.groups()
        if abbrev:
            zone = _fixed_tz(abbrev.upper())
        else:
            zone = _coerce_zone(board_tz)
        if zone is None or reference_now is None or (
                reference_now.tzinfo is None
                or reference_now.utcoffset() is None):
            raise ValueError(f"INTAKE_KICKOFF_TIMEZONE_UNRESOLVED:{raw}")
        date = reference_now.astimezone(zone).date()
        if day_word.lower() == "tomorrow":
            date += timedelta(days=1)
        dt = datetime(date.year, date.month, date.day,
                      _hour_24(hour, ampm), int(minute), tzinfo=zone)
        return dt.astimezone(timezone.utc).isoformat()
    raise ValueError(f"INTAKE_KICKOFF_UNPARSEABLE:{raw}")


def parse_game_header(line, *, reference_now, board_tz=None):
    """Parse one GAME: header line.

    Returns {"away", "home", "kickoff"} (kickoff normalized to UTC
    ISO), None when the line is not a GAME header, and raises
    ValueError(INTAKE_GAME_HEADER_UNPARSEABLE) when a GAME: line does
    not carry the documented "Away @ Home | <datetime>" shape.
    """
    if not line.startswith("GAME:"):
        return None
    m = _GAME_HEADER.match(line)
    if not m:
        raise ValueError(f"INTAKE_GAME_HEADER_UNPARSEABLE:{line}")
    return {
        'away': m.group(1).strip(),
        'home': m.group(2).strip(),
        'kickoff': parse_kickoff_datetime(
            m.group(3).strip(), reference_now=reference_now,
            board_tz=board_tz),
    }


# Markets whose rows the F5 quote-binding gate reads an event
# identity from; only these carry a stamped `event_id`.
_F5_EVENT_STAMP_MARKETS = frozenset(
    {"F5_MONEYLINE", "F5_SPREAD", "F5_TOTAL"})


def _period_rows(line, current_game, sport, now, book=None, event_id=None):
    """Parse an F5_* / FIRST_INNING line, preserving market identity.

    The full-game counterparts live in parse_browser_lines; an F5 row
    must stay distinguishable from them end-to-end, so the parsed
    market names are F5_MONEYLINE / F5_SPREAD / F5_TOTAL, and the
    first-inning total becomes the NRFI/YRFI pair (NRFI carries the
    UNDER price, YRFI the OVER price). A period-prefixed line that
    matches no documented shape is refused, never silently dropped.

    `book` is the board capture's declared source (see
    board_source_from_header); when given it is stamped on every row,
    because the F5 quote-binding gate refuses a row that names no
    sportsbook. When the capture declared no source it stays None
    and the rows carry no `book` key at all.

    `event_id` is the board capture's declared DraftKings event ID
    (see board_event_id_from_header); when given it is stamped on
    the F5 rows only, because the binding gate reads an event
    identity from no other row -- the first-inning pair is a
    full-game-shaped market to the binder and is NOT stamped.
    """
    def _bound():
        if not current_game:
            raise ValueError(
                f"INTAKE_PERIOD_LINE_UNBOUND_NO_GAME_CONTEXT:{line}")

    def _stamp(rows):
        if book:
            for r in rows:
                r['book'] = book
        if event_id:
            for r in rows:
                if r['market'] in _F5_EVENT_STAMP_MARKETS:
                    r['event_id'] = event_id
        return rows

    m = re.match(r'F5_(?:ML|MONEYLINE)' + _ML_SHAPE, line)
    if m:
        _bound()
        return _stamp([
            {'sport': sport, 'away': current_game['away'],
             'home': current_game['home'], 'market': 'F5_MONEYLINE',
             'side': 'AWAY', 'odds': int(m.group(2)),
             'kickoff': current_game['kickoff'],
             'quote_captured_at': now.isoformat()},
            {'sport': sport, 'away': current_game['away'],
             'home': current_game['home'], 'market': 'F5_MONEYLINE',
             'side': 'HOME', 'odds': int(m.group(4)),
             'kickoff': current_game['kickoff'],
             'quote_captured_at': now.isoformat()},
        ])
    m = re.match(r'F5_SPREAD' + _SPREAD_SHAPE, line)
    if m:
        _bound()
        return _stamp([
            {'sport': sport, 'away': current_game['away'],
             'home': current_game['home'], 'market': 'F5_SPREAD',
             'side': 'AWAY', 'line': float(m.group(2)),
             'odds': int(m.group(3)), 'kickoff': current_game['kickoff'],
             'quote_captured_at': now.isoformat()},
            {'sport': sport, 'away': current_game['away'],
             'home': current_game['home'], 'market': 'F5_SPREAD',
             'side': 'HOME', 'line': float(m.group(5)),
             'odds': int(m.group(6)), 'kickoff': current_game['kickoff'],
             'quote_captured_at': now.isoformat()},
        ])
    m = re.match(r'F5_TOTAL' + _TOTAL_SHAPE, line)
    if m:
        _bound()
        return _stamp([
            {'sport': sport, 'away': current_game['away'],
             'home': current_game['home'], 'market': 'F5_TOTAL',
             'side': 'OVER', 'line': float(m.group(1)),
             'odds': int(m.group(2)), 'kickoff': current_game['kickoff'],
             'quote_captured_at': now.isoformat()},
            {'sport': sport, 'away': current_game['away'],
             'home': current_game['home'], 'market': 'F5_TOTAL',
             'side': 'UNDER', 'line': float(m.group(3)),
             'odds': int(m.group(4)), 'kickoff': current_game['kickoff'],
             'quote_captured_at': now.isoformat()},
        ])
    m = re.match(r'FIRST_INNING' + _TOTAL_SHAPE, line)
    if m:
        _bound()
        return _stamp([
            {'sport': sport, 'away': current_game['away'],
             'home': current_game['home'], 'market': 'YRFI',
             'side': 'OVER', 'line': float(m.group(1)),
             'odds': int(m.group(2)), 'kickoff': current_game['kickoff'],
             'quote_captured_at': now.isoformat()},
            {'sport': sport, 'away': current_game['away'],
             'home': current_game['home'], 'market': 'NRFI',
             'side': 'UNDER', 'line': float(m.group(3)),
             'odds': int(m.group(4)), 'kickoff': current_game['kickoff'],
             'quote_captured_at': now.isoformat()},
        ])
    raise ValueError(f"INTAKE_PERIOD_LINE_UNPARSEABLE:{line}")


_PERIOD_PREFIXES = ("F5_", "F5 ", "FIRST_INNING", "NRFI", "YRFI")


def parse_browser_lines(text, sport, now=None, board_tz=None,
                        board_book=None, board_event_id=None):
    """Parse browser line report into run_it_full.py line objects.

    `sport` is REQUIRED and comes from the board/context being parsed;
    it is stamped on every row here, at parse time.

    The board's source is resolved the same way as its zone: an
    explicit `board_book` argument wins; otherwise the capture's own
    "SOURCE: <sportsbook>" header declaration is used. The resolved
    value is stamped on every row as `book`. When neither exists the
    rows carry no `book` key -- nothing is assumed about provenance.

    The board's DraftKings event ID is resolved the same way: an
    explicit `board_event_id` argument wins; otherwise the capture's
    own "EVENT_ID: <id>" header declaration is used (see
    board_event_id_from_header). The resolved value is stamped as
    `event_id` on the board's F5 rows only -- the rows the F5
    quote-binding gate reads an event identity from. When neither
    exists the rows carry no `event_id` key. A declared ID is bound
    to the board's fixture: the parse refuses when no GAME header
    was parsed (INTAKE_EVENT_ID_UNBOUND_NO_GAME_CONTEXT) and when a
    second GAME header appears under one declared ID
    (INTAKE_EVENT_ID_MULTIPLE_FIXTURES).

    Expected format from browser:
        SOURCE: DraftKings
        EVENT_ID: 34817298
        NOTE: EVENT_ID 34817298 read from the DraftKings event page <URL>
        GAME: Buffalo Bills @ Los Angeles Rams | 2026-10-13 20:15 ET
        SPREAD: Bills +3.5 (-118) | Rams -3.5 (-102)
        TOTAL: O 54.5 (-118) | U 54.5 (-102)
        ML: Bills (+150) | Rams (-180)
    """
    sport = validate_sport(sport)
    if now is None:
        now = datetime.now(timezone.utc)
    if board_tz is None:
        board_tz = board_zone_from_quote_time(text)
    if board_book is None:
        board_book = board_source_from_header(text)
    if board_event_id is None:
        board_event_id = board_event_id_from_header(text)
    else:
        board_event_id = _validate_board_event_id(board_event_id)

    def _stamp(row):
        if board_book:
            row['book'] = board_book
        return row

    lines = []
    current_game = {}
    game_headers = 0

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Game header (strict: malformed GAME lines fail closed)
        header = parse_game_header(line, reference_now=now, board_tz=board_tz)
        if header is not None:
            if board_event_id and game_headers >= 1:
                raise ValueError("INTAKE_EVENT_ID_MULTIPLE_FIXTURES")
            game_headers += 1
            current_game = header
            continue

        # Period markets (F5 / first inning): identity preserved or refused
        if line.startswith(_PERIOD_PREFIXES):
            lines.extend(_period_rows(line, current_game, sport, now,
                                      book=board_book,
                                      event_id=board_event_id))
            continue

        # Spread
        m = re.match(r'SPREAD' + _SPREAD_SHAPE, line)
        if m and current_game:
            lines.append(_stamp({
                'sport': sport,
                'away': current_game['away'],
                'home': current_game['home'],
                'market': 'SPREAD',
                'side': 'AWAY',
                'line': float(m.group(2)),
                'odds': int(m.group(3)),
                'kickoff': current_game['kickoff'],
                'quote_captured_at': now.isoformat(),
            }))
            lines.append(_stamp({
                'sport': sport,
                'away': current_game['away'],
                'home': current_game['home'],
                'market': 'SPREAD',
                'side': 'HOME',
                'line': float(m.group(5)),
                'odds': int(m.group(6)),
                'kickoff': current_game['kickoff'],
                'quote_captured_at': now.isoformat(),
            }))
            continue

        # Total
        m = re.match(r'TOTAL' + _TOTAL_SHAPE, line)
        if m and current_game:
            lines.append(_stamp({
                'sport': sport,
                'away': current_game['away'],
                'home': current_game['home'],
                'market': 'TOTAL',
                'side': 'OVER',
                'line': float(m.group(1)),
                'odds': int(m.group(2)),
                'kickoff': current_game['kickoff'],
                'quote_captured_at': now.isoformat(),
            }))
            lines.append(_stamp({
                'sport': sport,
                'away': current_game['away'],
                'home': current_game['home'],
                'market': 'TOTAL',
                'side': 'UNDER',
                'line': float(m.group(3)),
                'odds': int(m.group(4)),
                'kickoff': current_game['kickoff'],
                'quote_captured_at': now.isoformat(),
            }))
            continue

        # Moneyline
        m = re.match(r'ML' + _ML_SHAPE, line)
        if m and current_game:
            lines.append(_stamp({
                'sport': sport,
                'away': current_game['away'],
                'home': current_game['home'],
                'market': 'MONEYLINE',
                'side': 'AWAY',
                'odds': int(m.group(2)),
                'kickoff': current_game['kickoff'],
                'quote_captured_at': now.isoformat(),
            }))
            lines.append(_stamp({
                'sport': sport,
                'away': current_game['away'],
                'home': current_game['home'],
                'market': 'MONEYLINE',
                'side': 'HOME',
                'odds': int(m.group(4)),
                'kickoff': current_game['kickoff'],
                'quote_captured_at': now.isoformat(),
            }))
            continue

    if board_event_id and game_headers == 0:
        # A declared event ID with no parsed fixture to bind to is a
        # detached identity claim: refuse rather than stamp nothing.
        raise ValueError("INTAKE_EVENT_ID_UNBOUND_NO_GAME_CONTEXT")
    return lines


def run_browser_lines(browser_text, sport, now=None):
    """Run browser-pulled lines through the system.

    Args:
        browser_text: Raw text from browser task with lines
        sport: Sport code for THIS board (NFL, MLB, NBA, CFB) --
            required, rows are labeled with it at parse time.
        now: Datetime for the run (defaults to now)

    Returns:
        Research card dict from run_full()
    """
    if now is None:
        now = datetime.now(timezone.utc)

    lines = parse_browser_lines(browser_text, sport=sport, now=now)

    print(f"Parsed {len(lines)} lines from browser report")

    card = run_full({"lines": lines}, now=now, auto_context=False)
    return card


def format_card_summary(card):
    """Format a research card into a human-readable summary."""
    output = []
    output.append(f"Schema: {card.get('schema')}")

    rows = card.get("evaluated_rows", [])
    output.append(f"\nEvaluated: {len(rows)} lines")

    for r in rows:
        market = r.get('market')
        side = r.get('side')
        line = r.get('line')
        status = r.get('status')
        line_str = f" {line}" if line is not None else ""
        output.append(f"  {market} {side}{line_str}: {status}")

    # Edges
    edges = [r for r in rows if 'POSITIVE_EV' in r.get('status', '')]
    if edges:
        output.append(f"\nPositive EV (unvalidated): {len(edges)}")
        for e in edges:
            output.append(f"  {e.get('market')} {e.get('line', '')}")
    else:
        output.append("\nNo positive EV found.")

    # Blocked
    blocked = [r for r in rows if 'BLOCKED' in r.get('status', '')]
    if blocked:
        output.append(f"\nBlocked: {len(blocked)}")
        for b in blocked:
            output.append(f"  {b.get('market')} {b.get('side')}: {b.get('status')}")

    return "\n".join(output)


# Browser task prompt template
BROWSER_PROMPT_TEMPLATE = """Go to DraftKings Sportsbook (https://sportsbook.draftkings.com) and find the current odds for {scope}.

For each game, report the lines in EXACTLY this format:
SOURCE: DraftKings
EVENT_ID: <the DraftKings event ID -- the trailing number of the event page URL you read the lines from (…/event/<game>/<EVENT_ID>); include it when this report covers a single game read from its event page, omit it otherwise>
NOTE: EVENT_ID <id> read from the DraftKings event page <the full event page URL>
GAME: <Away Team> @ <Home Team> | <Date/Time>
SPREAD: <Away> <line> (<odds>) | <Home> <line> (<odds>)
TOTAL: O <line> (<odds>) | U <line> (<odds>)
ML: <Away> (<odds>) | <Home> (<odds>)
F5_ML: <Away> (<odds>) | <Home> (<odds>)
F5_SPREAD: <Away> <line> (<odds>) | <Home> <line> (<odds>)
F5_TOTAL: O <line> (<odds>) | U <line> (<odds>)
FIRST_INNING: O <line> (<odds>) | U <line> (<odds>)

Example:
GAME: Buffalo Bills @ Los Angeles Rams | 2026-10-13 20:15 ET
SPREAD: Bills +3.5 (-118) | Rams -3.5 (-102)
TOTAL: O 54.5 (-118) | U 54.5 (-102)
ML: Bills (+150) | Rams (-180)

Do NOT place bets, log in, or click betting links. Research only — just read the public odds.
Return ONLY the lines in the format above, one game per block."""


def get_browser_prompt(scope):
    """Get the browser task prompt for a given scope."""
    return BROWSER_PROMPT_TEMPLATE.format(scope=scope)
