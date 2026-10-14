#!/usr/bin/env python3
"""QB_IDENTITY_EVIDENCE Form 2 -- DEPTH_ROSTER_COMPOSITE (CFB only).

Owner ruling (Isaac, Oct 13, 2026; issue #2154): Form 2 is approved as
an IDENTITY-ONLY, research-stage evidence path for the CFB pre-pricing
QB gate. It implements the contract proposed in
``cfb_qb_alternative_source_20261013/PROPOSAL.md`` section 4 verbatim.

The composite, admitted ONLY for a CFB team whose ESPN injury-feed
status is ``TEAM_NOT_IN_INJURY_FEED`` (Form 1 cannot cover it):

  1. MEMBERSHIP -- an ESPN roster snapshot for the fixture team, pulled
     by team ID at an asserted-complete limit (?limit=1000 plus the
     count-stability assertion), providing athlete-ID-keyed,
     team-scoped membership. No ordering, no availability content.
  2. DEPTH_ORDER -- an OurLads depth-chart snapshot captured under
     receipt discipline (pre-kickoff capture, SHA-256 of the captured
     bytes, source URL, retrieval timestamp, on-page update stamp
     recorded verbatim), providing a projected QB ordering. No athlete
     IDs, no availability content.
  3. Resolution join -- the chart's named QB1 (name + jersey) must
     resolve to EXACTLY ONE athlete ID on the fixture team's roster
     snapshot, at position QB. Zero matches, multiple matches, a
     non-QB match, an incomplete roster snapshot, a missing bundle, or
     a stale bundle each fail closed with a distinct status (section
     4.5 of the proposal; two modes the proposal does not name are
     coined in the same style and marked below).

What Form 2 establishes, and what it never establishes:

  * IDENTITY limb: satisfied on a pass, at projected-editorial
    strength, recorded as
    QB_IDENTITY_SATISFIED_FORM2_DEPTH_ROSTER_COMPOSITE.
  * AVAILABILITY limb: NOT satisfied -- by Form 2 or by any free
    source -- for teams outside the ESPN injury feed. Availability
    stays EXPLICITLY UNKNOWN, labeled
    AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT wherever the record
    is printed. Form 2 evidence is never read as availability, health,
    or a clean injury report.
  * ``injury_points`` under Form 2 is exactly 0.0. There is no report
    to extract Out/Doubtful designations from, so there is nothing to
    extract; deriving an injury adjustment from depth order would be
    an invented probability and is prohibited.

Capture discipline (proposal section 4.4): both component snapshots
are captured before the fixture's kickoff and the gate decision is
made before kickoff; receipts are append-only and never backfilled;
a bundle binds to exactly one fixture (team + kickoff) -- a bundle
captured at/after kickoff, or issued for another fixture, is invalid.
The chart's update stamp must postdate the kickoff of the team's most
recent completed game (the previous-game bound; the stamp is a
publisher batch stamp, so a stamp that predates that game is
disqualifying even on the publisher's own account, while a fresh
stamp is necessary, never sufficient).

This module never fetches during evaluation: the pre-pricing stage
consumes bundles produced ahead of time by the capture helper
(``build_form2_bundle`` / the module CLI). No autonomous scraping is
wired into the runner.

Owner-review corrections (Oct 13, 2026; the four findings posted on
PR #2157):

  1. EXACT FIXTURE BINDING. A bundle must bind to the staged fixture
     exactly: ESPN event ID plus BOTH team ESPN IDs. The evaluator
     requires the bundle's event ID to equal the staged event's, and
     the bundle's opponent to be exactly the staged fixture's other
     team. A bundle for the right team in the wrong game is not
     evidence (QB_EVIDENCE_FIXTURE_MISMATCH).
  2. QB1 RANKING IS DERIVED, NEVER ASSERTED. The evaluator parses the
     QB ordering out of the captured chart content itself (the same
     parser the capture path uses). A bundle-carried ``qb_order`` is
     an assertion that is cross-checked against the parsed ordering;
     a disagreement fails closed
     (QB_EVIDENCE_QB1_ASSERTION_MISMATCH). The parsed QB1 is the only
     QB1 ever resolved.
  3. RECEIPT v2. The capture helper seals each bundle with a chained
     receipt hash over both component content hashes, both source
     URLs, the verbatim update stamp, both capture timestamps, the
     event ID and both team IDs. The evaluator recomputes the chain
     over the bundle's recorded fields and rejects any inconsistency
     (QB_EVIDENCE_RECEIPT_HASH_MISMATCH): no receipt field can be
     edited after capture without breaking the seal. Trust boundary,
     stated honestly: the chain proves the bundle was not edited
     after capture and binds the recorded time to the recorded
     content; the wall-clock truth of the capture itself rests on
     the capture operator (this system's own RUN IT capture step),
     anchored by the external audit trail -- the chain does not, and
     cannot, prove a clock honest.
  4. RESEARCH-ONLY ROUTE. A row priced on Form 2 evidence carries
     AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT as its
     availability_status, and the classification layer
     (sportsedge.pricing_provenance.apply_play_gate) forces any such
     row to research-only output regardless of EV or status. See
     issue #2158.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from artifacts.free_models import dt

EVIDENCE_CLASS = "QB_IDENTITY_EVIDENCE"
EVIDENCE_FORM = "DEPTH_ROSTER_COMPOSITE"

# Outcome statuses -- proposal section 4.5, verbatim.
STATUS_SATISFIED = "QB_IDENTITY_SATISFIED_FORM2_DEPTH_ROSTER_COMPOSITE"
STATUS_MISSING = "QB_DEPTH_EVIDENCE_MISSING"
STATUS_STALE = "QB_DEPTH_EVIDENCE_STALE"
STATUS_AMBIGUOUS = "QB_DEPTH_QB1_RESOLUTION_AMBIGUOUS"
STATUS_NOT_ON_ROSTER = "QB_DEPTH_QB1_NOT_ON_ROSTER"
STATUS_ROSTER_INCOMPLETE = "QB_ROSTER_SNAPSHOT_INCOMPLETE"
AVAILABILITY_UNVERIFIED = "AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"
BLOCK_QB_AVAILABILITY_UNVERIFIED = "BLOCKED_PREPRICING_QB_AVAILABILITY_UNVERIFIED"

# Failure modes the proposal requires to fail closed but does not name;
# coined here in the same style (recorded in the build report).
STATUS_POSITION_MISMATCH = "QB_DEPTH_QB1_POSITION_MISMATCH"
STATUS_HASH_MISMATCH = "QB_EVIDENCE_RECEIPT_HASH_MISMATCH"

# Owner-review corrections (PR #2157 findings): exact fixture binding
# and the derived-vs-asserted QB1 rule. Coined in the same style.
STATUS_FIXTURE_MISMATCH = "QB_EVIDENCE_FIXTURE_MISMATCH"
STATUS_QB1_ASSERTION_MISMATCH = "QB_EVIDENCE_QB1_ASSERTION_MISMATCH"

# Receipt v2: the capture helper seals every bundle it emits with a
# chained hash (see receipt_chain_sha256). A bundle without a valid
# v2 seal is not evidence, however consistent its components look.
RECEIPT_VERSION = 2

# ---------------------------------------------------------------------------
# OWNER DISPOSITION SWITCH -- the one place the Form 2 disposition lives.
#
# Ruling (issue #2154): Form 2 is an identity-only, RESEARCH-STAGE
# evidence path. Under the ruling as implemented, a team whose identity
# limb is satisfied by Form 2 PROCEEDS to pricing as research, with
# AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT carried on the record.
# Flipping this single constant to False restores continued blocking
# for such teams, under BLOCKED_PREPRICING_QB_AVAILABILITY_UNVERIFIED
# (identity verified; availability unverifiable) -- nothing else in
# the binder changes.
# ---------------------------------------------------------------------------
FORM2_PROCEEDS_WITH_AVAILABILITY_LABEL = True


def form2_disposition():
    """Return (proceeds, status) for a Form-2-satisfied team."""
    if FORM2_PROCEEDS_WITH_AVAILABILITY_LABEL:
        return True, AVAILABILITY_UNVERIFIED
    return False, BLOCK_QB_AVAILABILITY_UNVERIFIED


ROSTER_URL_TEMPLATE = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/teams/{team_id}/roster?limit=1000")
ROSTER_REQUIRED_LIMIT = 1000

_EASTERN = ZoneInfo("America/New_York")
_STAMP_RE = re.compile(
    r"Updated:\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)\s*ET")
_QB_ROW_ENTRY_RE = re.compile(
    r"(\d+)\.\s+([A-Z][A-Za-z.'-]+(?:\s+(?:Jr|Sr|II|III|IV)\.)?,\s*[^—,·\n]+?)"
    r"\s+—[^#·\n]*#(\d{1,2})")
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def sha256_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _chain_value(value):
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _subdict(mapping, key):
    """A bundle sub-object read as an object: the value when it is a
    dict, else an empty dict. Parsed JSON of the wrong type (a list,
    a string, a number where an object belongs) must reach the named
    binding/chain failures, never crash on ``.get`` -- the fail-closed
    vocabulary only works if the boundary is total over input types.
    """
    if not isinstance(mapping, dict):
        return {}
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def receipt_chain_fields(bundle):
    """The exact field set the receipt v2 chain seals (owner-review
    correction 3): both component content hashes, both source URLs,
    the chart's verbatim update stamp, both capture timestamps, the
    fixture's event ID and BOTH team IDs (subject + opponent). Read
    from the bundle's recorded fields only, so the capture helper and
    the evaluator compute over identical inputs by construction."""
    if not isinstance(bundle, dict):
        bundle = {}
    team = _subdict(bundle, "team")
    fixture = _subdict(bundle, "fixture")
    depth = _subdict(bundle, "depth_snapshot")
    roster_snap = _subdict(bundle, "roster_snapshot")
    return {
        "evidence_class": bundle.get("evidence_class"),
        "evidence_form": bundle.get("evidence_form"),
        "team_id": _chain_value(team.get("espn_id")),
        "opponent_id": _chain_value(fixture.get("opponent_espn_id")),
        "event_id": _chain_value(fixture.get("event_id")),
        "fixture_kickoff_utc": fixture.get("kickoff_utc"),
        "previous_game_kickoff_utc": _subdict(bundle, "previous_game").get("kickoff_utc"),
        "depth_qb_order": depth.get("qb_order"),
        "roster_requested_limit": roster_snap.get("requested_limit"),
        "roster_athlete_count": roster_snap.get("athlete_count"),
        "roster_athlete_count_repeat": roster_snap.get("athlete_count_repeat"),
        "depth_sha256": depth.get("sha256"),
        "depth_source_url": depth.get("source_url"),
        "depth_update_stamp": depth.get("update_stamp"),
        "depth_captured_at_utc": depth.get("captured_at_utc"),
        "roster_sha256": roster_snap.get("sha256"),
        "roster_source_url": roster_snap.get("source_url"),
        "roster_captured_at_utc": roster_snap.get("captured_at_utc"),
    }


def receipt_chain_sha256(bundle):
    """Chained receipt hash: sha256 over the canonical JSON of
    receipt_chain_fields. Editing ANY sealed field after capture --
    a timestamp, a URL, the stamp, either binding ID -- breaks the
    chain even when the component contents themselves are untouched."""
    canonical = json.dumps(receipt_chain_fields(bundle),
                           sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def parse_update_stamp(text):
    """Extract the verbatim OurLads update stamp and its ET datetime.

    Returns (verbatim, aware datetime in UTC) or (None, None). The
    stamp is publisher-asserted (a batch-publication stamp, per the
    proposal's honest limits) -- it is recorded verbatim and used only
    for the disqualifying direction of the staleness test.
    """
    match = _STAMP_RE.search(str(text or ""))
    if not match:
        return None, None
    verbatim = "Updated: " + match.group(1) + " ET"
    raw = re.sub(r"\s*([AP]M)$", r" \1", match.group(1).strip())
    try:
        naive = datetime.strptime(raw, "%m/%d/%Y %I:%M %p")
    except ValueError:
        return verbatim, None
    return verbatim, naive.replace(tzinfo=_EASTERN).astimezone(timezone.utc)


def parse_qb_order(text):
    """Parse the QB ordering (QB1 first) from captured chart text.

    Recognizes the numbered ``N. Last, First -- CLASS, #N`` entry
    format the source publishes (and that the archived verification
    summaries record verbatim). Returns a list of
    {"rank", "name", "jersey"} in chart order; empty when no ordering
    can be read -- the caller fails closed, never guesses.
    """
    entries = []
    for rank, name, jersey in _QB_ROW_ENTRY_RE.findall(str(text or "")):
        entries.append({"rank": int(rank), "name": " ".join(name.split()),
                        "jersey": str(int(jersey))})
    entries.sort(key=lambda e: e["rank"])
    # A clipped QB1, duplicate rank or missing rank is NOT a valid depth
    # ordering. Otherwise an unverified QB2 could be promoted to QB1.
    ranks = [entry["rank"] for entry in entries]
    if ranks != list(range(1, len(entries) + 1)):
        return []
    return entries


def _name_tokens(name):
    """Canonical name key: 'Minicucci, Nick' == 'Nick Minicucci'."""
    text = str(name or "")
    if "," in text:
        last, _, first = text.partition(",")
        text = f"{first} {last}"
    tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower())
              if t not in _NAME_SUFFIXES]
    return tuple(sorted(tokens))


def _jersey_key(jersey):
    digits = re.sub(r"\D", "", str(jersey or ""))
    return str(int(digits)) if digits else ""


# ---------------------------------------------------------------------------
# Capture-side HTML normalization (fix/form2-capture-html-table-20261013).
#
# The live OurLads chart page publishes the depth chart as an HTML
# table; the archived verification summaries record the SAME chart in
# the numbered text serialization ``parse_qb_order`` seals. The
# capture helper's own fetch now returns the HTML shape, which the
# numbered parser cannot read -- the Oct 13 FIU/JSU captures failed
# closed with NO_QB_ORDER_CAPTURED on pages that were fetched fine.
#
# ``normalize_ourlads_depth_html`` converts the fetched page's QB
# table into the exact numbered serialization, inside the capture
# path, from the helper's OWN fetched bytes (provenance unchanged:
# same fetch, same source URL; the sealed content is the canonical
# serialization of what the page publishes, with the page's verbatim
# update stamp as its first line). The order comes STRICTLY from the
# published table: the QB row's (jersey, name) cell pairs in printed
# order, QB1 first. Nothing is inferred, reordered, or completed.
#
# Fail-closed refusals (ValueError, module vocabulary; the
# CAPTURE_-prefixed details are coined here in the same style -- the
# proposal names no code for a malformed published table because the
# capture path was written against the text serialization):
#   * no readable update stamp      -> STALE:UPDATE_STAMP_UNPARSEABLE
#   * no QB row on the page         -> MISSING:NO_QB_ORDER_CAPTURED
#   * more than one QB row          -> MISSING:CAPTURE_MULTIPLE_QB_ROWS
#   * odd cell count, or a filled   -> MISSING:CAPTURE_QB_ROW_UNPARSEABLE
#     pair after an empty pair
#   * a name cell that does not     -> MISSING:CAPTURE_QB_NAME_UNPARSEABLE
#     read as "Last, First [CLASS]"
#   * a jersey cell that is not     -> MISSING:CAPTURE_QB_JERSEY_UNPARSEABLE
#     1-2 digits
#   * the same name twice in the    -> MISSING:CAPTURE_DUPLICATE_QB_NAME
#     published order
# The emitted serialization is round-tripped through parse_qb_order
# before it is returned: a serialization the sealing parser would
# read differently from the published table is refused, never sealed.
# ---------------------------------------------------------------------------
_QB_CLASS_TOKENS = {"FR", "SO", "JR", "SR", "GR", "RS"}
_SERIALIZED_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z.'-]*")


class _TableRowCollector(HTMLParser):
    """Collect table rows as lists of whitespace-collapsed cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _split_qb_name_cell(text):
    """Split a published QB name cell ("Kohl, JJ RS JR/TR") into the
    serialization's (name, class) parts: ("Kohl, JJ", "RS JR/TR").

    The class segment is the trailing run of class tokens (FR/SO/JR/
    SR/GR, optionally RS-prefixed, optionally /TR-suffixed); everything
    before it is the player's given name. A cell that cannot be split
    this way -- no comma, no given name, a name token outside the
    charset the sealing parser accepts -- is unparseable, not
    repairable."""
    if "," not in text:
        raise ValueError(STATUS_MISSING + ":CAPTURE_QB_NAME_UNPARSEABLE")
    last, _, rest = str(text).partition(",")
    last = " ".join(last.split())
    tokens = rest.split()
    if not last or not tokens:
        raise ValueError(STATUS_MISSING + ":CAPTURE_QB_NAME_UNPARSEABLE")
    class_start = None
    for index, token in enumerate(tokens):
        if index >= 1 and token.split("/")[0].upper() in _QB_CLASS_TOKENS:
            class_start = index
            break
    if class_start is None:
        first_tokens, class_tokens = tokens, []
    else:
        first_tokens, class_tokens = tokens[:class_start], tokens[class_start:]
    first = " ".join(first_tokens)
    for token in [last] + first_tokens:
        if not _SERIALIZED_NAME_TOKEN_RE.fullmatch(token):
            raise ValueError(STATUS_MISSING + ":CAPTURE_QB_NAME_UNPARSEABLE")
    if not last[0].isupper():
        raise ValueError(STATUS_MISSING + ":CAPTURE_QB_NAME_UNPARSEABLE")
    return f"{last}, {first}", " ".join(class_tokens)


def normalize_ourlads_depth_html(html_text):
    """Canonical numbered serialization of a live OurLads chart page.

    Returns the verbatim update-stamp line followed by one
    ``N. Last, First -- CLASS #N`` line per published QB, in published
    order -- the exact format parse_qb_order seals. Raises ValueError
    with a named detail on every shape the contract does not admit
    (see the block comment above); an empty ordering can never be
    returned."""
    text = str(html_text or "")
    _verbatim, stamp_dt = parse_update_stamp(text)
    if stamp_dt is None:
        raise ValueError(STATUS_STALE + ":UPDATE_STAMP_UNPARSEABLE")
    stamp_line = _STAMP_RE.search(text).group(0)
    collector = _TableRowCollector()
    try:
        collector.feed(text)
        collector.close()
    except Exception as exc:
        raise ValueError(STATUS_MISSING + ":CAPTURE_QB_ROW_UNPARSEABLE") from exc
    qb_rows = [row for row in collector.rows if row and row[0] == "QB"]
    if not qb_rows:
        raise ValueError(STATUS_MISSING + ":NO_QB_ORDER_CAPTURED")
    if len(qb_rows) > 1:
        raise ValueError(STATUS_MISSING + ":CAPTURE_MULTIPLE_QB_ROWS")
    cells = qb_rows[0][1:]
    if len(cells) % 2:
        raise ValueError(STATUS_MISSING + ":CAPTURE_QB_ROW_UNPARSEABLE")
    entries = []
    seen_names = set()
    seen_empty_pair = False
    for index in range(0, len(cells), 2):
        jersey_text, name_text = cells[index], cells[index + 1]
        if not jersey_text and not name_text:
            seen_empty_pair = True
            continue
        if seen_empty_pair:
            # A filled pair after an empty one is a hole in the
            # published order; the ranks between are unknowable.
            raise ValueError(STATUS_MISSING + ":CAPTURE_QB_ROW_UNPARSEABLE")
        if not name_text:
            raise ValueError(STATUS_MISSING + ":CAPTURE_QB_NAME_UNPARSEABLE")
        if not re.fullmatch(r"\d{1,2}", jersey_text or ""):
            raise ValueError(STATUS_MISSING + ":CAPTURE_QB_JERSEY_UNPARSEABLE")
        name, class_text = _split_qb_name_cell(name_text)
        name_key = _name_tokens(name)
        if name_key in seen_names:
            raise ValueError(STATUS_MISSING + ":CAPTURE_DUPLICATE_QB_NAME")
        seen_names.add(name_key)
        entries.append({"name": name, "class": class_text,
                        "jersey": str(int(jersey_text))})
    if not entries:
        raise ValueError(STATUS_MISSING + ":NO_QB_ORDER_CAPTURED")
    lines = [stamp_line]
    for rank, entry in enumerate(entries, start=1):
        if entry["class"]:
            lines.append(f"{rank}. {entry['name']} — {entry['class']} "
                         f"#{entry['jersey']}")
        else:
            lines.append(f"{rank}. {entry['name']} — #{entry['jersey']}")
    serialization = "\n".join(lines)
    parsed = parse_qb_order(serialization)
    if (len(parsed) != len(entries)
            or any(_name_tokens(p["name"]) != _name_tokens(e["name"])
                   or p["jersey"] != e["jersey"]
                   for p, e in zip(parsed, entries))):
        raise ValueError(STATUS_MISSING + ":CAPTURE_QB_ROW_UNPARSEABLE")
    return serialization


def roster_athletes(roster_obj):
    """Flatten an ESPN roster payload into its athlete records."""
    if isinstance(roster_obj, list):
        return [a for a in roster_obj if isinstance(a, dict)]
    if not isinstance(roster_obj, dict):
        return []
    athletes = []
    groups = roster_obj.get("athletes")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            items = group.get("items")
            if isinstance(items, list):
                athletes.extend(a for a in items if isinstance(a, dict))
            elif group.get("id") is not None:
                athletes.append(group)  # flat athlete record, not a group
    return athletes


def _qb1_in_content(qb1, content):
    """Integrity tie between the recorded QB1 and the captured bytes:
    the QB1's name must literally appear in the hashed chart content
    (either 'Last, First' chart order or 'First Last')."""
    name = " ".join(str(qb1.get("name") or "").split())
    if not name:
        return False
    haystack = " ".join(str(content or "").split())
    if name in haystack:
        return True
    if "," in name:
        last, _, first = name.partition(",")
        return f"{first.strip()} {last.strip()}" in haystack
    return False


def _position_abbr(athlete):
    pos = athlete.get("position")
    if isinstance(pos, dict):
        return str(pos.get("abbreviation") or "").upper()
    return str(pos or "").upper()


def check_roster_completeness(snapshot, athletes):
    """The asserted-complete-limit + count-stability assertion.

    Proposal section 4.2 / design section 2.2: a roster consumer must
    pull at an explicit high limit and assert count stability, or the
    default pull's silent 100-athlete cap drops real players and the
    binding surface cannot be trusted. Returns (ok, detail).
    """
    try:
        limit = int(snapshot.get("requested_limit"))
    except (TypeError, ValueError):
        return False, "ROSTER_LIMIT_UNRECORDED"
    if limit < ROSTER_REQUIRED_LIMIT:
        return False, f"ROSTER_LIMIT_{limit}_BELOW_ASSERTED_COMPLETE_{ROSTER_REQUIRED_LIMIT}"
    try:
        attested = int(snapshot.get("athlete_count"))
        repeat = int(snapshot.get("athlete_count_repeat"))
    except (TypeError, ValueError):
        return False, "ROSTER_COUNT_ATTESTATION_MISSING"
    if attested != repeat:
        return False, f"ROSTER_COUNT_UNSTABLE:{attested}_VS_{repeat}"
    if attested >= limit:
        return False, f"ROSTER_COUNT_{attested}_AT_LIMIT_{limit}_POSSIBLE_TRUNCATION"
    if len(athletes) != attested:
        return False, f"ROSTER_COUNT_CONTENT_MISMATCH:{len(athletes)}_VS_{attested}"
    ids = [str(a.get("id")) for a in athletes if a.get("id") is not None]
    if len(ids) != len(set(ids)) or len(ids) != len(athletes):
        return False, "ROSTER_ATHLETE_IDS_NOT_UNIQUE"
    return True, "ROSTER_COMPLETE_ASSERTED"


def resolve_qb1(qb1, athletes):
    """Resolve the chart's QB1 (name + jersey) on ONE team's roster.

    Exactly one joint name+jersey match, at position QB, is a
    resolution. Returns (status, athlete, detail); status is
    STATUS_SATISFIED on success.
    """
    if not qb1:
        return STATUS_MISSING, None, "NO_QB1_IN_CAPTURED_ORDER"
    wanted_name = _name_tokens(qb1.get("name"))
    wanted_jersey = _jersey_key(qb1.get("jersey"))
    if not wanted_name or not wanted_jersey:
        return STATUS_MISSING, None, "QB1_NAME_OR_JERSEY_UNREADABLE"
    matches = [a for a in athletes
               if _name_tokens(a.get("displayName") or a.get("fullName"))
               == wanted_name
               and _jersey_key(a.get("jersey")) == wanted_jersey]
    if not matches:
        name_only = [a for a in athletes
                     if _name_tokens(a.get("displayName") or a.get("fullName"))
                     == wanted_name]
        detail = ("NAME_MATCHES_WITH_DIFFERENT_JERSEY" if name_only
                  else "NO_NAME_MATCH_ON_ROSTER")
        return STATUS_NOT_ON_ROSTER, None, detail
    if len(matches) > 1:
        return (STATUS_AMBIGUOUS, None,
                f"{len(matches)}_ATHLETES_MATCH_QB1_NAME_AND_JERSEY")
    athlete = matches[0]
    if _position_abbr(athlete) != "QB":
        return (STATUS_POSITION_MISMATCH, None,
                f"RESOLVED_ATHLETE_POSITION_{_position_abbr(athlete) or 'UNKNOWN'}")
    return STATUS_SATISFIED, athlete, "UNIQUE_QB_RESOLUTION"


def _fail(status, detail, receipt=None):
    return {"ok": False, "status": status, "detail": detail,
            "resolved_athlete_id": None, "resolved_athlete_name": None,
            "availability_status": None, "injury_points": 0.0,
            "receipt": receipt}


def evaluate_form2_bundle(bundle, *, team_id, kickoff, previous_game_kickoff=None,
                          now=None, event_id=None, home_team_id=None,
                          away_team_id=None):
    """Verify one Form 2 bundle for one fixture team. Fail-closed.

    ``kickoff`` is the fixture's kickoff (aware datetime). ``now`` is
    the stage clock. ``previous_game_kickoff`` is the kickoff of the
    team's most recent completed game when the caller can derive it
    (the stage passes the provider-schedule value); the bundle's own
    attestation is the fallback, and a disagreement between the two
    fails closed.

    ``event_id`` / ``home_team_id`` / ``away_team_id`` are the STAGED
    fixture's identity (owner-review correction 1): the bundle must
    name this exact event and this exact opponent. When the caller
    cannot supply the staged identity, exact binding cannot be
    established and the bundle fails closed -- loose binding is the
    defect being corrected, not a fallback. Returns a result dict;
    on success it carries the receipt and the AVAILABILITY_UNVERIFIED
    label -- never an availability claim.
    """
    team_id = str(team_id)
    if not isinstance(bundle, dict):
        return _fail(STATUS_MISSING, "BUNDLE_ABSENT")
    if (bundle.get("evidence_class") != EVIDENCE_CLASS
            or bundle.get("evidence_form") != EVIDENCE_FORM):
        return _fail(STATUS_MISSING, "WRONG_EVIDENCE_FORM")
    team = _subdict(bundle, "team")
    if str(team.get("espn_id")) != team_id:
        return _fail(STATUS_MISSING, "TEAM_BINDING_MISMATCH")

    # -- Exact fixture binding (correction 1): event + opponent + sides.
    fixture = _subdict(bundle, "fixture")
    if event_id is None or home_team_id is None or away_team_id is None:
        return _fail(STATUS_FIXTURE_MISMATCH, "FIXTURE_IDENTITY_UNVERIFIABLE")
    home_team_id, away_team_id = str(home_team_id), str(away_team_id)
    if team_id not in (home_team_id, away_team_id):
        return _fail(STATUS_FIXTURE_MISMATCH, "TEAM_NOT_IN_STAGED_FIXTURE")
    if str(fixture.get("event_id")) != str(event_id):
        return _fail(STATUS_FIXTURE_MISMATCH, "EVENT_ID_MISMATCH")
    expected_opponent = away_team_id if team_id == home_team_id else home_team_id
    if str(fixture.get("opponent_espn_id")) != expected_opponent:
        return _fail(STATUS_FIXTURE_MISMATCH, "OPPONENT_MISMATCH")
    if dt(fixture.get("kickoff_utc")) != kickoff:
        return _fail(STATUS_FIXTURE_MISMATCH, "FIXTURE_KICKOFF_MISMATCH")
    depth = bundle.get("depth_snapshot")
    roster_snap = bundle.get("roster_snapshot")
    if not isinstance(depth, dict) or not isinstance(roster_snap, dict):
        return _fail(STATUS_MISSING, "COMPONENT_SNAPSHOT_MISSING")

    receipt = {
        "evidence_class": EVIDENCE_CLASS, "evidence_form": EVIDENCE_FORM,
        "team_id": team_id,
        "event_id": str(fixture.get("event_id")),
        "opponent_espn_id": str(fixture.get("opponent_espn_id")),
        "receipt_version": RECEIPT_VERSION,
        "receipt_sha256": None,
        "depth_source_url": depth.get("source_url"),
        "depth_update_stamp": depth.get("update_stamp"),
        "depth_captured_at_utc": depth.get("captured_at_utc"),
        "depth_sha256": depth.get("sha256"),
        "roster_source_url": roster_snap.get("source_url"),
        "roster_captured_at_utc": roster_snap.get("captured_at_utc"),
        "roster_sha256": roster_snap.get("sha256"),
        "resolved_qb1_athlete_id": None,
        "availability_status": None,
        "injury_points": 0.0,
    }

    depth_content = depth.get("content")
    roster_content = roster_snap.get("content")
    if not isinstance(depth_content, str) or not isinstance(roster_content, str):
        return _fail(STATUS_MISSING, "COMPONENT_CONTENT_MISSING", receipt)
    if sha256_text(depth_content) != depth.get("sha256"):
        return _fail(STATUS_HASH_MISMATCH, "DEPTH_CONTENT_SHA256_MISMATCH", receipt)
    if sha256_text(roster_content) != roster_snap.get("sha256"):
        return _fail(STATUS_HASH_MISMATCH, "ROSTER_CONTENT_SHA256_MISMATCH", receipt)

    # -- Receipt v2 chain (correction 3): every sealed field recomputed
    # over the bundle as presented. A bundle sealed by an older (or no)
    # receipt format, or edited in any sealed field after capture,
    # fails here even when both component contents are intact.
    sealed = bundle.get("receipt")
    if not isinstance(sealed, dict) or sealed.get("version") != RECEIPT_VERSION:
        return _fail(STATUS_HASH_MISMATCH, "RECEIPT_CHAIN_MISSING", receipt)
    chain = receipt_chain_sha256(bundle)
    if sealed.get("sha256") != chain:
        return _fail(STATUS_HASH_MISMATCH, "RECEIPT_CHAIN_MISMATCH", receipt)
    receipt["receipt_sha256"] = chain

    depth_captured = dt(depth.get("captured_at_utc"))
    roster_captured = dt(roster_snap.get("captured_at_utc"))
    if depth_captured is None or roster_captured is None:
        return _fail(STATUS_STALE, "CAPTURE_TIMESTAMP_UNREADABLE", receipt)
    if depth_captured >= kickoff or roster_captured >= kickoff:
        return _fail(STATUS_STALE, "CAPTURE_AT_OR_AFTER_KICKOFF", receipt)
    if now is not None and (depth_captured > now or roster_captured > now):
        return _fail(STATUS_STALE, "CAPTURE_IN_FUTURE", receipt)

    stamp_verbatim, stamp_dt = parse_update_stamp(
        depth.get("update_stamp") or depth_content)
    if stamp_dt is None:
        return _fail(STATUS_STALE, "UPDATE_STAMP_UNPARSEABLE", receipt)
    receipt["depth_update_stamp"] = stamp_verbatim
    if stamp_dt > depth_captured:
        # The captured bytes cannot contain an update stamped after
        # the capture that recorded them: the recorded stamp and the
        # recorded capture time contradict each other.
        return _fail(STATUS_STALE, "STAMP_AFTER_DEPTH_CAPTURE", receipt)

    attested_prev = dt(_subdict(bundle, "previous_game").get("kickoff_utc"))
    prev = previous_game_kickoff or attested_prev
    if (previous_game_kickoff is not None and attested_prev is not None
            and abs((previous_game_kickoff - attested_prev).total_seconds()) > 120):
        return _fail(STATUS_STALE, "PREVIOUS_GAME_ATTESTATION_MISMATCH", receipt)
    if prev is None:
        return _fail(STATUS_STALE, "PREVIOUS_GAME_BOUND_UNVERIFIABLE", receipt)
    if stamp_dt <= prev:
        return _fail(STATUS_STALE, "STAMP_PREDATES_PREVIOUS_GAME_KICKOFF", receipt)

    try:
        roster_obj = json.loads(roster_content)
    except ValueError:
        return _fail(STATUS_ROSTER_INCOMPLETE, "ROSTER_CONTENT_UNPARSEABLE", receipt)
    athletes = roster_athletes(roster_obj)
    complete, detail = check_roster_completeness(roster_snap, athletes)
    if not complete:
        return _fail(STATUS_ROSTER_INCOMPLETE, detail, receipt)

    # -- QB ordering is DERIVED from the captured bytes (correction 2).
    # The same parser the capture path uses reads the ordering out of
    # the hashed content; a bundle-carried qb_order is an assertion to
    # be cross-checked, never an input to resolution. A bundle whose
    # content cannot be parsed into an ordering fails closed here --
    # there is no asserted fallback to guess from.
    order = parse_qb_order(depth_content)
    if not order:
        return _fail(STATUS_MISSING, "NO_QB_ORDER_CAPTURED", receipt)
    qb1 = order[0]
    asserted = depth.get("qb_order")
    if asserted is not None:
        if not isinstance(asserted, list) or len(asserted) != len(order):
            return _fail(STATUS_QB1_ASSERTION_MISMATCH,
                         "ASSERTED_QB_ORDER_LENGTH_OR_SHAPE_MISMATCH", receipt)
        for claimed, actual in zip(asserted, order):
            if (not isinstance(claimed, dict)
                    or claimed.get("rank") != actual["rank"]
                    or _name_tokens(claimed.get("name")) != _name_tokens(actual["name"])
                    or _jersey_key(claimed.get("jersey")) != actual["jersey"]):
                return _fail(STATUS_QB1_ASSERTION_MISMATCH,
                             "ASSERTED_QB_ORDER_DIFFERS_FROM_CAPTURED_CHART", receipt)
    if not _qb1_in_content(qb1, depth_content):
        return _fail(STATUS_MISSING, "QB1_NOT_IN_CAPTURED_CONTENT", receipt)

    status, athlete, detail = resolve_qb1(qb1, athletes)
    if status != STATUS_SATISFIED:
        return _fail(status, detail, receipt)
    receipt["resolved_qb1_athlete_id"] = str(athlete.get("id"))
    receipt["resolved_qb1_name"] = athlete.get("displayName")
    receipt["resolved_qb1_jersey"] = _jersey_key(athlete.get("jersey"))
    receipt["availability_status"] = AVAILABILITY_UNVERIFIED
    return {"ok": True, "status": STATUS_SATISFIED, "detail": detail,
            "resolved_athlete_id": str(athlete.get("id")),
            "resolved_athlete_name": athlete.get("displayName"),
            "availability_status": AVAILABILITY_UNVERIFIED,
            "injury_points": 0.0, "receipt": receipt}


# ---------------------------------------------------------------------------
# Capture helper -- produces a Form 2 bundle. Used at RUN IT time,
# pre-kickoff, by an operator/runner step; the pre-pricing stage only
# ever CONSUMES bundles. Refuses to emit a bundle it cannot verify.
# ---------------------------------------------------------------------------
def build_form2_bundle(*, team_id, team_name, event_id, opponent_id,
                       kickoff_utc, previous_game_kickoff_utc,
                       depth_url, depth_content, depth_captured_at_utc,
                       roster_content, roster_captured_at_utc,
                       roster_athlete_count_repeat, roster_url=None,
                       roster_requested_limit=ROSTER_REQUIRED_LIMIT):
    """Assemble a bundle dict from captured component contents.

    ``depth_content`` / ``roster_content`` are the captured texts
    (roster may be a parsed JSON object, serialized canonically).
    Raises ValueError with a named status when the capture cannot
    support a bundle (no readable stamp/order, incomplete roster) --
    capture-time failure is fail-closed, exactly like gate-time.
    """
    if not isinstance(roster_content, str):
        roster_content = json.dumps(roster_content, sort_keys=True)
    stamp_verbatim, stamp_dt = parse_update_stamp(depth_content)
    if stamp_dt is None:
        raise ValueError(STATUS_STALE + ":UPDATE_STAMP_UNPARSEABLE")
    order = parse_qb_order(depth_content)
    if not order:
        raise ValueError(STATUS_MISSING + ":NO_QB_ORDER_CAPTURED")
    try:
        roster_obj = json.loads(roster_content)
    except ValueError as exc:
        raise ValueError(STATUS_ROSTER_INCOMPLETE + ":ROSTER_CONTENT_UNPARSEABLE") from exc
    athletes = roster_athletes(roster_obj)
    roster_snap = {
        "source_url": roster_url or ROSTER_URL_TEMPLATE.format(team_id=team_id),
        "captured_at_utc": roster_captured_at_utc,
        "sha256": sha256_text(roster_content),
        "content": roster_content,
        "requested_limit": roster_requested_limit,
        "athlete_count": len(athletes),
        "athlete_count_repeat": roster_athlete_count_repeat,
    }
    complete, detail = check_roster_completeness(roster_snap, athletes)
    if not complete:
        raise ValueError(STATUS_ROSTER_INCOMPLETE + ":" + detail)
    bundle = {
        "evidence_class": EVIDENCE_CLASS,
        "evidence_form": EVIDENCE_FORM,
        "sport": "CFB",
        "team": {"espn_id": str(team_id), "name": team_name},
        "fixture": {"event_id": str(event_id), "opponent_espn_id": str(opponent_id),
                    "kickoff_utc": kickoff_utc},
        "previous_game": {"kickoff_utc": previous_game_kickoff_utc},
        "depth_snapshot": {
            "source_url": depth_url,
            "update_stamp": stamp_verbatim,
            "captured_at_utc": depth_captured_at_utc,
            "sha256": sha256_text(depth_content),
            "content": depth_content,
            "qb_order": order,
        },
        "roster_snapshot": roster_snap,
    }
    # Receipt v2 seal (correction 3): computed LAST, over the finished
    # bundle's recorded fields, so any later edit to a sealed field --
    # either binding ID, either timestamp, the stamp, either URL,
    # either content hash -- breaks the chain at evaluation.
    bundle["receipt"] = {"version": RECEIPT_VERSION,
                         "sha256": receipt_chain_sha256(bundle)}
    return bundle


def _fetch_text(url):
    req = Request(url, headers={"User-Agent": "SportsEdge-free-context/1.0"})
    with urlopen(req, timeout=15) as response:
        return response.read().decode("utf-8", "replace")


def capture_form2_bundle(*, team_id, team_name, event_id, opponent_id,
                         kickoff_utc, previous_game_kickoff_utc, depth_url,
                         now=None, fetch_text=None, fetch_json=None, clock=None):
    """Capture chart and roster with completion-time receipts.

    Each timestamp is taken AFTER its fetch (after both roster polls for
    the count-stability assertion), not before network I/O. An optional
    injectable clock exists ONLY for deterministic offline tests; the
    production default is the current UTC clock. The legacy 'now' input
    never substitutes for an observation timestamp.
    """
    fetch_text = fetch_text or _fetch_text
    fetch_json = fetch_json or (lambda url: json.loads(_fetch_text(url)))
    capture_clock = clock or (lambda: datetime.now(timezone.utc))

    def completed_at_utc():
        recorded = capture_clock()
        if (not isinstance(recorded, datetime) or recorded.tzinfo is None
                or recorded.utcoffset() is None):
            raise ValueError(STATUS_STALE + ":CAPTURE_CLOCK_UNVERIFIED")
        return recorded.astimezone(timezone.utc).isoformat()

    depth_content = fetch_text(depth_url)
    if not parse_qb_order(depth_content):
        # The live page publishes the chart as an HTML table, not the
        # numbered serialization. Normalize the helper's OWN fetched
        # bytes into that serialization (fail-closed: a page with no
        # readable QB table, an ambiguous one, or no readable stamp
        # raises the named refusal here, before any timestamp is taken
        # -- no bundle is emitted for it, exactly as when the numbered
        # parser found no order downstream).
        depth_content = normalize_ourlads_depth_html(depth_content)
    depth_completed = completed_at_utc()
    roster_url = ROSTER_URL_TEMPLATE.format(team_id=team_id)
    roster_first = fetch_json(roster_url)
    roster_second = fetch_json(roster_url)
    roster_completed = completed_at_utc()
    if dt(roster_completed) < dt(depth_completed):
        raise ValueError(STATUS_STALE + ":CAPTURE_CLOCK_NONMONOTONIC")
    start = dt(kickoff_utc)
    if start is None or dt(depth_completed) >= start or dt(roster_completed) >= start:
        raise ValueError(STATUS_STALE + ":CAPTURE_AT_OR_AFTER_KICKOFF")
    count_second = len(roster_athletes(roster_second))
    return build_form2_bundle(
        team_id=team_id, team_name=team_name, event_id=event_id,
        opponent_id=opponent_id, kickoff_utc=kickoff_utc,
        previous_game_kickoff_utc=previous_game_kickoff_utc,
        depth_url=depth_url, depth_content=depth_content,
        depth_captured_at_utc=depth_completed,
        roster_content=json.dumps(roster_first, sort_keys=True),
        roster_captured_at_utc=roster_completed,
        roster_athlete_count_repeat=count_second, roster_url=roster_url)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Capture a QB_IDENTITY_EVIDENCE Form 2 bundle "
                    "(DEPTH_ROSTER_COMPOSITE) for one CFB fixture team.")
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--team-name", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--opponent-id", required=True)
    parser.add_argument("--kickoff", required=True,
                        help="fixture kickoff, ISO UTC (e.g. 2026-10-13T23:00:00Z)")
    parser.add_argument("--previous-game-kickoff", required=True,
                        help="kickoff of the team's most recent completed game, ISO UTC")
    parser.add_argument("--ourlads-url", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    bundle = capture_form2_bundle(
        team_id=args.team_id, team_name=args.team_name,
        event_id=args.event_id, opponent_id=args.opponent_id,
        kickoff_utc=args.kickoff,
        previous_game_kickoff_utc=args.previous_game_kickoff,
        depth_url=args.ourlads_url)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, indent=2)
    print(f"WROTE {args.out}: {EVIDENCE_FORM} team {args.team_id} "
          f"QB1 {bundle['depth_snapshot']['qb_order'][0]['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
