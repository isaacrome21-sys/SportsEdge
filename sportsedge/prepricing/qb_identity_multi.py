#!/usr/bin/env python3
"""QB_IDENTITY_EVIDENCE Form 2 MULTI -- MULTI_SOURCE_CORROBORATION (CFB only).

Owner ruling (Isaac, Oct 23, 2026, "Add all"): the QB identity
evidence spec is AMENDED by adding a second, distinctly labeled
evidence path alongside the frozen Form 2 composite. This module
implements that amendment as FORM2_MULTI_V1. The frozen path
(``qb_identity_evidence`` -- OurLads chart + ESPN roster composite,
DEPTH_ROSTER_COMPOSITE) is NOT modified by this module, is never
imported for mutation, and its admissions and archives stand exactly
as before. A team admitted here is admitted under
QB_IDENTITY_SATISFIED_FORM2_MULTI_V1, a different status string
from the frozen path's, so the two populations can never be
conflated downstream.

The owner's source list, as registered in SOURCE_REGISTRY:

  PRIMARY_CHART (one of these must anchor the admission):
    * OurLads            -- also the frozen path's chart source.
    * CFBDepth           -- adapter status UNVERIFIED_LIVE_SHAPE: the
      Oct 23, 2026 probe found cfbdepth.com reachable but no team
      chart page extractable through this environment's fetch (the
      chart product sits behind the site's 2.0 app surface). The
      adapter accepts the numbered serialization / QB-line shapes
      if an operator supplies a captured page; until a live page is
      verified, CFBDepth reads will normally land as
      SOURCE_UNREACHABLE with the parse reason recorded -- never
      faked, never silently dropped.
  CORROBORATOR (independent, non-social, current data):
    * Who's Starting     -- probed Oct 23, 2026: team pages carry a
      verbatim "Updated <Mon D, YYYY>" stamp and an explicit
      "<Name> is the projected starting quarterback" sentence.
    * TheTwoDeep         -- probed Oct 23, 2026: the QB index page
      lists every FBS team's STARTER with a page-level
      "Updated <Mon D>" stamp. The team lookup uses the site's own
      label (e.g. "BYU", not "Brigham Young") -- the raw page and
      its rendered text label teams differently, and the adapter
      matches the raw bytes it captures.
    * 247Sports          -- probed Oct 23, 2026: per-game depth-chart
      articles fetch cleanly and list QB first under "QB" with a
      Published timestamp; the article URL is operator-supplied
      (there is no stable per-team chart URL) and some articles are
      VIP-gated (a gated fetch records SOURCE_UNREACHABLE).
    * ESPN depth charts  -- registered; page shape unverified in the
      probe (the ESPN ROSTER poll already in the frozen path is a
      different surface and is not reused here).
    * Official team athletics sites / conference availability
      reports -- registered; URLs are operator-supplied per team.
  CORROBORATE_ONLY (never sufficient, never necessary):
    * Beat writers / X   -- social. Under program rules social alone
      never confirms; here a social read may be recorded alongside
      an admission but can never serve as the corroborator, and a
      social-only "corroboration" fails closed.

ADMISSION RULE (fail-closed, in evaluate_multi_bundle):

  (a) PRIMARY -- at least one PRIMARY_CHART read whose QB1 is
      derived from its captured content (never merely asserted) and
      whose verbatim stamp parses to an instant POSTDATING the
      team's previous-game kickoff (the same previous-game bound
      as the frozen path; a date-only stamp resolves to 00:00
      America/New_York on that date -- the earliest instant the
      stamp can mean, so the bound is tested conservatively).
  (b) CORROBORATION -- at least one INDEPENDENT read (different
      registry source AND different URL host) from a non-social
      source, itself current (stamp postdates the previous-game
      kickoff), naming the SAME QB1 (canonical name-key equality,
      the frozen path's name grammar).
  CONFLICT -- any two CURRENT reads (fresh primary or current
      corroborator-class) naming different QB1s refuse the bundle
      with QB_IDENTITY_SOURCE_CONFLICT, regardless of how many
      agree. Stale reads neither corroborate nor conflict; they are
      recorded and ignored for both.
  A primary alone, however fresh, refuses QB_MULTI_SINGLE_SOURCE:
  a single source other than the frozen OurLads+ESPN path does not
  admit under this amendment.

Receipt discipline mirrors the frozen path: every source read --
successful or not -- is recorded with its URL, its completion-time
fetched-at instant (taken AFTER the fetch, never before), the
stamp exactly as shown, the QB1 exactly as listed, and the SHA-256
of the captured bytes; failed fetches and unparseable pages record
outcome SOURCE_UNREACHABLE with the named reason. The bundle is
sealed with a chained receipt hash over all recorded read fields
and the fixture binding, computed last; editing any sealed field
after capture breaks the chain (QB_MULTI_RECEIPT_HASH_MISMATCH).

Fixture binding mirrors the frozen owner-review correction: the
bundle must name the staged event ID and the exact opponent; the
caller must supply the staged identity or evaluation fails closed.
Captures at/after the fixture kickoff, or in the future relative
to the stage clock, invalidate the read that carries them.

What this path establishes, and what it never establishes:

  * IDENTITY limb: satisfied on a pass, at multi-source editorial
    strength, recorded as
    QB_IDENTITY_SATISFIED_FORM2_MULTI_V1.
  * AVAILABILITY limb: NOT satisfied. Availability stays
    EXPLICITLY UNKNOWN under
    AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT, and
    ``injury_points`` is exactly 0.0 -- exactly as under Form 2.
  * This module never fetches during evaluation and is NOT wired
    into the runner: the pre-pricing stage consumes only the frozen
    loader's bundles. (The runner's "FORM2_MULTI_PIN" wording is a
    different concept -- multiple external pins for the FROZEN
    loader -- and is unrelated to this evidence path.)

Archive note: the frozen archive writer (qb_evidence_archive)
validates every preserved bundle through the frozen evaluator, so
it REJECTS multi-source bundles on evidence form. Multi bundles
are therefore preserved by this module's own writer -- same
write-once, content-addressed, single-receipt-manifest discipline,
schema CFB_FORM2_MULTI_ARCHIVE_MANIFEST_V1 -- under the operative
multi-evidence root (see DEFAULT_MULTI_EVIDENCE_ROOT). Existing
archives are never touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from artifacts.free_models import dt

from .qb_identity_evidence import (
    AVAILABILITY_UNVERIFIED,
    EVIDENCE_CLASS,
    STATUS_FIXTURE_MISMATCH,
    _name_tokens,
    normalize_ourlads_depth_html,
    parse_qb_order,
    parse_update_stamp,
    sha256_text,
)

EVIDENCE_FORM_MULTI = "MULTI_SOURCE_CORROBORATION"
EVIDENCE_PATH = "FORM2_MULTI_V1"

STATUS_SATISFIED_MULTI = "QB_IDENTITY_SATISFIED_FORM2_MULTI_V1"
STATUS_CONFLICT = "QB_IDENTITY_SOURCE_CONFLICT"
STATUS_MISSING = "QB_MULTI_EVIDENCE_MISSING"
STATUS_PRIMARY_STALE = "QB_MULTI_PRIMARY_STALE"
STATUS_SINGLE_SOURCE = "QB_MULTI_SINGLE_SOURCE"
STATUS_HASH_MISMATCH = "QB_MULTI_RECEIPT_HASH_MISMATCH"

READ_OK = "READ"
READ_UNREACHABLE = "SOURCE_UNREACHABLE"

RECEIPT_VERSION_MULTI = 1

# Mirror of the frozen path's owner disposition switch, for this
# path only: a multi-satisfied team proceeds to pricing as research
# with the AVAILABILITY_UNVERIFIED label carried on the record.
FORM2_MULTI_PROCEEDS_WITH_AVAILABILITY_LABEL = True


def multi_disposition():
    """Return (proceeds, status) for a multi-satisfied team."""
    if FORM2_MULTI_PROCEEDS_WITH_AVAILABILITY_LABEL:
        return True, AVAILABILITY_UNVERIFIED
    return False, "BLOCKED_PREPRICING_QB_AVAILABILITY_UNVERIFIED"


# ---------------------------------------------------------------------------
# Source registry. ``role`` is the admission-rule class; ``social``
# marks sources that can never corroborate; ``adapter_status`` is
# the Oct 23, 2026 probe outcome, stated honestly per source.
# ---------------------------------------------------------------------------
ROLE_PRIMARY = "PRIMARY_CHART"
ROLE_CORROBORATOR = "CORROBORATOR"
ROLE_CORROBORATE_ONLY = "CORROBORATE_ONLY"

SOURCE_REGISTRY = {
    "OURLADS": {
        "role": ROLE_PRIMARY, "social": False, "parser": "ourlads",
        "adapter_status": "VERIFIED_LIVE_SHAPE",
    },
    "CFBDEPTH": {
        "role": ROLE_PRIMARY, "social": False, "parser": "cfbdepth",
        "adapter_status": "UNVERIFIED_LIVE_SHAPE",
    },
    "WHOSSTARTING": {
        "role": ROLE_CORROBORATOR, "social": False, "parser": "whosstarting",
        "adapter_status": "VERIFIED_LIVE_SHAPE",
    },
    "TWODEEP": {
        "role": ROLE_CORROBORATOR, "social": False, "parser": "twodeep",
        "adapter_status": "VERIFIED_LIVE_SHAPE",
    },
    "SPORTS247": {
        "role": ROLE_CORROBORATOR, "social": False, "parser": "sports247",
        "adapter_status": "VERIFIED_LIVE_SHAPE_ARTICLE_URL_OPERATOR_SUPPLIED",
    },
    "ESPN_DEPTH": {
        "role": ROLE_CORROBORATOR, "social": False, "parser": "generic",
        "adapter_status": "UNVERIFIED_LIVE_SHAPE",
    },
    "OFFICIAL_TEAM": {
        "role": ROLE_CORROBORATOR, "social": False, "parser": "generic",
        "adapter_status": "OPERATOR_SUPPLIED_URL",
    },
    "CONFERENCE_AVAILABILITY": {
        "role": ROLE_CORROBORATOR, "social": False, "parser": "generic",
        "adapter_status": "OPERATOR_SUPPLIED_URL",
    },
    "BEAT_SOCIAL": {
        "role": ROLE_CORROBORATE_ONLY, "social": True, "parser": "generic",
        "adapter_status": "OPERATOR_ATTESTED_TEXT_ONLY_NO_FETCH_WIRED",
    },
}

_EASTERN = ZoneInfo("America/New_York")

_NAME = r"[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3}"
_SENTENCE_QB1_RE = re.compile(
    r"(" + _NAME + r")\s+is the (?:projected\s+)?starting quarterback")
_QB_LINE_RE = re.compile(r"\bQB:\s*(" + _NAME + r")")
_WS_STAMP_RE = re.compile(r"Updated\s+([A-Z][a-z]{2,9} \d{1,2}, \d{4})")
_LAST_UPDATED_RE = re.compile(
    r"Last updated:?\s+([A-Z][a-z]{2,9} \d{1,2}, \d{4})", re.IGNORECASE)
_TD_STAMP_RE = re.compile(r"Updated\s+([A-Z][a-z]{2} \d{1,2})\b")
_PUBLISHED_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_247_QB_RE = re.compile(
    r"\bQB\b,?\s*\d{1,2}\s+(" + _NAME + r"),?\s*\d{1,2}\s")
_TD_STARTER_RE = re.compile(r"STARTER\s*#\s*\d+\s*(" + _NAME + r")")


class _TextCollector(HTMLParser):
    """Flatten a page to its text, chunks joined by single spaces."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []

    def handle_data(self, data):
        if data.strip():
            self.chunks.append(" ".join(data.split()))


