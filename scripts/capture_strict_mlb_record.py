#!/usr/bin/env python3
"""Capture one live, pregame strict-evaluator record for an MLB game market.

Reads a capture-input JSON (schema SPORTSEDGE_STRICT_CAPTURE_INPUT_V1,
see below), runs the FROZEN production pricer (artifacts/run_it_full.py,
Lane A market-blind) at capture time, computes the comparison-model
probability (in-repo Elo floor, ML only in v1), stamps the model source
SHA from git HEAD, and writes ONE immutable record into the
forward-capture archive via sportsedge/backtest/forward_capture.py.

Input JSON fields (all required):
    schema                      "SPORTSEDGE_STRICT_CAPTURE_INPUT_V1"
    away, home                  full team names, e.g. "Tampa Bay Rays"
    kickoff_utc                 scheduled first pitch, ISO-8601 UTC
    series_id                   series block label, e.g. "2026-ALCS-CLE-TB"
    market                      "ML" (v1); "SPREAD"/"TOTAL" fail closed
    selection                   "HOME" or "AWAY" (ML)
    line                        "ML" for moneyline
    book                        sportsbook key, e.g. "draftkings"
    selection_american          American price for the selection
    selection_captured_at_utc   when that price was observed (ISO UTC)
    opposite_american           American price for the opposite selection
    opposite_captured_at_utc    when that price was observed (ISO UTC)
    quote_source                provenance string for the quote capture

Evaluator timing rules the operator must respect (enforced at evaluation;
violations are archived truthfully but flagged as warnings here):
both quotes before first pitch, <=120s apart, latest quote <=1800s
(30 min) before first pitch. Run this script AFTER capturing the quotes
and BEFORE first pitch: the production run instant becomes as_of_utc.

Example:
    python scripts/capture_strict_mlb_record.py \
        --input capture_cle_tb.json \
        --archive-dir archive/strict-forward-capture
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.backtest import forward_capture as fc
from sportsedge.backtest.elo import EloRatings
from sportsedge.backtest.outcomes import (fetch_mlb_schedule,
                                          parse_completed_mlb_games)
# The shared fetcher's default HTTP getter, imported so the Elo leg's
# provenance-recording getter (below) can DELEGATE to it: HTTP
# semantics (size cap, fail-closed on non-200/malformed) stay
# single-sourced in outcomes.py. The wrapper only observes when a
# fetch happened and whether the on-disk cache served the payload —
# it reimplements neither the URL construction nor the parsing.
from sportsedge.backtest.outcomes import _public_json as \
    _default_schedule_getter

INPUT_SCHEMA = "SPORTSEDGE_STRICT_CAPTURE_INPUT_V1"

# Allowable Elo TRAINING population (owner data-quality hold, issue
# #2086): regular-season and postseason games ONLY.
#   R = regular season, F = Wild Card round, D = Division Series,
#   L = League Championship Series, W = World Series.
# Spring training (S), exhibitions (E), and the All-Star game (A) are
# EXCLUDED because lineups and effort in those games are not
# competitive, so their results would contaminate the market-free Elo
# floor. parse_completed_mlb_games drops gameType, so this filter is
# applied to the raw fetched schedule inside the Elo leg, before
# parsing. A game whose gameType is missing or unrecognized is
# excluded (fail closed) and counted under "UNKNOWN" in the summary.
ELO_TRAINING_GAME_TYPES = frozenset({"R", "F", "D", "L", "W"})

# Elo-leg schedule cache (issue #2086 cache-provenance requirement).
# The shared fetcher's on-disk cache (outcomes._cached_fetch) stores
# ONLY the JSON payload — no fetch time, no provenance — so a bare
# cache hit cannot establish WHEN the payload was observed at the
# source. The Elo leg therefore uses its OWN cache directory plus a
# provenance manifest (written by _fetch_schedule_with_provenance)
# recording, per payload content hash, the instant the payload was
# originally retrieved over HTTP. A later cache hit is verified
# against that manifest by content-hash match; a payload with no
# manifest entry has an unestablishable observation time and the leg
# refuses (fail closed). The cache file's mtime was considered and
# rejected as evidence: nothing records it, any copy/touch rewrites
# it, and it is not bound to the payload's content.
SCHEDULE_CACHE_DIR = (Path(__file__).resolve().parents[1] / ".cache"
                      / "mlb_schedule")
SCHEDULE_PROVENANCE_MANIFEST = "provenance_manifest.json"

# Schedule FRESHNESS bound (owner qualification, issue #2086):
# point-in-time provenance proves a payload was OBSERVED before the
# cutoff; it does NOT prove the payload is COMPLETE. A schedule
# observed hours earlier omits games completed since the observation,
# and with no bound it would remain eligible indefinitely. The
# manifest and this bound TOGETHER bound staleness; neither alone
# does — the manifest alone proves observation, not completeness.
# The capture runs minutes before first pitch, so the training
# snapshot must be current to the capture session: 900 seconds is
# half the evaluator's 1800-second verified-close window, leaving
# room inside that window for the rest of the capture. A verified
# observation older than the bound (relative to the consumer read)
# forces one fresh HTTP re-observation through the recording getter;
# if that refresh fails, the Elo leg refuses.
ELO_SCHEDULE_MAX_AGE_SECONDS = 900

REQUIRED_INPUT = (
    "schema", "away", "home", "kickoff_utc", "series_id", "market",
    "selection", "line", "book", "selection_american",
    "selection_captured_at_utc", "opposite_american",
    "opposite_captured_at_utc", "quote_source",
)


def fail(message):
    print(json.dumps({"status": "CAPTURE_REFUSED", "reason": message}))
    return 1


def git_head_sha(repo_root):
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo_root),
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (out.stdout or "").strip()
    return sha if out.returncode == 0 and len(sha) >= 7 else None


def production_probability(payload_row, now):
    """Run the frozen production path; return (candidate_p, prediction, row).

    Lane discipline: the candidate is ALWAYS the market-blind Lane A
    probability for the payload row's own selection and line. Lane B is
    market-anchored by construction; its probability is carried in the
    prediction section labeled MARKET_ANCHORED and is never returned as
    the candidate.
    """
    from artifacts.run_it_full import run_full
    card = run_full({"lines": [payload_row]}, now=now, lane="A")
    rows = card.get("evaluated_rows") or []
    if len(rows) != 1:
        raise fc.CaptureError("PRODUCTION_ROW_COUNT_UNEXPECTED")
    row = rows[0]
    status = str(row.get("status") or "")
    if status.startswith("BLOCKED"):
        raise fc.CaptureError("PRODUCTION_PRICING_BLOCKED:" + status)
    lanes = row.get("pricing_lanes") or {}
    lane_a = lanes.get("lane_a_independent") or {}
    lane_b = lanes.get("lane_b_anchored") or {}
    p = lane_a.get("estimate_p", row.get("estimate_p"))
    if p is None:
        raise fc.CaptureError("PRODUCTION_PROBABILITY_MISSING:" + status)
    candidate_p = float(p)
    push_p = lane_a.get("push_p", 0.0)
    prediction = {
        "candidate": {
            "lane": "LANE_A_INDEPENDENT", "label": "MARKET_BLIND",
            "win_p": candidate_p, "push_p": push_p,
            "loss_p": lane_a.get(
                "loss_p", round(1.0 - candidate_p - float(push_p), 6)),
        },
        "market_anchored": (
            {"lane": "LANE_B_ANCHORED", "label": "MARKET_ANCHORED",
             "win_p": lane_b.get("estimate_p"),
             "push_p": lane_b.get("push_p"),
             "loss_p": lane_b.get("loss_p")}
            if lane_b.get("estimate_p") is not None else None),
    }
    return candidate_p, prediction, row


def _split_training_population(dates, kickoff):
    """Filter the raw schedule to the allowable Elo training population.

    Returns (filtered_dates, summary). filtered_dates keeps only games
    whose StatsAPI gameType is in ELO_TRAINING_GAME_TYPES. summary
    counts COMPLETED games (detailedState "Final", the parser's own
    completion test) starting strictly before kickoff, by gameType,
    split into included vs excluded — the audit trail proving which
    population the ratings were trained on.
    """
    included_by_type, excluded_by_type = {}, {}
    filtered_dates = []
    for day in dates:
        if not isinstance(day, dict):
            filtered_dates.append(day)  # parser skips non-dict days
            continue
        kept = []
        for game in day.get("games") or []:
            if not isinstance(game, dict):
                kept.append(game)  # parser skips non-dict games
                continue
            game_type = str(game.get("gameType") or "").strip().upper()
            if game_type in ELO_TRAINING_GAME_TYPES:
                kept.append(game)
            status = str(((game.get("status") or {}).get(
                "detailedState") or ""))
            if status != "Final":
                continue  # not completed: in neither population
            try:
                start = datetime.fromisoformat(
                    str(game.get("gameDate") or "").replace("Z", "+00:00"))
                is_prior = start < kickoff
            except (TypeError, ValueError):
                continue  # cannot establish it as a prior completed game
            if not is_prior:
                continue
            bucket = (included_by_type
                      if game_type in ELO_TRAINING_GAME_TYPES
                      else excluded_by_type)
            key = game_type or "UNKNOWN"
            bucket[key] = bucket.get(key, 0) + 1
        filtered_day = dict(day)
        filtered_day["games"] = kept
        filtered_dates.append(filtered_day)
    summary = {
        "allowable_game_types": sorted(ELO_TRAINING_GAME_TYPES),
        "included_by_game_type": included_by_type,
        "included_total": sum(included_by_type.values()),
        "excluded_by_game_type": excluded_by_type,
        "excluded_total": sum(excluded_by_type.values()),
    }
    return filtered_dates, summary


def _utcnow():
    """Real-clock UTC instant (isolated so tests can inject the clock)."""
    return datetime.now(timezone.utc)


def _schedule_content_sha256(dates):
    """SHA-256 over the canonical serialization of a parsed schedule.

    Canonical form: JSON with sorted keys and compact separators, UTF-8.
    The shared fetcher (outcomes.fetch_mlb_schedule) returns PARSED JSON,
    so this hash binds the parsed content the Elo leg actually consumed
    — NOT the raw HTTP response bytes. Byte-level hashing would require
    a fetcher change on main and is deliberately out of scope here.
    """
    canonical = json.dumps(dates, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_provenance_manifest(cache_dir):
    """CLI provenance manifest: {dates content hash: entry}.

    Entries are written ONLY by _fetch_schedule_with_provenance at
    the moment of an original HTTP retrieval. Any read/parse problem
    yields an empty manifest — which fails closed downstream (a cache
    hit then has no verifiable original observation time).
    """
    try:
        raw = (Path(cache_dir) / SCHEDULE_PROVENANCE_MANIFEST).read_text(
            encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_provenance_manifest(cache_dir, dates_hash, entry):
    """Record one original-observation entry (best effort).

    A failed manifest write is NOT fatal to the current run — the
    in-run recording getter already established this run's observation
    instant. It only means a FUTURE cache hit on this payload will
    find no entry and refuse: the safe direction.
    """
    try:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        manifest = _read_provenance_manifest(cache_dir)
        manifest[dates_hash] = entry
        (cache_dir / SCHEDULE_PROVENANCE_MANIFEST).write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8")
    except OSError:
        pass


def _make_recording_getter(sink):
    """Build a getter that DELEGATES to the shared fetcher's default
    HTTP getter and, when a dict response comes back, stamps the
    source-observation instant into sink["observed_at"]. HTTP
    semantics (URL handling upstream, size cap, parsing) stay
    single-sourced in outcomes.py; this only observes WHEN a response
    was obtained."""
    def _recording_getter(url):
        data = _default_schedule_getter(url)
        if isinstance(data, dict):
            sink["observed_at"] = _utcnow()
        return data
    return _recording_getter


def _fetch_schedule_with_provenance(season_start, end_date):
    """Fetch the MLB schedule, distinguishing source observation from
    consumer read (owner requirement, issue #2086).

    Returns (dates, provenance_fields, source_observed_at,
    consumer_read_at) where provenance_fields is JSON-safe and
    source_observed_at is a datetime or None.

    WHY THIS WRAPPER EXISTS: the shared fetcher's cache
    (outcomes._cached_fetch) records no fetch time, so the previous
    implementation — stamping the clock when the helper returned —
    could not distinguish a FRESH HTTP observation from a CACHE HIT;
    on a hit, that stamp was merely the consumer-read instant and the
    payload might have been observed at any earlier unknown time,
    silently breaking the point-in-time demonstration. This wrapper
    is the thinnest provenance-recording layer that closes the gap
    without forking the shared fetcher: it injects a recording getter
    that delegates to the fetcher's own default HTTP getter (so URL
    construction, the response size cap, and parsing stay in
    outcomes.py), routes the fetch through the Elo leg's own cache
    directory, and maintains the provenance manifest described at
    SCHEDULE_CACHE_DIR.

    Provenance semantics:
      * getter invoked  -> source_origin "HTTP": the payload was
        retrieved from the source during THIS run; the getter stamps
        source_observed_at the instant the response was obtained, and
        a manifest entry binds that instant to the payload's content
        hash for future cache hits.
      * getter silent   -> source_origin "CACHE": the payload came
        from the on-disk cache. Its original observation instant is
        taken from the manifest entry for the payload's content hash
        (evidence: a record written by this CLI at the original HTTP
        retrieval, bound to these exact bytes by the hash). No entry
        -> source_observed_at is None: the observation time CANNOT be
        established, and the caller must fail closed.
      * consumer_read_at is stamped separately, when this leg
        consumed the payload — it is never presented as the source
        observation time.
    """
    sink = {}
    dates = fetch_mlb_schedule(
        season_start, end_date,
        getter=_make_recording_getter(sink),
        cache_dir=SCHEDULE_CACHE_DIR)
    consumer_read_at = _utcnow()
    dates_hash = _schedule_content_sha256(dates)
    if sink:
        source_origin = "HTTP"
        source_observed_at = sink["observed_at"]
        _record_provenance_manifest(SCHEDULE_CACHE_DIR, dates_hash, {
            "source_observed_at_utc": source_observed_at.isoformat(),
            "source_origin": "HTTP",
            "schedule_dates_sha256": dates_hash,
        })
        cache_provenance_basis = (
            "fresh HTTP retrieval in this run; the observation "
            "instant was stamped by the CLI recording getter when "
            "the source response was obtained, and a provenance "
            "manifest entry binding that instant to this payload's "
            "content hash was recorded for future cache hits")
    else:
        source_origin = "CACHE"
        source_observed_at = None
        entry = _read_provenance_manifest(SCHEDULE_CACHE_DIR).get(
            dates_hash)
        if isinstance(entry, dict):
            try:
                parsed = datetime.fromisoformat(
                    str(entry.get("source_observed_at_utc") or ""))
                if parsed.tzinfo is not None:
                    source_observed_at = parsed
            except ValueError:
                source_observed_at = None
        if source_observed_at is not None:
            cache_provenance_basis = (
                "cache hit; the original observation instant comes "
                "from the CLI provenance manifest entry recorded at "
                "the original HTTP retrieval, bound to this payload "
                "by SHA-256 content-hash match over the canonical "
                "serialization of the returned schedule dates")
        else:
            cache_provenance_basis = (
                "cache hit with NO provenance manifest entry for "
                "this payload's content hash; the original "
                "observation instant cannot be established (the "
                "shared fetcher's cache records no fetch time, and "
                "cache-file existence/mtime is not verified "
                "provenance)")
    provenance_fields = {
        "source_observed_at_utc": (source_observed_at.isoformat()
                                   if source_observed_at else None),
        "source_origin": source_origin,
        "consumer_read_at_utc": consumer_read_at.isoformat(),
        "cache_provenance_basis": cache_provenance_basis,
        # The manifest key: SHA-256 over the canonical serialization
        # of the FULL returned schedule, BEFORE the training-
        # population filter. It differs from schedule_content_sha256
        # (the filtered population the leg trains on) whenever the
        # filter removes games; an auditor verifying the manifest
        # lookup needs THIS hash.
        "schedule_manifest_lookup_sha256": dates_hash,
    }
    return dates, provenance_fields, source_observed_at, consumer_read_at


def _fetch_schedule_fresh_http(season_start, end_date):
    """Force a FRESH HTTP observation of the schedule (freshness
    policy, ELO_SCHEDULE_MAX_AGE_SECONDS), bypassing the on-disk
    cache entirely.

    Returns the same (dates, provenance_fields, source_observed_at,
    consumer_read_at) tuple as _fetch_schedule_with_provenance on
    success, or None when no fresh observation could be obtained —
    the source fetch failed or yielded no payload. The caller then
    refuses (fail closed); there is no silent fallback to the stale
    payload.

    cache_dir=None bypasses outcomes._cached_fetch, so the request
    goes through the recording getter. The refreshed payload's
    manifest entry is recorded under its (unfiltered) content hash,
    so a later run can verify a cache hit on these bytes if the
    shared cache ever holds them. The STALE cache entry itself is
    left untouched — the shared cache format belongs to
    outcomes.py — and will simply read as stale again on a later
    run and trigger another refresh.
    """
    sink = {}
    try:
        dates = fetch_mlb_schedule(
            season_start, end_date,
            getter=_make_recording_getter(sink), cache_dir=None)
    except Exception:
        # Any fetch-layer failure means the fresh observation could
        # not be obtained; the caller refuses on None.
        return None
    if "observed_at" not in sink or not isinstance(dates, list) \
            or not dates:
        return None
    source_observed_at = sink["observed_at"]
    consumer_read_at = _utcnow()
    dates_hash = _schedule_content_sha256(dates)
    _record_provenance_manifest(SCHEDULE_CACHE_DIR, dates_hash, {
        "source_observed_at_utc": source_observed_at.isoformat(),
        "source_origin": "HTTP",
        "schedule_dates_sha256": dates_hash,
    })
    provenance_fields = {
        "source_observed_at_utc": source_observed_at.isoformat(),
        "source_origin": "HTTP",
        "consumer_read_at_utc": consumer_read_at.isoformat(),
        "cache_provenance_basis": (
            "fresh HTTP retrieval forced by the schedule freshness "
            "policy: the verified cache observation was older than "
            "ELO_SCHEDULE_MAX_AGE_SECONDS relative to the consumer "
            "read, so the schedule was re-observed over HTTP in "
            "this run with the cache bypassed; the recording getter "
            "stamped the observation instant, and a provenance "
            "manifest entry binds that instant to this payload's "
            "content hash"),
        "schedule_manifest_lookup_sha256": dates_hash,
    }
    return dates, provenance_fields, source_observed_at, consumer_read_at


def elo_existing_probability(away, home, selection, kickoff):
    """Elo-floor P(selection) from completed games strictly before kickoff.

    The training population is ELO_TRAINING_GAME_TYPES only (regular
    season + postseason); spring training, exhibition, and All-Star
    results never enter the ratings.

    Also returns the training-cutoff basis: the latest start time among
    completed games involving either team before kickoff (a conservative
    lower bound of that game's final time; the production rating samples
    likewise contain only games completed before kickoff), the number
    of games the ratings were built from, the training-population
    summary (per-gameType included/excluded counts) for audit, and the
    schedule provenance (below).

    FINALITY + CACHE PROVENANCE (owner requirements, issue #2086):
    start time < kickoff plus a "Final" status in the response cannot
    by itself prove a game was final before the cutoff — a game
    starting one minute before the cutoff could finish afterward.
    The leg therefore records WHEN the schedule payload was observed
    at the source (source_observed_at_utc), HOW it arrived
    (source_origin: HTTP or CACHE), and WHEN this leg consumed it
    (consumer_read_at_utc) — three distinct facts the earlier single
    retrieval stamp conflated, because the shared fetcher's on-disk
    cache records no fetch time: on a cache hit the old stamp was
    merely the consumer-read instant. See
    _fetch_schedule_with_provenance for the mechanism and the
    evidence each timestamp rests on.

    FAIL CLOSED: unless the payload's source observation is
    established AND strictly before kickoff, this leg refuses with
    ELO_SCHEDULE_PROVENANCE_UNESTABLISHED and produces no
    probability. The rule is OBSERVATION-time based, not call-time
    based: what matters is when the payload was observed at the
    source, not when this function happens to be called. A later
    call that consumes a VERIFIED cache observation made before the
    kickoff is therefore legitimately eligible — that pre-cutoff
    observation is the point-in-time evidence. A FRESH observation
    made at or after the kickoff refuses. (An earlier description of
    this rule — "retrospective calls refuse by design" — was wrong:
    only retrospective OBSERVATIONS refuse.) Observation stamps are
    never backdated.

    FRESHNESS (owner qualification, issue #2086): provenance proves
    WHEN a payload was observed, not that it is COMPLETE — a
    schedule observed hours earlier omits games completed since, and
    with no bound it would stay eligible indefinitely. A verified
    observation older than ELO_SCHEDULE_MAX_AGE_SECONDS relative to
    the consumer read therefore forces one fresh HTTP re-observation
    through the recording getter (see _fetch_schedule_fresh_http):
    success replaces the payload (source_origin HTTP,
    schedule_freshness REFRESHED); failure refuses with
    ELO_SCHEDULE_PROVENANCE_UNESTABLISHED. The exported provenance
    carries schedule_age_seconds and schedule_freshness
    (WITHIN_BOUND or REFRESHED) so an auditor can see which case
    produced the probability. The manifest and the freshness bound
    TOGETHER bound staleness; neither alone does.
    """
    season_start = f"{kickoff.year}-01-01"
    local_date = kickoff.astimezone(ZoneInfo("America/New_York")).date()
    (dates, provenance_fields, source_observed_at,
     consumer_read_at) = _fetch_schedule_with_provenance(
        season_start, local_date.isoformat())
    # FRESHNESS POLICY: a verified observation older than the bound
    # (relative to the consumer read) is stale — it can omit games
    # completed since — so force one fresh HTTP re-observation.
    # Refresh failure refuses; there is no fallback to the stale
    # payload.
    schedule_age_seconds = None
    schedule_freshness = "UNKNOWN"
    if source_observed_at is not None:
        schedule_age_seconds = (
            consumer_read_at - source_observed_at).total_seconds()
        schedule_freshness = "WITHIN_BOUND"
    if (schedule_age_seconds is not None
            and schedule_age_seconds > ELO_SCHEDULE_MAX_AGE_SECONDS):
        refreshed = _fetch_schedule_fresh_http(
            season_start, local_date.isoformat())
        if refreshed is None:
            raise fc.CaptureError(
                "ELO_SCHEDULE_PROVENANCE_UNESTABLISHED: verified "
                "schedule observation is stale (schedule_age_seconds="
                "{age:.0f} exceeds ELO_SCHEDULE_MAX_AGE_SECONDS="
                "{bound}) and the forced fresh HTTP re-observation "
                "failed, so no Elo probability is produced".format(
                    age=schedule_age_seconds,
                    bound=ELO_SCHEDULE_MAX_AGE_SECONDS))
        (dates, provenance_fields, source_observed_at,
         consumer_read_at) = refreshed
        schedule_age_seconds = (
            consumer_read_at - source_observed_at).total_seconds()
        schedule_freshness = "REFRESHED"
    pit_established = (
        source_observed_at is not None
        and source_observed_at < kickoff
        and source_observed_at <= consumer_read_at)
    schedule_provenance = dict(provenance_fields)
    schedule_provenance["pit_provenance_status"] = (
        "PIT_PROVENANCE_ESTABLISHED" if pit_established
        else "PIT_PROVENANCE_INCOMPLETE")
    schedule_provenance["schedule_age_seconds"] = schedule_age_seconds
    schedule_provenance["schedule_freshness"] = schedule_freshness
    if not pit_established:
        raise fc.CaptureError(
            "ELO_SCHEDULE_PROVENANCE_UNESTABLISHED: "
            "source_origin={origin} source_observed_at_utc={observed} "
            "consumer_read_at_utc={read} kickoff_utc={kickoff} "
            "pit_provenance_status=PIT_PROVENANCE_INCOMPLETE — the "
            "schedule payload's pre-cutoff availability at the source "
            "cannot be established, so no Elo probability is "
            "produced".format(
                origin=provenance_fields["source_origin"],
                observed=provenance_fields["source_observed_at_utc"],
                read=provenance_fields["consumer_read_at_utc"],
                kickoff=kickoff.isoformat()))
    dates, training_population = _split_training_population(dates, kickoff)
    schedule_provenance["schedule_content_sha256"] = \
        _schedule_content_sha256(dates)
    schedule_provenance["schedule_hash_basis"] = (
        "SHA-256 over canonical JSON (sorted keys, compact "
        "separators) of the parsed, population-filtered schedule "
        "structure consumed by the Elo leg; binds parsed content, "
        "NOT raw response bytes (the shared fetcher returns parsed "
        "JSON)")
    games = parse_completed_mlb_games(dates)
    prior = []
    for game in games:
        start = datetime.fromisoformat(game["kickoff"].replace("Z", "+00:00"))
        if start < kickoff:
            prior.append((start, game))
    prior.sort(key=lambda item: item[0])
    if not prior:
        raise fc.CaptureError("ELO_NO_PRIOR_COMPLETED_GAMES")
    ratings = EloRatings("mlb")
    for start, game in prior:
        ratings.update_game(game["home_team"], game["away_team"],
                            game["home_score"], game["away_score"],
                            season=start.year)
    p_home = ratings.prob_home(home, away)
    team_games = [start for start, game in prior
                  if away in (game["home_team"], game["away_team"])
                  or home in (game["home_team"], game["away_team"])]
    if not team_games:
        raise fc.CaptureError("TRAIN_CUTOFF_UNESTABLISHED")
    train_last_final = max(team_games)
    existing = p_home if selection == "HOME" else 1.0 - p_home
    return (existing, train_last_final, len(prior), p_home,
            training_population, schedule_provenance)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--archive-dir", type=Path,
                        default=Path("archive") / fc.ARCHIVE_DIRNAME)
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        spec = json.loads(args.input.read_text(encoding="utf-8"))
        absent = [k for k in REQUIRED_INPUT
                  if k not in spec or spec[k] in (None, "")]
        if absent:
            return fail("INPUT_FIELDS_MISSING:" + ",".join(absent))
        if spec["schema"] != INPUT_SCHEMA:
            return fail("INPUT_SCHEMA_MISMATCH:" + str(spec["schema"]))
        market = str(spec["market"]).upper()
        if market != "ML":
            return fail("EXISTING_MODEL_PROBABILITY_UNAVAILABLE_FOR_MARKET:"
                        + market + " (Elo floor is ML-only in v1; refusing "
                        "to archive a record with an invented comparison "
                        "probability)")
        kickoff = fc._stamp(spec["kickoff_utc"], "kickoff_utc")
        now = datetime.now(timezone.utc)
        if now >= kickoff:
            return fail("AS_OF_NOT_PREGAME: capture instant is not before "
                        "first pitch")
        sha = git_head_sha(repo_root)
        if sha is None:
            return fail("MODEL_SOURCE_SHA_UNAVAILABLE: git HEAD required "
                        "so the record names its frozen model revision")
        selection = str(spec["selection"]).upper()
        local_date = kickoff.astimezone(
            ZoneInfo("America/New_York")).date().isoformat()
        payload_row = {
            "sport": "MLB", "market": "ML", "side": selection,
            "away": spec["away"], "home": spec["home"],
            "game": f"{spec['away']} @ {spec['home']}",
            "game_date": local_date, "kickoff": spec["kickoff_utc"],
            "price": spec["selection_american"],
            "opposite_odds": spec["opposite_american"],
            "quote_captured_at": spec["selection_captured_at_utc"],
        }
        candidate_p, prediction, production_row = production_probability(
            payload_row, now)
        (existing_p, train_last_final, elo_games, elo_p_home,
         elo_training_population, elo_schedule_provenance) = (
            elo_existing_probability(spec["away"], spec["home"], selection,
                                     kickoff))
        provenance = {
            "quote_source": spec["quote_source"],
            "candidate_model": "artifacts/run_it_full.py Lane A "
                               "(FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED)",
            "candidate_lane": "LANE_A_INDEPENDENT (MARKET_BLIND)",
            "market_anchored_lane": "LANE_B_ANCHORED (MARKET_ANCHORED) — "
                "carried only in prediction.market_anchored, never as "
                "candidate_p",
            "existing_model": "sportsedge/backtest/elo.py EloRatings(MLB) "
                              "walk-forward over completed games before "
                              "kickoff (market-free floor)",
            "existing_model_games": elo_games,
            "existing_model_p_home": elo_p_home,
            "train_last_final_basis": "start time of the most recent "
                "completed game involving either team before kickoff; a "
                "conservative lower bound of that game's final time "
                "(production rating samples contain only games completed "
                "before kickoff)",
            "feature_availability_basis": "live capture: every feature "
                "the production provider consumed was served at or before "
                "as_of_utc, so feature_max_available_at_utc = as_of_utc",
            "production_row": production_row,
            "input_sha256": hashlib.sha256(
                args.input.read_bytes()).hexdigest(),
        }
        record = fc.build_capture_record(
            away=spec["away"], home=spec["home"],
            kickoff_utc=spec["kickoff_utc"], series_id=spec["series_id"],
            market=market, selection=selection, line=spec["line"],
            book=spec["book"],
            selection_american=spec["selection_american"],
            selection_captured_at_utc=spec["selection_captured_at_utc"],
            opposite_american=spec["opposite_american"],
            opposite_captured_at_utc=spec["opposite_captured_at_utc"],
            candidate_p=candidate_p, existing_p=existing_p,
            model_source_sha=sha, as_of_utc=now.isoformat(),
            feature_max_available_at_utc=now.isoformat(),
            train_last_final_at_utc=train_last_final.isoformat(),
            provenance=provenance, prediction=prediction)
        path = fc.write_capture(args.archive_dir, record)
    except fc.CaptureError as exc:
        return fail(str(exc))
    print(json.dumps({
        "status": "CAPTURED", "file": str(path),
        "fixture_id": record["fixture_id"],
        "candidate_p": record["candidate_p"],
        "existing_p": record["existing_p"],
        # Audit surface only: the Elo training population and the
        # schedule finality provenance are reported on stdout, never
        # added to the (frozen) archived record.
        "elo_training_population": elo_training_population,
        "elo_schedule_provenance": elo_schedule_provenance,
        "model_source_sha": record["model_source_sha"],
        "compliance_warnings": record["compliance_warnings"],
    }, indent=2, sort_keys=True))
    if record["compliance_warnings"]:
        print("WARNING: this record will be REJECTED by the strict "
              "evaluator unless the warned condition is cured by a fresh "
              "capture inside the window.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
