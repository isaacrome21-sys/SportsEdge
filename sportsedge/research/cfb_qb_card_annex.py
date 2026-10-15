"""Card annex: CFB QB passing research projections for RUN IT (research only).

WHY THIS EXISTS: CFB player families are registry-BLOCKED by owner
governance, so every CFB prop row on the canonical card terminates at
FAMILY_REGISTRY_NOT_VALIDATED (or FAMILY_MARKET_UNREGISTERED) and the
card shows a CFB user nothing but refusals -- even where a working,
identity-gated research distribution exists underneath the block
(sportsedge.research.cfb_qb_passing_distribution). This module builds
the card's ``cfb_research_projections`` annex: the research READ,
attached beside the refused rows, changing none of them.

HARD INVARIANTS (the annex is a read, never a route around the gate):

  * Terminal states are untouched. The annex copies each ladder
    group's registry refusal from the evaluated card rows; it never
    writes to a row, a candidate list, or the play gate.
  * No prices, no EV, no no-vig. The annex carries a distribution
    SUMMARY only (mean, sd, percentiles) plus provenance. A recursive
    PRICING_KEYS scan runs before the annex is returned; any leak
    replaces the projections with a named section failure.
  * Identity comes ONLY from the runner's Form 2 seam state: the
    per-side evaluator verdicts the pre-pricing stage recorded on the
    staged game (stage["qb_form2_identities"], populated from the
    trusted bundle loader's admitted bundles -- never from an intake
    row). When the seam has no satisfied verdict for the ladder QB's
    team, the annex says so (IDENTITY_NOT_ESTABLISHED_TO_THE_RUNNER,
    with the seam's reason) and emits NO distribution. There is no
    fallback: a gamelog is never name-matched to invent a read.
  * Availability is never upgraded. The evaluator's availability
    label is carried verbatim; Form 2 establishes identity only.
  * The distribution builder's own refusals (insufficient PIT
    history, PIT violations, Illinois, missing identity fields) are
    preserved by name on the annex entry, never softened.

PRIOR-GAME ASSEMBLY (only reached after identity is established):
the QB's gamelog is fetched BY THE EVALUATOR'S RESOLVED ATHLETE ID
(never by name) through the repo's CFB public source discipline
(sportsedge.cfb_public_player_history: the same dated PIT filters and
named-stat decoder the phone path uses), and each game's team pass /
rush attempts are joined from that game's ESPN summary boxscore for
the team the QB played for in that game (event-metadata attribution).
A game that cannot be joined is excluded AND counted with its reason;
assembly produces inputs for the research builder, which applies its
own PIT discipline a second time.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from sportsedge.prepricing.qb_form2_bundle_loader import (
    PIN_VERIFIED as LOADER_PIN_VERIFIED,
)
from sportsedge.prepricing.qb_identity_evidence import (
    STATUS_SATISFIED as FORM2_STATUS_SATISFIED,
)
from sportsedge.registry_gate import PRICING_KEYS
from sportsedge.research.cfb_qb_passing_distribution import (
    QBDistributionError,
    build_qb_passing_distribution,
)

SCHEMA = "SPORTSEDGE_CFB_RESEARCH_PROJECTIONS_V1"
PASSING_MARKET = "PLAYER_PASSING_YARDS"

IDENTITY_ESTABLISHED = "ESTABLISHED_TO_THE_RUNNER_VIA_FORM2"
IDENTITY_NOT_ESTABLISHED = "NOT_ESTABLISHED_TO_THE_RUNNER"

ESPN_SUMMARY = ("https://site.api.espn.com/apis/site/v2/sports/football/"
                "college-football/summary")
MAX_PRIOR_GAMES = 40


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _clock(value, name):
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name}_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Prior-game assembly (athlete-ID keyed; reached only post-identity)
# ---------------------------------------------------------------------------

def assemble_qb_prior_games(*, athlete_id, as_of_utc, kickoff_utc,
                            getter=None):
    """Assemble builder-shaped prior-game records for one resolved QB.

    Returns (records, exclusions). Fetches the athlete's ESPN gamelog
    by ID over the research construction's season window -- the
    current season plus the immediately preceding one (the window the
    family's worked-example evidence was assembled over; older stints
    are staler evidence and stay out) -- applies the source's PIT
    history discipline, and joins each game's team totals from its
    summary boxscore. Games that cannot be fully joined are excluded
    and counted in ``exclusions`` with a named reason; nothing is
    substituted or zero-filled. Fewer than the builder's minimum
    usable games in the window is a named builder refusal downstream,
    never a reason to widen the window silently.
    """
    from sportsedge.cfb_public_player_history import (
        CFBPlayerPublicSource, _gamelog_history, _merge_season_history,
        _response_season_year, _season_year_of, ESPN_GAMELOG)

    as_of = _clock(as_of_utc, "AS_OF")
    kickoff = _clock(kickoff_utc, "FIXTURE_KICKOFF")
    source = CFBPlayerPublicSource(getter=getter)
    base_url = f"{ESPN_GAMELOG}/{athlete_id}/gamelog"
    data = source._fetch(base_url)
    if not isinstance(data, dict):
        return [], [{"event_id": None, "game_date_utc": None,
                     "reason": "QB_GAMELOG_UNAVAILABLE"}]
    current_year = _response_season_year(data) or _season_year_of(kickoff)
    hist, _rejected, _reasons = _gamelog_history(
        data, now=as_of, kickoff=kickoff, season_year=current_year)
    prior = source._fetch(f"{base_url}?season={current_year - 1}")
    if isinstance(prior, dict):
        extra, _r, _why = _gamelog_history(
            prior, now=as_of, kickoff=kickoff,
            season_year=(_response_season_year(prior) or current_year - 1))
        hist = _merge_season_history(hist, extra)
    hist.sort(key=lambda entry: entry[0], reverse=True)

    records, exclusions = [], []
    for day, event_id, stats, _year, _kind, _opp, team_id in hist:
        stamp = {"event_id": event_id, "game_date_utc": day.isoformat()}
        missing = [f for f in ("pass_attempts", "completions", "passing_yards")
                   if stats.get(f) is None]
        if missing:
            exclusions.append({**stamp, "reason":
                               "GAMELOG_STAT_MISSING:" + ",".join(missing)})
            continue
        if not team_id:
            exclusions.append({**stamp, "reason":
                               "GAMELOG_TEAM_ATTRIBUTION_MISSING"})
            continue
        summary = source._fetch(f"{ESPN_SUMMARY}?event={event_id}")
        totals = _boxscore_team_totals(summary, team_id)
        if isinstance(totals, str):
            exclusions.append({**stamp, "reason": totals})
            continue
        team_pass, team_rush, team_name = totals
        records.append({
            "event_id": event_id,
            "game_date_utc": day.isoformat(),
            "qb_team": team_name,
            "qb_attempts": stats["pass_attempts"],
            "qb_completions": stats["completions"],
            "qb_passing_yards": stats["passing_yards"],
            "team_pass_attempts": team_pass,
            "team_rush_attempts": team_rush,
        })
        if len(records) >= MAX_PRIOR_GAMES:
            break
    return records, exclusions


def _boxscore_team_totals(summary, team_id):
    """(team_pass_attempts, team_rush_attempts, team_name) or a reason str."""
    if not isinstance(summary, dict):
        return "TEAM_TOTALS_SUMMARY_UNAVAILABLE"
    teams = ((summary.get("boxscore") or {}).get("teams")) or []
    for entry in teams:
        if not isinstance(entry, dict):
            continue
        team = entry.get("team") or {}
        if str(team.get("id") or "") != str(team_id):
            continue
        stats = {str(s.get("name")): s.get("displayValue")
                 for s in entry.get("statistics") or [] if isinstance(s, dict)}
        comp_att = stats.get("completionAttempts")
        rush_att = stats.get("rushingAttempts")
        if comp_att is None or rush_att is None:
            return "TEAM_TOTALS_STAT_MISSING"
        try:
            team_pass = int(str(comp_att).split("/")[-1].strip())
            team_rush = int(str(rush_att).replace(",", "").strip())
        except (TypeError, ValueError):
            return "TEAM_TOTALS_UNPARSEABLE"
        return team_pass, team_rush, team.get("displayName")
    return "TEAM_TOTALS_TEAM_NOT_IN_BOXSCORE"


# ---------------------------------------------------------------------------
# Annex construction
# ---------------------------------------------------------------------------

def _terminal_state(evaluated_row):
    """Copy the registry refusal from an evaluated (gated) card row."""
    if not isinstance(evaluated_row, Mapping):
        return None
    decision = evaluated_row.get("family_decision") or {}
    return {
        "status": evaluated_row.get("status"),
        "reason": evaluated_row.get("reason"),
        "blocker": evaluated_row.get("blocker"),
        "registry_enforced": bool(evaluated_row.get("registry_enforced")),
        "family": decision.get("market"),
        "family_state": decision.get("state"),
        "family_blocker": decision.get("blocker"),
        "validation_status": decision.get("validation_status"),
        "evaluation_scope": decision.get("evaluation_scope"),
    }


def _loader_blocker(audit):
    """The loader-level reason Form 2 admission produced nothing, if any.

    Speaks only when admission itself failed: no pin supplied (the
    loader audit's pin gate), an unusable archive directory, or a pin
    that did not verify -- including #2278's composite refusal, where
    one bad per-team pin refuses the entire composition. When pins
    VERIFIED and bundles were admitted, admission is not the blocker
    (the consult layer is), and this returns (None, None).
    """
    if not isinstance(audit, Mapping):
        return "FORM2_NOT_CONFIGURED_FOR_RUN", None
    if audit.get("directory_status") not in (None, "OK"):
        return f"FORM2_ARCHIVE_{audit.get('directory_status')}", None
    if audit.get("pin_status") == LOADER_PIN_VERIFIED:
        return None, None
    entries = audit.get("entries") or []
    for entry in entries:
        if entry.get("disposition") == "EXCLUDED" and entry.get("reason"):
            return str(entry["reason"]), entry.get("detail")
    return None, None


def _identity_for_group(*, stage, player_name, loader_audit):
    """Resolve the seam identity state for one ladder QB.

    Returns (state, detail, verdict_or_None, side_or_None). Identity is
    established only when the stage recorded a satisfied Form 2 verdict
    whose resolved athlete IS the ladder's QB.
    """
    verdicts = {}
    if isinstance(stage, Mapping):
        verdicts = stage.get("qb_form2_identities") or {}
    satisfied = {side: v for side, v in verdicts.items()
                 if isinstance(v, Mapping) and v.get("ok")
                 and v.get("status") == FORM2_STATUS_SATISFIED}
    for side, verdict in satisfied.items():
        if _norm(verdict.get("resolved_athlete_name")) == _norm(player_name):
            return IDENTITY_ESTABLISHED, "FORM2_SEAM_VERDICT_MATCHES_LADDER_QB", verdict, side
    if satisfied:
        names = sorted(str(v.get("resolved_athlete_name")) for v in satisfied.values())
        return (IDENTITY_NOT_ESTABLISHED,
                "RESOLVED_QB_DIFFERS_FROM_LADDER_PLAYER:" + ",".join(names),
                None, None)
    failed = {side: v for side, v in verdicts.items() if isinstance(v, Mapping)}
    if failed:
        detail = ";".join(f"{side}:{v.get('status')}" for side, v in sorted(failed.items()))
        return (IDENTITY_NOT_ESTABLISHED, f"FORM2_VERDICT_NOT_SATISFIED:{detail}",
                None, None)
    if stage is None:
        return (IDENTITY_NOT_ESTABLISHED, "NO_STAGED_GAME_FOR_FIXTURE",
                None, None)
    reason, detail = _loader_blocker(loader_audit)
    if reason:
        return (IDENTITY_NOT_ESTABLISHED,
                reason + (f":{detail}" if detail else ""), None, None)
    admitted = (loader_audit or {}).get("admitted_team_ids") or []
    if admitted:
        # Bundles were admitted under verified pins, yet the stage
        # recorded no verdict for either team: the Form 2 consult
        # never fired for this fixture (e.g. a team the injury feed
        # covers is Form 1 territory, where Form 2 is not consulted)
        # or no admitted bundle bound to these teams. Either way the
        # runner holds no seam identity for the ladder QB.
        return (IDENTITY_NOT_ESTABLISHED,
                "FORM2_ADMITTED_BUT_NOT_CONSULTED_FOR_FIXTURE", None, None)
    return (IDENTITY_NOT_ESTABLISHED,
            "FORM2_NOT_CONSULTED_FOR_FIXTURE_TEAMS", None, None)


def _distribution_summary(built, assembly_exclusions):
    dist = built["distribution"]
    return {
        "mean_yards": dist["mean_yards"],
        "sd_yards": dist["sd_yards"],
        "quantiles_yards": dist["quantiles_yards"],
        "paths": dist["paths"],
        "seed": dist["seed"],
        "construction": dist["construction"],
        "prior_game_count": built["inputs"]["prior_game_count"],
        "excluded_post_asof_games": len(built["inputs"]["excluded_post_asof_games"]),
        "excluded_unusable_games": len(built["inputs"]["excluded_unusable_games"]),
        "assembly_excluded_games": assembly_exclusions,
        "chain_means": built["chain_means"],
    }


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def build_cfb_research_projections(*, rows, evaluated, games, stages,
                                   form2_loader_audit=None, as_of_utc,
                                   fetch_enabled=True, getter=None,
                                   prior_games_provider: Optional[Callable] = None):
    """Build the card's CFB research-projection annex.

    ``rows``/``evaluated`` are the runner's expanded intake rows and
    their evaluated card rows (aligned). ``games``/``stages`` are the
    runner's game lines and their pre-pricing stages (aligned). The
    annex is purely additive: it reads seam state and evaluated rows,
    and writes nothing back.
    """
    annex = {
        "schema": SCHEMA,
        "section_label": "RESEARCH_ONLY",
        "content_kind": "RESEARCH_PROJECTION",
        "research_only": True,
        "official_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
        "registry_gate": "UNCHANGED: every annexed family's rows keep "
                         "their registry terminal state; this annex is "
                         "a research read beside the refusal, never a "
                         "priced row, candidate, or play.",
        "projections": [],
        "notes": [
            "Identity is the Form 2 evaluator's verdict as recorded by "
            "the pre-pricing stage; availability labels are carried "
            "verbatim and are never upgraded by this annex.",
            "Distributions are conditional on the identified QB "
            "starting with the role his PIT history shows; the "
            "replacement-pool mixture is not constructed.",
        ],
    }

    # Ladder groups: CFB passing-yard rows by fixture + QB, with the
    # terminal state copied from the evaluated (gated) rows.
    groups = {}
    for row, result in zip(rows, evaluated):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("sport") or "").upper() != "CFB":
            continue
        if str(row.get("market") or "").upper() != PASSING_MARKET:
            continue
        player = str(row.get("player_name") or row.get("label") or "").strip()
        if not player:
            continue
        key = (_norm(row.get("away")), _norm(row.get("home")), _norm(player))
        group = groups.setdefault(key, {
            "away": row.get("away"), "home": row.get("home"),
            "player_name": player, "thresholds": set(),
            "kickoff_utc": row.get("commence_time") or row.get("kickoff"),
            "terminal": _terminal_state(result),
        })
        threshold = row.get("milestone_threshold")
        if threshold is not None:
            try:
                group["thresholds"].add(int(threshold))
            except (TypeError, ValueError):
                pass

    # Staged fixtures by normalized team pair (first stage wins; the
    # runner stages each unique game once and aligns rows to it).
    stage_by_fixture = {}
    for line, stage in zip(games, stages):
        if str(line.get("sport") or "").upper() != "CFB":
            continue
        key = (_norm(line.get("away")), _norm(line.get("home")))
        stage_by_fixture.setdefault(key, stage)

    provider = prior_games_provider
    for key in sorted(groups):
        group = groups[key]
        stage = stage_by_fixture.get((key[0], key[1]))
        state, detail, verdict, side = _identity_for_group(
            stage=stage, player_name=group["player_name"],
            loader_audit=form2_loader_audit)
        entry = {
            "game": f"{group['away']} @ {group['home']}",
            "away": group["away"], "home": group["home"],
            "kickoff_utc": group["kickoff_utc"],
            "market": PASSING_MARKET,
            "player_name": group["player_name"],
            "ladder_thresholds": sorted(group["thresholds"]),
            "terminal_registry_state": group["terminal"],
            "identity": {"state": state, "detail": detail},
            "availability_status": None,
            "distribution": None,
            "distribution_state": "NOT_BUILT",
            "distribution_refusal": None,
        }
        annex["projections"].append(entry)
        if state != IDENTITY_ESTABLISHED:
            entry["distribution_state"] = "NOT_BUILT_IDENTITY_NOT_ESTABLISHED"
            continue
        entry["identity"].update({
            "source": "QB_IDENTITY_EVIDENCE_FORM2_DEPTH_ROSTER_COMPOSITE",
            "team_side": side,
            "team_id": verdict.get("team_id"),
            "event_id": verdict.get("event_id"),
            "athlete_id": verdict.get("resolved_athlete_id"),
            "athlete_name": verdict.get("resolved_athlete_name"),
            "identity_status": verdict.get("status"),
        })
        entry["availability_status"] = verdict.get("availability_status")
        if provider is None and not fetch_enabled:
            entry["distribution_state"] = "NOT_BUILT"
            entry["distribution_refusal"] = (
                "PRIOR_GAME_ASSEMBLY_REQUIRES_FETCH_DISABLED_IN_NO_FETCH_MODE")
            continue
        assemble = provider or (
            lambda **kw: assemble_qb_prior_games(getter=getter, **kw))
        try:
            records, assembly_exclusions = assemble(
                athlete_id=str(verdict.get("resolved_athlete_id")),
                as_of_utc=as_of_utc,
                kickoff_utc=(stage.get("kickoff_utc")
                             if isinstance(stage, Mapping) else None)
                            or group["kickoff_utc"])
        except Exception as exc:  # assembly failure is an annex state, never a card failure
            entry["distribution_state"] = "NOT_BUILT"
            entry["distribution_refusal"] = (
                f"PRIOR_GAME_ASSEMBLY_FAILED:{type(exc).__name__}:{exc}")[:300]
            continue
        identity_record = {
            "status": verdict.get("status"),
            "team_id": verdict.get("team_id"),
            "event_id": verdict.get("event_id"),
            "resolved_athlete_id": verdict.get("resolved_athlete_id"),
            "resolved_athlete_name": verdict.get("resolved_athlete_name"),
            "availability_status": verdict.get("availability_status"),
            "kickoff_utc": (stage.get("kickoff_utc")
                            if isinstance(stage, Mapping) else None)
                           or group["kickoff_utc"],
            "home_team_name": group["home"],
            "away_team_name": group["away"],
        }
        try:
            built = build_qb_passing_distribution(
                identity_record=identity_record, prior_games=records,
                as_of_utc=as_of_utc, thresholds=sorted(group["thresholds"]))
        except QBDistributionError as exc:
            entry["distribution_state"] = "REFUSED"
            entry["distribution_refusal"] = str(exc)
            entry["assembly_excluded_games"] = assembly_exclusions
            continue
        entry["distribution_state"] = "BUILT"
        entry["identity"]["athlete_name"] = built["identity"]["athlete_name"]
        entry["availability_status"] = built["identity"]["availability_status"]
        entry["starter_certainty"] = built["starter_certainty"]
        entry["validation_status"] = built["validation_status"]
        entry["distribution"] = _distribution_summary(built, assembly_exclusions)

    # Defense in depth: the annex must never carry a pricing-shaped
    # key. By construction it cannot; if that ever changes, fail the
    # section closed rather than leak a price-shaped field onto a card
    # whose rows the registry refused.
    leaked = set(_walk_keys(annex)) & set(PRICING_KEYS)
    if leaked:
        annex["projections"] = []
        annex["section_failure"] = (
            "ANNEX_PRICING_KEY_LEAK:" + ",".join(sorted(leaked)))
    return annex


__all__ = [
    "SCHEMA", "IDENTITY_ESTABLISHED", "IDENTITY_NOT_ESTABLISHED",
    "assemble_qb_prior_games", "build_cfb_research_projections",
]