def _flatten_text(content):
    text = str(content or "")
    if "<" not in text:
        return " ".join(text.split())
    collector = _TextCollector()
    try:
        collector.feed(text)
        collector.close()
    except Exception:
        return " ".join(text.split())
    return " ".join(collector.chunks)


def _date_floor_utc(year, month, day):
    """A date-only stamp's conservative instant: 00:00 ET that date."""
    try:
        naive = datetime(year, month, day)
    except ValueError:
        return None
    return naive.replace(tzinfo=_EASTERN).astimezone(timezone.utc)


def _parse_stamp(text, raw, captured_at):
    """Extract (verbatim, aware UTC datetime or None, precision).

    Tries, in order: the frozen OurLads stamp grammar; a JSON-LD
    datePublished; "Updated <Month D, YYYY>"; "Last updated
    <Month D, YYYY>"; and the TwoDeep yearless "Updated <Mon D>"
    (year taken from the capture instant; if that lands more than
    a day in the capture's future, the previous year is meant).
    Date-only stamps resolve to their 00:00 ET floor and report
    precision "date"; time-bearing stamps report "instant" -- the
    evaluator refuses an instant stamp that postdates the fetch
    that recorded it, a contradiction a date-only stamp cannot
    commit (its floor is a construct, not a claimed instant).
    """
    verbatim, stamp_dt = parse_update_stamp(raw)
    if stamp_dt is not None:
        return verbatim, stamp_dt, "instant"
    match = _PUBLISHED_RE.search(str(raw or ""))
    if match:
        return match.group(1), dt(match.group(1)), "instant"
    flat = _flatten_text(text)
    for regex in (_WS_STAMP_RE, _LAST_UPDATED_RE):
        match = regex.search(flat)
        if match:
            try:
                naive = datetime.strptime(match.group(1), "%B %d, %Y")
            except ValueError:
                try:
                    naive = datetime.strptime(match.group(1), "%b %d, %Y")
                except ValueError:
                    return match.group(0), None, "date"
            return match.group(0), _date_floor_utc(
                naive.year, naive.month, naive.day), "date"
    match = _TD_STAMP_RE.search(flat)
    if match and captured_at is not None:
        try:
            naive = datetime.strptime(match.group(1), "%b %d")
        except ValueError:
            return match.group(0), None, "date"
        candidate = _date_floor_utc(captured_at.year, naive.month, naive.day)
        if candidate is not None and (candidate - captured_at).days > 1:
            candidate = _date_floor_utc(
                captured_at.year - 1, naive.month, naive.day)
        return match.group(0), candidate, "date"
    return None, None, None


def _qb1_ourlads(content):
    order = parse_qb_order(content)
    if not order:
        normalized = normalize_ourlads_depth_html(content)
        order = parse_qb_order(normalized)
    if not order:
        raise ValueError("PARSE_QB1_NOT_FOUND")
    return order[0]["name"]


def _qb1_sentence_or_line(flat):
    match = _SENTENCE_QB1_RE.search(flat)
    if match:
        return match.group(1)
    match = _QB_LINE_RE.search(flat)
    if match:
        return match.group(1)
    raise ValueError("PARSE_QB1_NOT_FOUND")


def _qb1_whosstarting(content):
    return _qb1_sentence_or_line(_flatten_text(content))


def _qb1_twodeep(content, team_lookup):
    if not team_lookup:
        raise ValueError("PARSE_TEAM_LOOKUP_MISSING")
    flat = _flatten_text(content)
    lowered = flat.lower()
    needle = " ".join(str(team_lookup).lower().split())
    keys = set()
    names = {}
    start = 0
    found = False
    while True:
        index = lowered.find(needle, start)
        if index < 0:
            break
        found = True
        window = flat[index:index + 1200]
        match = _TD_STARTER_RE.search(window)
        if match:
            name = " ".join(match.group(1).split())
            keys.add(_name_tokens(name))
            names[_name_tokens(name)] = name
        start = index + len(needle)
    if not found:
        raise ValueError("PARSE_TEAM_NOT_FOUND")
    if len(keys) != 1:
        raise ValueError("PARSE_QB1_NOT_FOUND")
    return names[keys.pop()]


def _qb1_sports247(content):
    flat = _flatten_text(content)
    match = _247_QB_RE.search(flat)
    if match:
        return " ".join(match.group(1).split())
    return _qb1_sentence_or_line(flat)


def _qb1_generic(content):
    order = parse_qb_order(content)
    if order:
        return order[0]["name"]
    return _qb1_sentence_or_line(_flatten_text(content))


_PARSERS = {
    "ourlads": lambda content, lookup: _qb1_ourlads(content),
    "cfbdepth": lambda content, lookup: _qb1_generic(content),
    "whosstarting": lambda content, lookup: _qb1_whosstarting(content),
    "twodeep": lambda content, lookup: _qb1_twodeep(content, lookup),
    "sports247": lambda content, lookup: _qb1_sports247(content),
    "generic": lambda content, lookup: _qb1_generic(content),
}


def parse_source_read(source_key, content, *, team_lookup=None, captured_at=None):
    """Derive (qb1, stamp_verbatim, stamp_dt, stamp_precision).

    The QB1 is always DERIVED from the captured content -- the same
    parser runs at capture and at evaluation, and a recorded QB1
    that disagrees with the derivation invalidates the read.
    Raises ValueError with a named detail when no QB1 can be read.
    """
    spec = SOURCE_REGISTRY.get(source_key)
    if spec is None:
        raise ValueError("UNKNOWN_SOURCE:" + str(source_key))
    parser = _PARSERS[spec["parser"]]
    qb1 = parser(content, team_lookup)
    stamp_verbatim, stamp_dt, precision = _parse_stamp(
        content, content, captured_at)
    return qb1, stamp_verbatim, stamp_dt, precision


# ---------------------------------------------------------------------------
# Collector -- produces source reads under receipt discipline. Used at
# capture time by an operator/runner step; evaluation never fetches.
# ---------------------------------------------------------------------------
def _fetch_text(url):
    req = Request(url, headers={"User-Agent": "SportsEdge-free-context/1.0"})
    with urlopen(req, timeout=15) as response:
        return response.read().decode("utf-8", "replace")


def _utc_iso(moment):
    return moment.astimezone(timezone.utc).isoformat()


def collect_source_read(source_key, url, *, team_lookup=None,
                        fetch_text=None, clock=None):
    """Fetch and parse ONE registered source into a read record.

    The fetched-at timestamp is taken AFTER the fetch attempt
    completes (success or failure), mirroring the frozen path's
    completion-time receipts. A fetch failure or an unparseable
    page yields outcome SOURCE_UNREACHABLE with the named reason;
    it is recorded, never dropped and never treated as agreement.
    """
    spec = SOURCE_REGISTRY.get(source_key)
    if spec is None:
        raise ValueError("UNKNOWN_SOURCE:" + str(source_key))
    fetch_text = fetch_text or _fetch_text
    capture_clock = clock or (lambda: datetime.now(timezone.utc))

    def completed_at():
        recorded = capture_clock()
        if (not isinstance(recorded, datetime) or recorded.tzinfo is None
                or recorded.utcoffset() is None):
            raise ValueError(STATUS_MISSING + ":CAPTURE_CLOCK_UNVERIFIED")
        return recorded.astimezone(timezone.utc)

    read = {
        "source": source_key,
        "role": spec["role"],
        "social": bool(spec["social"]),
        "url": url,
        "team_lookup": team_lookup,
        "fetched_at_utc": None,
        "outcome": READ_UNREACHABLE,
        "reason": None,
        "stamp_verbatim": None,
        "stamp_utc": None,
        "stamp_precision": None,
        "qb1_as_listed": None,
        "content_sha256": None,
        "content": None,
    }
    try:
        content = fetch_text(url)
    except Exception as exc:  # fetch barrier: record, never fake
        read["fetched_at_utc"] = _utc_iso(completed_at())
        read["reason"] = f"FETCH_FAILED:{type(exc).__name__}:{str(exc)[:120]}"
        return read
    fetched = completed_at()
    read["fetched_at_utc"] = _utc_iso(fetched)
    read["content"] = content
    read["content_sha256"] = sha256_text(content)
    try:
        qb1, stamp_verbatim, stamp_dt, precision = parse_source_read(
            source_key, content, team_lookup=team_lookup, captured_at=fetched)
    except ValueError as exc:
        read["reason"] = str(exc)
        return read
    read["outcome"] = READ_OK
    read["qb1_as_listed"] = qb1
    read["stamp_verbatim"] = stamp_verbatim
    read["stamp_utc"] = _utc_iso(stamp_dt) if stamp_dt is not None else None
    read["stamp_precision"] = precision
    return read


def collect_multi_reads(source_urls, *, team_lookup_by_source=None,
                        fetch_text=None, clock=None):
    """Collect every requested source, in registry order.

    ``source_urls`` maps registry keys to operator-supplied URLs.
    Every requested source produces exactly one read record --
    including the failures.
    """
    lookups = team_lookup_by_source or {}
    reads = []
    for source_key in SOURCE_REGISTRY:
        if source_key not in source_urls:
            continue
        reads.append(collect_source_read(
            source_key, source_urls[source_key],
            team_lookup=lookups.get(source_key),
            fetch_text=fetch_text, clock=clock))
    return reads


# ---------------------------------------------------------------------------
# Bundle assembly + receipt seal.
# ---------------------------------------------------------------------------
def receipt_chain_fields_multi(bundle):
    """The exact field set the multi receipt chain seals: the
    fixture binding, the previous-game bound, and every recorded
    read field (source, URL, fetched-at, outcome, reason, verbatim
    stamp, listed QB1, content hash). Read from the bundle's
    recorded fields only, so capture and evaluation compute over
    identical inputs by construction."""
    if not isinstance(bundle, dict):
        bundle = {}
    team = bundle.get("team") if isinstance(bundle.get("team"), dict) else {}
    fixture = (bundle.get("fixture")
               if isinstance(bundle.get("fixture"), dict) else {})
    previous = (bundle.get("previous_game")
                if isinstance(bundle.get("previous_game"), dict) else {})
    reads = bundle.get("source_reads")
    sealed_reads = []
    if isinstance(reads, list):
        for read in reads:
            if not isinstance(read, dict):
                sealed_reads.append({"malformed": True})
                continue
            sealed_reads.append({
                "source": read.get("source"),
                "role": read.get("role"),
                "url": read.get("url"),
                "team_lookup": read.get("team_lookup"),
                "fetched_at_utc": read.get("fetched_at_utc"),
                "outcome": read.get("outcome"),
                "reason": read.get("reason"),
                "stamp_verbatim": read.get("stamp_verbatim"),
                "stamp_utc": read.get("stamp_utc"),
                "stamp_precision": read.get("stamp_precision"),
                "qb1_as_listed": read.get("qb1_as_listed"),
                "content_sha256": read.get("content_sha256"),
            })
    return {
        "evidence_class": bundle.get("evidence_class"),
        "evidence_form": bundle.get("evidence_form"),
        "evidence_path": bundle.get("evidence_path"),
        "team_id": str(team.get("espn_id")) if team.get("espn_id") is not None else None,
        "opponent_id": (str(fixture.get("opponent_espn_id"))
                        if fixture.get("opponent_espn_id") is not None else None),
        "event_id": (str(fixture.get("event_id"))
                     if fixture.get("event_id") is not None else None),
        "fixture_kickoff_utc": fixture.get("kickoff_utc"),
        "previous_game_kickoff_utc": previous.get("kickoff_utc"),
        "source_reads": sealed_reads,
    }


def receipt_chain_sha256_multi(bundle):
    canonical = json.dumps(receipt_chain_fields_multi(bundle),
                           sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def build_multi_bundle(*, team_id, team_name, event_id, opponent_id,
                       kickoff_utc, previous_game_kickoff_utc, source_reads):
    """Assemble and seal a FORM2_MULTI_V1 bundle from collected reads.

    Raises ValueError when there is nothing to seal (no reads at
    all). A bundle whose reads all failed still seals -- it is the
    durable record of the attempt, and evaluation refuses it.
    """
    if not source_reads:
        raise ValueError(STATUS_MISSING + ":NO_SOURCE_READS")
    bundle = {
        "evidence_class": EVIDENCE_CLASS,
        "evidence_form": EVIDENCE_FORM_MULTI,
        "evidence_path": EVIDENCE_PATH,
        "sport": "CFB",
        "team": {"espn_id": str(team_id), "name": team_name},
        "fixture": {"event_id": str(event_id),
                    "opponent_espn_id": str(opponent_id),
                    "kickoff_utc": kickoff_utc},
        "previous_game": {"kickoff_utc": previous_game_kickoff_utc},
        "source_reads": source_reads,
    }
    bundle["receipt"] = {"version": RECEIPT_VERSION_MULTI,
                         "sha256": receipt_chain_sha256_multi(bundle)}
    return bundle


# ---------------------------------------------------------------------------
# Evaluator -- verifies one multi-source bundle for one fixture team.
# Fail-closed; never fetches.
# ---------------------------------------------------------------------------
def _fail(status, detail, receipt=None):
    return {"ok": False, "status": status, "detail": detail,
            "resolved_qb1_name": None,
            "availability_status": None, "injury_points": 0.0,
            "receipt": receipt}


def _host_of(url):
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _independent(read_a, read_b):
    """Independence: different registry source AND different host."""
    if read_a.get("source") == read_b.get("source"):
        return False
    return _host_of(read_a.get("url")) != _host_of(read_b.get("url"))


def evaluate_multi_bundle(bundle, *, team_id, kickoff,
                          previous_game_kickoff=None, now=None,
                          event_id=None, home_team_id=None,
                          away_team_id=None):
    """Verify one FORM2_MULTI_V1 bundle for one fixture team.

    ``event_id`` / ``home_team_id`` / ``away_team_id`` are the STAGED
    fixture's identity (the frozen path's exact-binding rule): when
    the caller cannot supply them, exact binding cannot be
    established and the bundle fails closed. Returns a result dict;
    on success it carries the receipt, the primary's QB1 as listed,
    and the AVAILABILITY_UNVERIFIED label -- never an availability
    claim.
    """
    team_id = str(team_id)
    if not isinstance(bundle, dict):
        return _fail(STATUS_MISSING, "BUNDLE_ABSENT")
    if (bundle.get("evidence_class") != EVIDENCE_CLASS
            or bundle.get("evidence_form") != EVIDENCE_FORM_MULTI
            or bundle.get("evidence_path") != EVIDENCE_PATH):
        return _fail(STATUS_MISSING, "WRONG_EVIDENCE_FORM")
    team = bundle.get("team") if isinstance(bundle.get("team"), dict) else {}
    if str(team.get("espn_id")) != team_id:
        return _fail(STATUS_MISSING, "TEAM_BINDING_MISMATCH")

    fixture = (bundle.get("fixture")
               if isinstance(bundle.get("fixture"), dict) else {})
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

    reads = bundle.get("source_reads")
    if not isinstance(reads, list) or not reads:
        return _fail(STATUS_MISSING, "NO_SOURCE_READS")

    receipt = {
        "evidence_class": EVIDENCE_CLASS,
        "evidence_form": EVIDENCE_FORM_MULTI,
        "evidence_path": EVIDENCE_PATH,
        "team_id": team_id,
        "event_id": str(fixture.get("event_id")),
        "opponent_espn_id": str(fixture.get("opponent_espn_id")),
        "receipt_version": RECEIPT_VERSION_MULTI,
        "receipt_sha256": None,
        "resolved_qb1_name": None,
        "primary_source": None,
        "corroborating_sources": [],
        "availability_status": None,
        "injury_points": 0.0,
        "reads": [{
            "source": r.get("source") if isinstance(r, dict) else None,
            "outcome": r.get("outcome") if isinstance(r, dict) else None,
            "reason": r.get("reason") if isinstance(r, dict) else None,
            "stamp_verbatim": (r.get("stamp_verbatim")
                               if isinstance(r, dict) else None),
            "qb1_as_listed": (r.get("qb1_as_listed")
                              if isinstance(r, dict) else None),
        } for r in reads],
    }

    sealed = bundle.get("receipt")
    if not isinstance(sealed, dict) or sealed.get("version") != RECEIPT_VERSION_MULTI:
        return _fail(STATUS_HASH_MISMATCH, "RECEIPT_CHAIN_MISSING", receipt)
    chain = receipt_chain_sha256_multi(bundle)
    if sealed.get("sha256") != chain:
        return _fail(STATUS_HASH_MISMATCH, "RECEIPT_CHAIN_MISMATCH", receipt)
    receipt["receipt_sha256"] = chain

    # Previous-game bound attestation discipline (frozen mirror).
    previous = (bundle.get("previous_game")
                if isinstance(bundle.get("previous_game"), dict) else {})
    attested_prev = dt(previous.get("kickoff_utc"))
    prev = previous_game_kickoff or attested_prev
    if (previous_game_kickoff is not None and attested_prev is not None
            and abs((previous_game_kickoff - attested_prev).total_seconds()) > 120):
        return _fail(STATUS_PRIMARY_STALE,
                     "PREVIOUS_GAME_ATTESTATION_MISMATCH", receipt)
    if prev is None:
        return _fail(STATUS_PRIMARY_STALE,
                     "PREVIOUS_GAME_BOUND_UNVERIFIABLE", receipt)

    # Validate reads: content hashes, capture timing, and the
    # derived-vs-asserted rule (the QB1 and stamp are re-derived
    # from the captured bytes; a recorded value that disagrees
    # invalidates the read -- it is never silently trusted).
    valid = []
    for read in reads:
        if not isinstance(read, dict) or read.get("outcome") != READ_OK:
            continue
        source_key = read.get("source")
        if source_key not in SOURCE_REGISTRY:
            continue
        content = read.get("content")
        if not isinstance(content, str):
            continue
        if sha256_text(content) != read.get("content_sha256"):
            return _fail(STATUS_HASH_MISMATCH,
                         "READ_CONTENT_SHA256_MISMATCH", receipt)
        fetched = dt(read.get("fetched_at_utc"))
        if fetched is None:
            continue
        if fetched >= kickoff:
            continue  # CAPTURE_AT_OR_AFTER_KICKOFF: not evidence
        if now is not None and fetched > now:
            continue  # CAPTURE_IN_FUTURE
        try:
            qb1, stamp_verbatim, stamp_dt, precision = parse_source_read(
                source_key, content,
                team_lookup=read.get("team_lookup"), captured_at=fetched)
        except ValueError:
            continue  # READ_QB1_UNDERIVABLE
        if _name_tokens(qb1) != _name_tokens(read.get("qb1_as_listed")):
            continue  # READ_QB1_REDERIVATION_MISMATCH
        if stamp_verbatim != read.get("stamp_verbatim"):
            continue  # READ_STAMP_REDERIVATION_MISMATCH
        if precision != read.get("stamp_precision"):
            continue  # READ_STAMP_PRECISION_MISMATCH
        if precision == "instant" and stamp_dt is not None \
                and stamp_dt > fetched:
            continue  # STAMP_AFTER_FETCH: the bytes cannot contain an
            # update stamped after the capture that recorded them
        valid.append({
            "read": read, "source": source_key,
            "role": SOURCE_REGISTRY[source_key]["role"],
            "social": bool(SOURCE_REGISTRY[source_key]["social"]),
            "qb1_name": read.get("qb1_as_listed"),
            "qb1_key": _name_tokens(qb1),
            "stamp_dt": stamp_dt,
            "current": stamp_dt is not None and stamp_dt > prev,
        })

    primaries = [v for v in valid if v["role"] == ROLE_PRIMARY]
    if not primaries:
        return _fail(STATUS_MISSING, "NO_PRIMARY_READ", receipt)
    fresh_primaries = [v for v in primaries if v["current"]]
    if not fresh_primaries:
        if all(v["stamp_dt"] is None for v in primaries):
            return _fail(STATUS_PRIMARY_STALE,
                         "PRIMARY_STAMP_UNPARSEABLE", receipt)
        return _fail(STATUS_PRIMARY_STALE,
                     "STAMP_PREDATES_PREVIOUS_GAME_KICKOFF", receipt)
    primary_keys = {v["qb1_key"] for v in fresh_primaries}
    if len(primary_keys) > 1:
        return _fail(STATUS_CONFLICT,
                     "PRIMARY_SOURCES_DISAGREE", receipt)
    primary = fresh_primaries[0]
    receipt["primary_source"] = primary["source"]
    receipt["resolved_qb1_name"] = primary["qb1_name"]

    # Corroboration pool: independent, current reads other than the
    # anchoring read itself. Conflict is scanned across ALL current
    # pool reads before agreement is counted: one current dissent
    # refuses the bundle no matter how many agree.
    pool = [v for v in valid
            if v is not primary and v["current"]
            and _independent(primary["read"], v["read"])]
    for other in pool:
        if other["qb1_key"] != primary["qb1_key"]:
            return _fail(STATUS_CONFLICT,
                         f"CURRENT_SOURCE_DISAGREES:{other['source']}",
                         receipt)
    agreeing = [v for v in pool if v["qb1_key"] == primary["qb1_key"]]
    non_social_agreeing = [v for v in agreeing if not v["social"]]
    if not non_social_agreeing:
        if agreeing:
            return _fail(STATUS_SINGLE_SOURCE,
                         "SOCIAL_CORROBORATION_ONLY", receipt)
        stale_pool = [v for v in valid
                      if v is not primary and not v["current"]
                      and _independent(primary["read"], v["read"])]
        if stale_pool:
            return _fail(STATUS_SINGLE_SOURCE,
                         "CORROBORATOR_STALE_ONLY", receipt)
        return _fail(STATUS_SINGLE_SOURCE,
                     "NO_INDEPENDENT_CORROBORATOR", receipt)
    receipt["corroborating_sources"] = [v["source"]
                                        for v in non_social_agreeing]
    receipt["availability_status"] = AVAILABILITY_UNVERIFIED
    return {"ok": True, "status": STATUS_SATISFIED_MULTI,
            "detail": (f"PRIMARY_{primary['source']}_CORROBORATED_BY_"
                       + "_".join(receipt["corroborating_sources"])),
            "resolved_qb1_name": primary["qb1_name"],
            "availability_status": AVAILABILITY_UNVERIFIED,
            "injury_points": 0.0, "receipt": receipt}


# ---------------------------------------------------------------------------
# Multi archive writer -- the frozen archive writer validates through
# the frozen evaluator and so rejects this evidence form by design.
# This writer mirrors its discipline (write-once, content-addressed,
# immutable single-receipt manifests, seal-by-enumeration) under a
# distinct schema, without touching the frozen archive or its files.
# ---------------------------------------------------------------------------
MULTI_MANIFEST_SCHEMA = "CFB_FORM2_MULTI_ARCHIVE_MANIFEST_V1"
MAX_MULTI_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_MULTI_MANIFEST_BYTES = 1024 * 1024

DEFAULT_MULTI_EVIDENCE_ROOT = str(
    Path.home() / "workspace" / "sportsedge"
    / "operative_run_20261024_cfb_full_slate" / "multi_evidence")


class MultiArchiveError(ValueError):
    pass


def _canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _publish_once_multi(root, name, raw):
    """Publish complete bytes atomically without replacing an
    existing object (the frozen archive's discipline, re-implemented
    here so the frozen module is never imported for its privates)."""
    import uuid
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".pending-" + uuid.uuid4().hex
    try:
        fd = os.open(temporary,
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, name, src_dir_fd=directory,
                    dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            existing = _read_multi_object(root, name)
            if existing != raw:
                raise MultiArchiveError("MULTI_EXISTING_OBJECT_MISMATCH")
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def _read_multi_object(root, name):
    import stat as _stat
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not _stat.S_ISREG(info.st_mode):
                raise MultiArchiveError("MULTI_OBJECT_NOT_REGULAR")
            with os.fdopen(fd, "rb") as handle:
                fd = None
                return handle.read(MAX_MULTI_BUNDLE_BYTES + 1)
        finally:
            if fd is not None:
                os.close(fd)
    except OSError as exc:
        raise MultiArchiveError("MULTI_OBJECT_UNREADABLE") from exc
    finally:
        os.close(directory)


def preserve_multi_bundle(root, *, bundle, team_id, event_id,
                          home_team_id, away_team_id, kickoff,
                          previous_game_kickoff=None, clock=None):
    """Write-once preservation of ONE multi bundle + its manifest.

    The bundle is stored content-addressed, then evaluated in full;
    a bundle that does not pass evaluation publishes NO manifest
    (the stored object alone is the record of a refused capture,
    exactly as a failed frozen preservation leaves a bundle object
    but no manifest). The returned candidate digest is NOT an
    independently trusted anchor.
    """
    raw = _canonical_bytes(bundle)
    if len(raw) > MAX_MULTI_BUNDLE_BYTES:
        raise MultiArchiveError("MULTI_BUNDLE_TOO_LARGE")
    digest = hashlib.sha256(raw).hexdigest()
    os.makedirs(root, exist_ok=True)
    _publish_once_multi(root, digest + ".json", raw)
    recorded = (clock or (lambda: datetime.now(timezone.utc)))()
    if not isinstance(recorded, datetime) or recorded.tzinfo is None:
        raise MultiArchiveError("MULTI_ARCHIVE_TIME_INVALID")
    recorded = recorded.astimezone(timezone.utc)
    kickoff_dt = dt(kickoff) if not isinstance(kickoff, datetime) else kickoff
    if kickoff_dt is None:
        raise MultiArchiveError("MULTI_ARCHIVE_TIME_INVALID")
    if recorded >= kickoff_dt:
        raise MultiArchiveError("MULTI_RECEIPT_NOT_AVAILABLE")
    for read in bundle.get("source_reads", []):
        fetched = dt(read.get("fetched_at_utc")) if isinstance(read, dict) else None
        if fetched is not None and fetched > recorded:
            raise MultiArchiveError("MULTI_RECEIPT_PRECEDES_FETCH")
    result = evaluate_multi_bundle(
        bundle, team_id=team_id, event_id=event_id,
        home_team_id=home_team_id, away_team_id=away_team_id,
        kickoff=kickoff_dt,
        previous_game_kickoff=(dt(previous_game_kickoff)
                               if previous_game_kickoff else None),
        now=recorded)
    if not result.get("ok"):
        raise MultiArchiveError(
            "MULTI_BUNDLE_REJECTED:" + str(result.get("status")))
    manifest = {"schema": MULTI_MANIFEST_SCHEMA, "entries": [{
        "team_id": str(team_id), "event_id": str(event_id),
        "home_team_id": str(home_team_id),
        "away_team_id": str(away_team_id),
        "kickoff_utc": kickoff_dt.isoformat(),
        "recorded_at_utc": recorded.isoformat(),
        "bundle_sha256": digest,
        "evidence_form": EVIDENCE_FORM_MULTI,
        "evidence_path": EVIDENCE_PATH,
    }]}
    manifest_raw = _canonical_bytes(manifest)
    candidate = hashlib.sha256(manifest_raw).hexdigest()
    _publish_once_multi(root, candidate + ".json", manifest_raw)
    return {"manifest_bytes": manifest_raw,
            "candidate_manifest_sha256": candidate,
            "bundle_sha256": digest,
            "recorded_at_utc": recorded.isoformat(),
            "identity_evidence": result,
            "anchor_status": "UNANCHORED", "research_only": True,
            "eligibility": False, "staking_allowed": False,
            "activation_allowed": False}


def seal_multi_archive_manifest(root, *, manifest_sha256s):
    """Seal ONE archive-level manifest over preserved multi bundles.

    Enumeration only: each named single-receipt manifest is read
    back and verified against its digest, each bundle against its
    content address and its binding (team, event, roles, kickoff,
    receipt ordering). A fixture/team covered twice fails closed.
    The candidate digest becomes a consumer pin only when an
    operator supplies it from an independent channel.
    """
    if isinstance(manifest_sha256s, (str, bytes)) or not manifest_sha256s:
        raise MultiArchiveError("MULTI_SEAL_NO_MANIFESTS")
    entries = []
    seen_fixtures = set()
    seen_bundles = set()
    for value in manifest_sha256s:
        pin = str(value)
        if re.fullmatch(r"[0-9a-f]{64}", pin) is None:
            raise MultiArchiveError("MULTI_DIGEST_INVALID")
        raw_manifest = _read_multi_object(root, pin + ".json")
        if len(raw_manifest) > MAX_MULTI_MANIFEST_BYTES:
            raise MultiArchiveError("MULTI_MANIFEST_TOO_LARGE")
        if hashlib.sha256(raw_manifest).hexdigest() != pin:
            raise MultiArchiveError("MULTI_MANIFEST_HASH_MISMATCH")
        manifest = json.loads(raw_manifest.decode("utf-8"))
        if not isinstance(manifest, dict) \
                or manifest.get("schema") != MULTI_MANIFEST_SCHEMA:
            raise MultiArchiveError("MULTI_SCHEMA_INVALID")
        receipts = manifest.get("entries")
        if not isinstance(receipts, list) or len(receipts) != 1 \
                or not isinstance(receipts[0], dict):
            raise MultiArchiveError(
                "MULTI_SEAL_REQUIRES_SINGLE_RECEIPT_MANIFEST")
        entry = receipts[0]
        fixture_key = (str(entry.get("team_id")), str(entry.get("event_id")))
        if fixture_key in seen_fixtures:
            raise MultiArchiveError("MULTI_RECEIPT_NOT_UNIQUE")
        seen_fixtures.add(fixture_key)
        digest = str(entry.get("bundle_sha256"))
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None \
                or digest in seen_bundles:
            raise MultiArchiveError("MULTI_RECEIPT_NOT_UNIQUE")
        seen_bundles.add(digest)
        raw_bundle = _read_multi_object(root, digest + ".json")
        if hashlib.sha256(raw_bundle).hexdigest() != digest:
            raise MultiArchiveError("MULTI_BUNDLE_HASH_MISMATCH")
        bundle = json.loads(raw_bundle.decode("utf-8"))
        team = bundle.get("team", {})
        fixture = bundle.get("fixture", {})
        if str(entry.get("team_id")) != str(team.get("espn_id")) \
                or str(entry.get("event_id")) != str(fixture.get("event_id")):
            raise MultiArchiveError("MULTI_FIXTURE_MISMATCH")
        roles = {str(entry.get("home_team_id")), str(entry.get("away_team_id"))}
        if roles != {str(team.get("espn_id")),
                     str(fixture.get("opponent_espn_id"))}:
            raise MultiArchiveError("MULTI_FIXTURE_MISMATCH")
        if dt(entry.get("kickoff_utc")) != dt(fixture.get("kickoff_utc")):
            raise MultiArchiveError("MULTI_FIXTURE_MISMATCH")
        recorded = dt(entry.get("recorded_at_utc"))
        if recorded is None or recorded >= dt(entry.get("kickoff_utc")):
            raise MultiArchiveError("MULTI_RECEIPT_NOT_AVAILABLE")
        for read in bundle.get("source_reads", []):
            fetched = dt(read.get("fetched_at_utc")) if isinstance(read, dict) else None
            if fetched is not None and fetched > recorded:
                raise MultiArchiveError("MULTI_RECEIPT_PRECEDES_FETCH")
        entries.append(entry)
    entries.sort(key=lambda e: (str(e["event_id"]), str(e["team_id"]),
                                str(e["bundle_sha256"])))
    combined = {"schema": MULTI_MANIFEST_SCHEMA, "entries": entries}
    raw = _canonical_bytes(combined)
    if len(raw) > MAX_MULTI_MANIFEST_BYTES:
        raise MultiArchiveError("MULTI_MANIFEST_TOO_LARGE")
    candidate = hashlib.sha256(raw).hexdigest()
    _publish_once_multi(root, candidate + ".json", raw)
    return {"manifest_bytes": raw, "candidate_manifest_sha256": candidate,
            "bundle_sha256s": sorted(seen_bundles),
            "receipt_count": len(entries),
            "anchor_status": "UNANCHORED", "research_only": True,
            "eligibility": False, "staking_allowed": False,
            "activation_allowed": False}


# ---------------------------------------------------------------------------
# Capture CLI -- produces a FORM2_MULTI_V1 bundle. Used at capture
# time, pre-kickoff, by an operator step; evaluation never fetches
# and the runner never calls this module.
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Capture a QB_IDENTITY_EVIDENCE FORM2_MULTI_V1 "
                    "bundle (MULTI_SOURCE_CORROBORATION) for one CFB "
                    "fixture team.")
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--team-name", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--opponent-id", required=True)
    parser.add_argument("--kickoff", required=True,
                        help="fixture kickoff, ISO UTC")
    parser.add_argument("--previous-game-kickoff", required=True,
                        help="kickoff of the team's most recent "
                             "completed game, ISO UTC")
    parser.add_argument("--source", action="append", default=[],
                        metavar="KEY=URL",
                        help="registered source key and its "
                             "operator-supplied URL (repeatable)")
    parser.add_argument("--team-lookup", action="append", default=[],
                        metavar="KEY=NAME",
                        help="the team's name as the source itself "
                             "prints it (e.g. TWODEEP=BYU)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    source_urls = {}
    for item in args.source:
        key, _, url = item.partition("=")
        if key not in SOURCE_REGISTRY or not url:
            parser.error(f"bad --source {item!r}: unknown key or empty URL")
        source_urls[key] = url
    lookups = {}
    for item in args.team_lookup:
        key, _, name = item.partition("=")
        lookups[key] = name
    reads = collect_multi_reads(source_urls, team_lookup_by_source=lookups)
    bundle = build_multi_bundle(
        team_id=args.team_id, team_name=args.team_name,
        event_id=args.event_id, opponent_id=args.opponent_id,
        kickoff_utc=args.kickoff,
        previous_game_kickoff_utc=args.previous_game_kickoff,
        source_reads=reads)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, indent=2)
    for read in reads:
        print(f"{read['source']}: {read['outcome']}"
              + (f" ({read['reason']})" if read["reason"] else "")
              + (f" QB1 {read['qb1_as_listed']!r} stamp "
                 f"{read['stamp_verbatim']!r}"
                 if read["outcome"] == READ_OK else ""))
    print(f"WROTE {args.out}: {EVIDENCE_PATH} team {args.team_id} "
          f"({len(reads)} source reads)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
