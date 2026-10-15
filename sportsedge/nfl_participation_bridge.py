"""NFL participation/role evidence bridge for player-prop research.

Closes the gap named by ``nfl_phone_player_pricing``: a player's game log
proves historical performance, never tonight's role.  That phone path's only
evidence is the ESPN gamelog, so it stamps
``STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG`` unconditionally and demotes every
candidate to the watchlist.  The evidence that satisfies the stamp is a
participation verdict for the same (game, team, player) identity built from
sources INDEPENDENT of the game log:

* starting-QB identity from timestamped nflverse depth charts (the same PIT
  snapshot discipline as ``sports.nfl.live_role_source``),
* availability from nflverse injury reports known by the cutoff
  (``date_modified`` point-in-time, again mirroring ``live_role_source``),
* game-day confirmation from an official inactive snapshot published
  before the cutoff whose COMPLETENESS is provable (see
  :func:`_inactive_scan`): only a source-complete, exact game/team
  snapshot supports the negative inference "not listed => dressed".
  Loose designation rows are positive evidence only -- a candidate
  found on any of them is OUT -- and can never confirm anyone.  When
  inactive evidence exists for the game/team but no complete snapshot
  does, the verdict is ``UNKNOWN / INACTIVES_COMPLETENESS_UNVERIFIED``
  (integrator audit B1 on PR #2274).

The state vocabulary mirrors STARTER_CERTAINTY_V1: the state of a slot is a
pure function of evidence with ``observed_at <= cutoff``; later evidence is
invisible and counted in ``excluded_evidence``.  States are
``CONFIRMED_STARTER`` / ``PROJECTED_STARTER`` / ``QUESTIONABLE`` / ``OUT`` /
``UNKNOWN``, each with a subclass naming the decision-table row that fired.

The connector at the bottom wires a CONFIRMED verdict into the coherent prop
runner (``nfl_coherent_prop_runner``) so QB passing yards can be produced as
a research distribution (a survival ladder over the runner's own paths).
Any other state refuses BY NAME.  Research only: this module grants no
Model_P, Truth Gate, staking, promotion, or OFFICIAL authority, and it does
not change any existing pricer or the runner's eligibility labels.

Skill positions (RB/WR/TE) are graded by the same evidence discipline via
:func:`assess_skill_participation`: the candidate is the named player
himself (not a slot), his chart position/rank is reported, and the
confirmed tier splits into ``CONFIRMED_STARTER`` (game-day active, chart
rank 1 at his position) and ``CONFIRMED_ACTIVE`` (game-day active,
rotation rank) -- both mean the player's participation is verified from
gamelog-independent evidence; projected tiers never confirm.  The phone
pricer (``nfl_phone_player_pricing``) consumes these verdicts through
:func:`require_confirmed_qb_role` / :func:`require_confirmed_skill_role`:
only a confirmed-tier verdict lifts its
``STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG`` stamp, and every other outcome
keeps the stamp with the gate's named refusal recorded.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sportsedge.nfl_coherent_prop_runner import run_coherent_prop_estimates
from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.live_role_source import (
    _latest_depth_snapshot,
    _pit_injury_statuses,
    _player_id,
    _rank,
    _team,
    build_live_team_model,
)


class NFLParticipationError(ValueError):
    """Named fail-closed refusal from the participation bridge."""


# A depth-chart snapshot older than this at the cutoff cannot support a
# role verdict: charts are republished through the week, so a week-old
# chart is stale evidence, not a current role.  Declared constant; the
# caller may tighten it, never silently widen it per-call site.
DEFAULT_MAX_DEPTH_AGE_HOURS = 96.0

STATE_CONFIRMED = "CONFIRMED_STARTER"
STATE_CONFIRMED_ACTIVE = "CONFIRMED_ACTIVE"
STATE_PROJECTED = "PROJECTED_STARTER"
STATE_PROJECTED_ROTATION = "PROJECTED_ROTATION"
STATE_QUESTIONABLE = "QUESTIONABLE"
STATE_OUT = "OUT"
STATE_UNKNOWN = "UNKNOWN"

# The confirmed tier: a completeness-proven official inactive snapshot
# for the game/team is published and the player is NOT on it.
# CONFIRMED_STARTER additionally requires chart rank 1 at the player's
# position (the QB slot, an RB1, a WR1, a TE1); a dressed rotation
# player is CONFIRMED_ACTIVE.  Only this tier satisfies a participation
# gate; projected/questionable/out/unknown never do.
CONFIRMED_STATES = frozenset({STATE_CONFIRMED, STATE_CONFIRMED_ACTIVE})

# Completeness contract for official inactive snapshots (audit B1).
# An official game-day inactive list names the team's FULL inactive set
# (the players not dressing from the game-day roster); it is never a
# one-name note, so a snapshot shorter than this floor cannot be the
# complete official list and the negative inference is unavailable
# from it.  Declared conservative constant: failing closed (UNKNOWN)
# is the safe direction for a genuinely short list.
MIN_OFFICIAL_INACTIVE_SNAPSHOT_ROWS = 5
# Official inactives are published on game day, shortly before kickoff.
# A list claiming to be this game's inactives published longer than
# this before kickoff is not a credible game-day publication (a prior
# game's list cannot be re-bound to this fixture), so its completeness
# is unverified.
INACTIVES_SNAPSHOT_MAX_LEAD_HOURS = 24.0


def _utc(value: Any, field: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NFLParticipationError(f"{field}_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLParticipationError(f"{field}_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _count_excluded(depth_rows, injury_rows, inactive_rows, cutoff,
                    inactive_snapshots=()) -> int:
    """Evidence after the cutoff is invisible; count it for audit."""
    excluded = 0
    for raw in depth_rows:
        if raw.get("dt") in (None, ""):
            continue
        try:
            if _utc(raw.get("dt"), "depth dt") > cutoff:
                excluded += 1
        except NFLParticipationError:
            continue
    for raw in injury_rows:
        if raw.get("date_modified") in (None, ""):
            continue
        try:
            if _utc(raw.get("date_modified"), "injury date_modified") > cutoff:
                excluded += 1
        except NFLParticipationError:
            continue
    for raw in inactive_rows:
        if raw.get("published_at") in (None, ""):
            continue
        try:
            if _utc(raw.get("published_at"), "inactive published_at") > cutoff:
                excluded += 1
        except NFLParticipationError:
            continue
    for raw in inactive_snapshots:
        if not isinstance(raw, Mapping) or raw.get("published_at") in (None, ""):
            continue
        try:
            if _utc(raw.get("published_at"), "inactive published_at") > cutoff:
                excluded += 1
        except NFLParticipationError:
            continue
    return excluded


def _latest_snapshot_by_team(depth_rows, *, as_of):
    """Latest depth snapshot per team at the cutoff (switch detection)."""
    out: dict[str, tuple[datetime, list[Mapping[str, Any]]]] = {}
    teams = {_team(r.get("team") or r.get("club_code")) for r in depth_rows}
    for team in teams:
        if not team:
            continue
        try:
            out[team] = _latest_depth_snapshot(depth_rows, team=team, as_of=as_of)
        except NFLContextError:
            continue
    return out


def _qb1_of(snapshot_rows) -> list[Mapping[str, Any]]:
    return [
        row for row in snapshot_rows
        if str(row.get("pos_abb") or "").strip().upper() == "QB"
        and _rank(row) == 1 and _player_id(row)
    ]


def _snapshot_player_ids(snapshot) -> list[str] | None:
    """Validated player-id list of one snapshot object, or None.

    A complete official list is a list of distinct, non-empty player
    ids meeting the declared floor; anything else (not a list, too
    short, duplicates, non-string/empty entries) is not a complete
    list and proves nothing by absence.
    """
    ids = snapshot.get("player_ids")
    if not isinstance(ids, (list, tuple)):
        return None
    out = [str(v).strip() for v in ids]
    if len(out) < MIN_OFFICIAL_INACTIVE_SNAPSHOT_ROWS:
        return None
    if any(not v for v in out) or len(set(out)) != len(out):
        return None
    return out


def _inactive_scan(inactive_rows, inactive_snapshots, *, game_id, team_id,
                   candidate_id, kickoff, cutoff):
    """Official-inactive evidence scan for one candidate, <= cutoff only.

    Returns a dict with:

    * ``candidate_inactive`` -- POSITIVE evidence only: the candidate
      is named inactive on any loose designation row for this
      game/team published by the cutoff, or in any matching snapshot's
      player list.  Positive evidence is sound even from a partial
      list, so loose rows can mark a player OUT -- and nothing else.
    * ``evidence_present`` -- some inactive evidence for this game/team
      was published by the cutoff (a parseable loose row or snapshot).
    * ``complete_published`` -- the NEGATIVE inference is available: a
      source-complete official snapshot for exactly this game/team was
      published by the cutoff and within the game-day lead window
      before kickoff, its player list validates (see
      :func:`_snapshot_player_ids`), and it is not contradicted by a
      conflicting same-instant snapshot.  Only under this flag may an
      unlisted candidate be read as dressed (CONFIRMED tier).  A
      truncated, malformed, wrong-game, wrong-team, future-dated,
      stale or mixed snapshot NEVER sets it (audit B1).

    Rows/snapshots from other games/teams, published after the cutoff,
    or with unparseable timestamps are invisible here (post-cutoff
    evidence is counted as excluded by the callers' audit).
    """
    result = {"candidate_inactive": False, "evidence_present": False,
              "complete_published": False}
    if game_id is None:
        return result
    for raw in inactive_rows:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("game_id") or "") != str(game_id):
            continue
        if _team(raw.get("team")) != team_id:
            continue
        if raw.get("published_at") in (None, ""):
            continue
        try:
            published_at = _utc(raw.get("published_at"),
                                "inactive published_at")
        except NFLParticipationError:
            continue  # unplaceable in time: not evidence
        if published_at > cutoff:
            continue
        result["evidence_present"] = True
        if _player_id(raw) == candidate_id and str(
                raw.get("status") or "").strip().upper() == "INACTIVE":
            result["candidate_inactive"] = True
    valid: dict[datetime, set] = {}
    for raw in inactive_snapshots:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("game_id") or "") != str(game_id):
            continue
        if _team(raw.get("team")) != team_id:
            continue
        if raw.get("published_at") in (None, ""):
            continue
        try:
            published_at = _utc(raw.get("published_at"),
                                "inactive published_at")
        except NFLParticipationError:
            continue
        if published_at > cutoff:
            continue
        result["evidence_present"] = True
        ids = raw.get("player_ids")
        if isinstance(ids, (list, tuple)) and candidate_id in {
                str(v).strip() for v in ids}:
            result["candidate_inactive"] = True
        lead = (kickoff - published_at).total_seconds() / 3600.0
        if lead < 0.0 or lead > INACTIVES_SNAPSHOT_MAX_LEAD_HOURS:
            continue  # not a credible game-day publication for this game
        validated = _snapshot_player_ids(raw)
        if validated is None:
            continue
        valid.setdefault(published_at, set()).add(tuple(sorted(validated)))
    if valid:
        # A list of any length can be truncated. Matching game/team,
        # plausible publication time, and unique IDs prove only that
        # these players were named inactive; they do NOT prove that
        # every inactive was named. Even a sole latest snapshot or an
        # inline 'complete' flag is untrusted negative evidence.
        #
        # Fail closed until a separately authenticated, content-bound
        # source-completeness receipt is verified by the intake layer
        # and plumbed through a dedicated trusted contract. Never infer
        # CONFIRMED_* from snapshot absence alone.
        result["complete_published"] = False
    return result


def assess_qb_participation(
    *,
    team: str,
    depth_rows: Sequence[Mapping[str, Any]],
    injury_rows: Sequence[Mapping[str, Any]] = (),
    inactive_rows: Sequence[Mapping[str, Any]] = (),
    inactive_snapshots: Sequence[Mapping[str, Any]] = (),
    game_id: str | None = None,
    target_season: int,
    target_week: int,
    kickoff: Any,
    as_of: Any,
    expected_player_id: str | None = None,
    max_depth_age_hours: float = DEFAULT_MAX_DEPTH_AGE_HOURS,
) -> dict[str, Any]:
    """Grade the starting-QB slot for one team as of a pregame cutoff.

    First-match decision table (all evidence <= as_of):

    1. no depth snapshot <= cutoff        -> UNKNOWN / DEPTH_SNAPSHOT_MISSING
    2. snapshot older than max age        -> UNKNOWN / DEPTH_SNAPSHOT_STALE
    3. snapshot QB1 count != 1            -> UNKNOWN / DEPTH_QB_AMBIGUOUS
    4. candidate on official inactives    -> OUT / OFFICIAL_INACTIVE
    5. injury status OUT or INACTIVE      -> OUT / INJURY_REPORT_OUT
    6. COMPLETE inactive snapshot         -> CONFIRMED_STARTER / GAMEDAY_ACTIVE
       published, candidate not on it       (game-day active supersedes
                                             earlier-week designations)
    6b. inactive evidence exists but      -> UNKNOWN /
        completeness unproven                INACTIVES_COMPLETENESS_UNVERIFIED
    7. injury status DOUBTFUL            -> QUESTIONABLE / INJURY_DOUBTFUL
    8. injury status QUESTIONABLE         -> QUESTIONABLE / INJURY_QUESTIONABLE
    9. otherwise (rank-1, no adverse      -> PROJECTED_STARTER /
       designation, inactives unpublished)   DEPTH_QB1_NO_ADVERSE_DESIGNATION
    """
    team_id = _team(team)
    kick = _utc(kickoff, "kickoff")
    cutoff = _utc(as_of, "as_of")
    if cutoff >= kick:
        raise NFLParticipationError("NFL_PARTICIPATION_CUTOFF_NOT_PREGAME")

    verdict: dict[str, Any] = {
        "team": team_id,
        "game_id": game_id,
        "as_of": cutoff.isoformat(),
        "kickoff": kick.isoformat(),
        "expected_player_id": expected_player_id,
        "excluded_evidence": _count_excluded(
            depth_rows, injury_rows, inactive_rows, cutoff,
            inactive_snapshots),
        "max_depth_age_hours": float(max_depth_age_hours),
    }

    def _no_inactives() -> dict[str, Any]:
        return {"injury_status": None, "inactives_published": False,
                "inactives_evidence_present": False,
                "inactives_completeness": "NOT_PUBLISHED",
                "candidate_inactive": False}

    try:
        depth_at, snapshot = _latest_depth_snapshot(
            depth_rows, team=team_id, as_of=cutoff)
    except NFLContextError:
        verdict.update({
            "state": STATE_UNKNOWN, "subclass": "DEPTH_SNAPSHOT_MISSING",
            "candidate_id": None, "candidate_name": None,
            "depth_as_of": None, "depth_age_hours": None,
            **_no_inactives(),
        })
        return verdict

    age_hours = (cutoff - depth_at).total_seconds() / 3600.0
    verdict["depth_as_of"] = depth_at.isoformat()
    verdict["depth_age_hours"] = age_hours
    if age_hours > float(max_depth_age_hours):
        verdict.update({
            "state": STATE_UNKNOWN, "subclass": "DEPTH_SNAPSHOT_STALE",
            "candidate_id": None, "candidate_name": None,
            **_no_inactives(),
        })
        return verdict

    qb1 = _qb1_of(snapshot)
    if len(qb1) != 1:
        verdict.update({
            "state": STATE_UNKNOWN, "subclass": "DEPTH_QB_AMBIGUOUS",
            "candidate_id": None, "candidate_name": None,
            **_no_inactives(),
        })
        return verdict

    candidate = qb1[0]
    candidate_id = _player_id(candidate)
    verdict["candidate_id"] = candidate_id
    verdict["candidate_name"] = str(
        candidate.get("player_name") or candidate_id).strip()

    statuses = _pit_injury_statuses(
        injury_rows, team=team_id, target_season=int(target_season),
        target_week=int(target_week), as_of=cutoff)
    injury_status = statuses.get(candidate_id)
    verdict["injury_status"] = injury_status

    scan = _inactive_scan(
        inactive_rows, inactive_snapshots, game_id=game_id,
        team_id=team_id, candidate_id=candidate_id, kickoff=kick,
        cutoff=cutoff)
    verdict["inactives_published"] = scan["complete_published"]
    verdict["inactives_evidence_present"] = scan["evidence_present"]
    verdict["inactives_completeness"] = (
        "VERIFIED_COMPLETE" if scan["complete_published"]
        else "UNVERIFIED" if scan["evidence_present"] else "NOT_PUBLISHED")
    verdict["candidate_inactive"] = scan["candidate_inactive"]

    if scan["candidate_inactive"]:
        verdict.update({"state": STATE_OUT, "subclass": "OFFICIAL_INACTIVE"})
    elif injury_status in {"OUT", "INACTIVE"}:
        verdict.update({"state": STATE_OUT, "subclass": "INJURY_REPORT_OUT"})
    elif scan["complete_published"]:
        verdict.update({
            "state": STATE_CONFIRMED, "subclass": "GAMEDAY_ACTIVE"})
    elif scan["evidence_present"]:
        verdict.update({
            "state": STATE_UNKNOWN,
            "subclass": "INACTIVES_COMPLETENESS_UNVERIFIED"})
    elif injury_status == "DOUBTFUL":
        verdict.update({
            "state": STATE_QUESTIONABLE, "subclass": "INJURY_DOUBTFUL"})
    elif injury_status == "QUESTIONABLE":
        verdict.update({
            "state": STATE_QUESTIONABLE, "subclass": "INJURY_QUESTIONABLE"})
    else:
        verdict.update({
            "state": STATE_PROJECTED,
            "subclass": "DEPTH_QB1_NO_ADVERSE_DESIGNATION"})
    return verdict


def _gate_refusal(verdict: Mapping[str, Any]) -> NFLParticipationError:
    state = verdict.get("state")
    subclass = verdict.get("subclass")
    if subclass == "DEPTH_SNAPSHOT_STALE":
        return NFLParticipationError("NFL_PARTICIPATION_EVIDENCE_STALE")
    if subclass == "DEPTH_SNAPSHOT_MISSING":
        return NFLParticipationError("NFL_PARTICIPATION_DEPTH_SNAPSHOT_MISSING")
    if subclass == "DEPTH_QB_AMBIGUOUS":
        return NFLParticipationError("NFL_PARTICIPATION_DEPTH_QB_AMBIGUOUS")
    if subclass == "INACTIVES_COMPLETENESS_UNVERIFIED":
        return NFLParticipationError("INACTIVES_COMPLETENESS_UNVERIFIED")
    if state == STATE_OUT:
        return NFLParticipationError(f"NFL_QB_ROLE_OUT:{subclass}")
    return NFLParticipationError(
        f"NFL_QB_ROLE_NOT_CONFIRMED:{state}:{subclass}")


def _assert_identity_binding(
    verdict: Mapping[str, Any],
    *,
    depth_rows: Sequence[Mapping[str, Any]],
    as_of: datetime,
) -> None:
    """Detect a team switch / identity divergence for the expected QB.

    If the caller expected a specific player and the slot's candidate is
    someone else, refuse by name: TEAM_MISMATCH when the expected player
    is the current QB1 of a DIFFERENT team (he switched teams), otherwise
    a plain identity-binding mismatch.
    """
    expected = verdict.get("expected_player_id")
    if not expected:
        return
    if verdict.get("candidate_id") == expected:
        return
    for other_team, (_stamp, rows) in _latest_snapshot_by_team(
            depth_rows, as_of=as_of).items():
        if other_team == verdict.get("team"):
            continue
        if any(_player_id(r) == expected for r in _qb1_of(rows)):
            raise NFLParticipationError(
                f"NFL_PARTICIPATION_TEAM_MISMATCH:{expected}:{other_team}")
    raise NFLParticipationError(
        f"NFL_PARTICIPATION_IDENTITY_BINDING_MISMATCH:{expected}")


def require_confirmed_qb_role(
    verdict: Mapping[str, Any],
    *,
    depth_rows: Sequence[Mapping[str, Any]],
    as_of: Any,
) -> dict[str, Any]:
    """Gate a QB verdict for a consumer (e.g. the phone pricer).

    Returns the verdict unchanged when it is CONFIRMED_STARTER for the
    expected player; raises the bridge's named refusal otherwise
    (identity binding first, so a team switch names TEAM_MISMATCH rather
    than a generic not-confirmed).
    """
    _assert_identity_binding(
        verdict, depth_rows=depth_rows, as_of=_utc(as_of, "as_of"))
    if verdict.get("state") != STATE_CONFIRMED:
        raise _gate_refusal(verdict)
    return dict(verdict)


def assess_skill_participation(
    *,
    team: str,
    player_id: str,
    depth_rows: Sequence[Mapping[str, Any]],
    injury_rows: Sequence[Mapping[str, Any]] = (),
    inactive_rows: Sequence[Mapping[str, Any]] = (),
    inactive_snapshots: Sequence[Mapping[str, Any]] = (),
    game_id: str | None = None,
    target_season: int,
    target_week: int,
    kickoff: Any,
    as_of: Any,
    position: str | None = None,
    max_depth_age_hours: float = DEFAULT_MAX_DEPTH_AGE_HOURS,
) -> dict[str, Any]:
    """Grade one skill player's (RB/WR/TE) participation as of a cutoff.

    Same evidence discipline as the QB slot machine, but the candidate is
    the named player: his own row in the team's latest PIT depth snapshot
    supplies chart position and rank.  First-match decision table (all
    evidence <= as_of):

    1. no depth snapshot <= cutoff        -> UNKNOWN / DEPTH_SNAPSHOT_MISSING
    2. snapshot older than max age        -> UNKNOWN / DEPTH_SNAPSHOT_STALE
    3a. player fronts ANOTHER team's      -> UNKNOWN / PLAYER_ON_OTHER_TEAM_CHART
        chart (he switched teams; the        (gate: TEAM_MISMATCH)
        gate refuses by that name)
    3b. player on no chart at all         -> UNKNOWN / PLAYER_NOT_ON_DEPTH_CHART
    4. candidate on official inactives    -> OUT / OFFICIAL_INACTIVE
    5. injury status OUT or INACTIVE      -> OUT / INJURY_REPORT_OUT
    6. COMPLETE inactive snapshot         -> CONFIRMED_STARTER /
       published, candidate not on it        GAMEDAY_ACTIVE_STARTER (rank 1)
                                             CONFIRMED_ACTIVE /
                                             GAMEDAY_ACTIVE_ROTATION (rank > 1
                                             or unranked)
    6b. inactive evidence exists but      -> UNKNOWN /
        completeness unproven                INACTIVES_COMPLETENESS_UNVERIFIED
    7. injury status DOUBTFUL             -> QUESTIONABLE / INJURY_DOUBTFUL
    8. injury status QUESTIONABLE         -> QUESTIONABLE / INJURY_QUESTIONABLE
    9. otherwise (on chart, no adverse    -> PROJECTED_STARTER /
       designation, inactives unpublished)   DEPTH_STARTER_NO_ADVERSE_DESIGNATION
                                             (rank 1) or PROJECTED_ROTATION /
                                             DEPTH_ROTATION_NO_ADVERSE_DESIGNATION
    """
    team_id = _team(team)
    pid = str(player_id or "").strip()
    if not pid:
        raise NFLParticipationError("NFL_PARTICIPATION_PLAYER_ID_REQUIRED")
    kick = _utc(kickoff, "kickoff")
    cutoff = _utc(as_of, "as_of")
    if cutoff >= kick:
        raise NFLParticipationError("NFL_PARTICIPATION_CUTOFF_NOT_PREGAME")

    verdict: dict[str, Any] = {
        "team": team_id,
        "game_id": game_id,
        "as_of": cutoff.isoformat(),
        "kickoff": kick.isoformat(),
        "player_id": pid,
        "expected_player_id": pid,
        "position": (str(position).strip().upper() or None) if position else None,
        "excluded_evidence": _count_excluded(
            depth_rows, injury_rows, inactive_rows, cutoff,
            inactive_snapshots),
        "max_depth_age_hours": float(max_depth_age_hours),
    }

    def _unknown(subclass: str, **extra: Any) -> dict[str, Any]:
        verdict.update({
            "state": STATE_UNKNOWN, "subclass": subclass,
            "candidate_id": None, "candidate_name": None,
            "chart_position": None, "chart_rank": None,
            "injury_status": None, "inactives_published": False,
            "inactives_evidence_present": False,
            "inactives_completeness": "NOT_PUBLISHED",
            "candidate_inactive": False,
        })
        verdict.update(extra)
        return verdict

    try:
        depth_at, snapshot = _latest_depth_snapshot(
            depth_rows, team=team_id, as_of=cutoff)
    except NFLContextError:
        return _unknown("DEPTH_SNAPSHOT_MISSING", depth_as_of=None,
                        depth_age_hours=None)

    age_hours = (cutoff - depth_at).total_seconds() / 3600.0
    verdict["depth_as_of"] = depth_at.isoformat()
    verdict["depth_age_hours"] = age_hours
    if age_hours > float(max_depth_age_hours):
        return _unknown("DEPTH_SNAPSHOT_STALE")

    chart_rows = [r for r in snapshot if _player_id(r) == pid]
    if not chart_rows:
        other_team = None
        for other, (_stamp, rows) in sorted(
                _latest_snapshot_by_team(depth_rows, as_of=cutoff).items()):
            if other == team_id:
                continue
            if any(_player_id(r) == pid for r in rows):
                other_team = other
                break
        if other_team is not None:
            return _unknown("PLAYER_ON_OTHER_TEAM_CHART",
                            other_team=other_team)
        return _unknown("PLAYER_NOT_ON_DEPTH_CHART")

    def _row_key(row):
        rank = _rank(row)
        pos = str(row.get("pos_abb") or "").strip().upper()
        return (0 if verdict["position"] and pos == verdict["position"] else 1,
                0 if rank is not None else 1,
                rank if rank is not None else 999)

    candidate = sorted(chart_rows, key=_row_key)[0]
    chart_position = str(candidate.get("pos_abb") or "").strip().upper() or None
    chart_rank = _rank(candidate)
    verdict["candidate_id"] = pid
    verdict["candidate_name"] = str(
        candidate.get("player_name") or pid).strip()
    verdict["chart_position"] = chart_position
    verdict["chart_rank"] = chart_rank
    verdict["other_team"] = None

    statuses = _pit_injury_statuses(
        injury_rows, team=team_id, target_season=int(target_season),
        target_week=int(target_week), as_of=cutoff)
    injury_status = statuses.get(pid)
    verdict["injury_status"] = injury_status

    scan = _inactive_scan(
        inactive_rows, inactive_snapshots, game_id=game_id,
        team_id=team_id, candidate_id=pid, kickoff=kick, cutoff=cutoff)
    verdict["inactives_published"] = scan["complete_published"]
    verdict["inactives_evidence_present"] = scan["evidence_present"]
    verdict["inactives_completeness"] = (
        "VERIFIED_COMPLETE" if scan["complete_published"]
        else "UNVERIFIED" if scan["evidence_present"] else "NOT_PUBLISHED")
    verdict["candidate_inactive"] = scan["candidate_inactive"]

    starter = chart_rank == 1
    if scan["candidate_inactive"]:
        verdict.update({"state": STATE_OUT, "subclass": "OFFICIAL_INACTIVE"})
    elif injury_status in {"OUT", "INACTIVE"}:
        verdict.update({"state": STATE_OUT, "subclass": "INJURY_REPORT_OUT"})
    elif scan["complete_published"]:
        if starter:
            verdict.update({
                "state": STATE_CONFIRMED,
                "subclass": "GAMEDAY_ACTIVE_STARTER"})
        else:
            verdict.update({
                "state": STATE_CONFIRMED_ACTIVE,
                "subclass": "GAMEDAY_ACTIVE_ROTATION"})
    elif scan["evidence_present"]:
        verdict.update({
            "state": STATE_UNKNOWN,
            "subclass": "INACTIVES_COMPLETENESS_UNVERIFIED"})
    elif injury_status == "DOUBTFUL":
        verdict.update({
            "state": STATE_QUESTIONABLE, "subclass": "INJURY_DOUBTFUL"})
    elif injury_status == "QUESTIONABLE":
        verdict.update({
            "state": STATE_QUESTIONABLE, "subclass": "INJURY_QUESTIONABLE"})
    elif starter:
        verdict.update({
            "state": STATE_PROJECTED,
            "subclass": "DEPTH_STARTER_NO_ADVERSE_DESIGNATION"})
    else:
        verdict.update({
            "state": STATE_PROJECTED_ROTATION,
            "subclass": "DEPTH_ROTATION_NO_ADVERSE_DESIGNATION"})
    return verdict


def _skill_gate_refusal(verdict: Mapping[str, Any]) -> NFLParticipationError:
    state = verdict.get("state")
    subclass = verdict.get("subclass")
    if subclass == "DEPTH_SNAPSHOT_STALE":
        return NFLParticipationError("NFL_PARTICIPATION_EVIDENCE_STALE")
    if subclass == "DEPTH_SNAPSHOT_MISSING":
        return NFLParticipationError("NFL_PARTICIPATION_DEPTH_SNAPSHOT_MISSING")
    if subclass == "PLAYER_ON_OTHER_TEAM_CHART":
        return NFLParticipationError(
            "NFL_PARTICIPATION_TEAM_MISMATCH:"
            f"{verdict.get('player_id')}:{verdict.get('other_team')}")
    if subclass == "PLAYER_NOT_ON_DEPTH_CHART":
        return NFLParticipationError(
            "NFL_PARTICIPATION_PLAYER_NOT_ON_DEPTH_CHART:"
            f"{verdict.get('player_id')}")
    if subclass == "INACTIVES_COMPLETENESS_UNVERIFIED":
        return NFLParticipationError("INACTIVES_COMPLETENESS_UNVERIFIED")
    if state == STATE_OUT:
        return NFLParticipationError(f"NFL_SKILL_ROLE_OUT:{subclass}")
    return NFLParticipationError(
        f"NFL_SKILL_ROLE_NOT_CONFIRMED:{state}:{subclass}")


def require_confirmed_skill_role(
    verdict: Mapping[str, Any],
) -> dict[str, Any]:
    """Gate a skill verdict: only the confirmed tier passes.

    Game-day active is the confirmation -- CONFIRMED_STARTER (chart
    rank 1) and CONFIRMED_ACTIVE (rotation) both pass, mirroring the QB
    rule that only CONFIRMED lifts/stamps.  Every other state raises the
    named refusal.
    """
    if verdict.get("state") in CONFIRMED_STATES:
        return dict(verdict)
    raise _skill_gate_refusal(verdict)


def _prior_stat_rows(rows, *, target_season, target_week):
    out = []
    for raw in rows:
        try:
            season = int(float(raw.get("season")))
            week = int(float(raw.get("week")))
        except (TypeError, ValueError):
            continue
        if str(raw.get("season_type") or "REG").strip().upper() != "REG":
            continue
        if season > target_season or (
                season == target_season and week >= target_week):
            continue
        row = dict(raw)
        row["_season"] = season
        row["_week"] = week
        out.append(row)
    return out


def opportunity_shares(
    *,
    player_id: str,
    team: str,
    player_stat_rows: Sequence[Mapping[str, Any]],
    target_season: int,
    target_week: int,
    snap_rows: Sequence[Mapping[str, Any]] = (),
    lookback_games: int = 8,
) -> dict[str, Any]:
    """Opportunity-share priors from strictly-prior evidence only.

    target/carry shares come from nflverse weekly player stats (the same
    strictly-prior window discipline as the role builder); snap share from
    nflverse snap counts when rows are supplied.  Route share has NO
    consumed source (routes-run is not in any repo feed) and is reported
    UNKNOWN, never estimated from targets.  Nothing here is backfilled
    from the player's current-game log: every window ends before the
    target week.
    """
    team_id = _team(team)
    prior = _prior_stat_rows(
        player_stat_rows, target_season=int(target_season),
        target_week=int(target_week))
    team_rows = [
        r for r in prior
        if _team(r.get("recent_team") or r.get("team")) == team_id]
    team_weeks = sorted({(r["_season"], r["_week"]) for r in team_rows})
    window = set(team_weeks[-int(lookback_games):]) if team_weeks else set()

    def _sum(rows, field):
        total = 0.0
        for r in rows:
            if (r["_season"], r["_week"]) not in window:
                continue
            try:
                total += float(r.get(field) or 0)
            except (TypeError, ValueError):
                continue
        return total

    def _share(field):
        team_total = _sum(team_rows, field)
        if team_total <= 0:
            return {"value": None, "status": "UNKNOWN",
                    "reason": f"NO_PRIOR_TEAM_{field.upper()}",
                    "basis": "NFLVERSE_STATS_PLAYER_STRICTLY_PRIOR"}
        mine = _sum(
            [r for r in team_rows
             if str(r.get("player_id") or "").strip() == str(player_id)],
            field)
        return {"value": mine / team_total, "status": "MEASURED_PRIOR",
                "basis": "NFLVERSE_STATS_PLAYER_STRICTLY_PRIOR"}

    snap_share: dict[str, Any] = {
        "value": None, "status": "UNKNOWN",
        "reason": "NO_SNAP_ROWS_SUPPLIED",
        "basis": "NFLVERSE_SNAP_COUNTS_STRICTLY_PRIOR"}
    pcts = []
    for raw in snap_rows:
        if str(raw.get("player_id") or "").strip() != str(player_id):
            continue
        try:
            season = int(float(raw.get("season")))
            week = int(float(raw.get("week")))
        except (TypeError, ValueError):
            continue
        if season > target_season or (
                season == target_season and week >= target_week):
            continue
        pct = raw.get("offense_pct")
        if pct in (None, ""):
            continue
        try:
            value = float(pct)
        except (TypeError, ValueError):
            continue
        if value > 1.0:
            value /= 100.0
        if 0.0 <= value <= 1.0:
            pcts.append(value)
    if pcts:
        snap_share = {"value": sum(pcts) / len(pcts),
                      "status": "MEASURED_PRIOR",
                      "basis": "NFLVERSE_SNAP_COUNTS_STRICTLY_PRIOR"}

    return {
        "player_id": str(player_id),
        "team": team_id,
        "window_team_games": len(window),
        "target_share": _share("targets"),
        "carry_share": _share("carries"),
        "snap_share": snap_share,
        "route_share": {"value": None, "status": "UNKNOWN",
                        "reason": "NO_ROUTE_SOURCE_CONSUMED",
                        "basis": None},
    }


def skill_role_assessment(
    *,
    team: str,
    player_id: str,
    depth_rows: Sequence[Mapping[str, Any]],
    player_stat_rows: Sequence[Mapping[str, Any]] = (),
    injury_rows: Sequence[Mapping[str, Any]] = (),
    inactive_rows: Sequence[Mapping[str, Any]] = (),
    inactive_snapshots: Sequence[Mapping[str, Any]] = (),
    snap_rows: Sequence[Mapping[str, Any]] = (),
    game_id: str | None = None,
    target_season: int,
    target_week: int,
    kickoff: Any,
    as_of: Any,
    position: str | None = None,
    max_depth_age_hours: float = DEFAULT_MAX_DEPTH_AGE_HOURS,
) -> dict[str, Any]:
    """One skill player's verdict + opportunity shares, as a bundle.

    The shares ride along for audit: they are strictly-prior measurements
    and they never upgrade the verdict.  Route share propagates as
    UNKNOWN -- the nflverse participation release (checked Oct 2026,
    CC-BY-SA 4.0) carries play-level on-field player lists but no
    per-player routes-run field, and its 2023+ data is published only
    after the postseason, so it cannot serve pregame evidence in-season
    either.  Routes are therefore never estimated from targets or from
    personnel.
    """
    verdict = assess_skill_participation(
        team=team, player_id=player_id, depth_rows=depth_rows,
        injury_rows=injury_rows, inactive_rows=inactive_rows,
        inactive_snapshots=inactive_snapshots,
        game_id=game_id, target_season=target_season,
        target_week=target_week, kickoff=kickoff, as_of=as_of,
        position=position, max_depth_age_hours=max_depth_age_hours)
    return {
        "verdict": verdict,
        "opportunity_shares": opportunity_shares(
            player_id=str(player_id), team=team,
            player_stat_rows=player_stat_rows,
            target_season=target_season, target_week=target_week,
            snap_rows=snap_rows),
    }


def trailing_team_week_states(
    *,
    team: str,
    player_stat_rows: Sequence[Mapping[str, Any]],
    target_season: int,
    target_week: int,
    state_weeks: int = 8,
) -> list[dict[str, Any]]:
    """Game-state paths replayed from the team's own trailing team weeks.

    Each observed prior team week contributes one market-blind state
    (team TDs and pass/rush TD split from that week's player-stat sums,
    neutral script multipliers).  This keeps the QB's simulated attempts
    and yards on the same team-opportunity paths the runner prices.
    """
    team_id = _team(team)
    prior = _prior_stat_rows(
        player_stat_rows, target_season=int(target_season),
        target_week=int(target_week))
    by_week: dict[tuple[int, int], dict[str, float]] = {}
    for r in prior:
        if _team(r.get("recent_team") or r.get("team")) != team_id:
            continue
        agg = by_week.setdefault(
            (r["_season"], r["_week"]), {"pass_tds": 0.0, "rush_tds": 0.0})
        for field, key in (("passing_tds", "pass_tds"),
                           ("rushing_tds", "rush_tds")):
            try:
                agg[key] += float(r.get(field) or 0)
            except (TypeError, ValueError):
                continue
    states = []
    for key in sorted(by_week)[-int(state_weeks):]:
        agg = by_week[key]
        total = agg["pass_tds"] + agg["rush_tds"]
        states.append({
            "script_source": "trailing_team_week_states_participation_bridge_v1",
            "pass_multiplier": 1.0,
            "rush_multiplier": 1.0,
            "team_tds": int(round(total)),
            "pass_td_share": (agg["pass_tds"] / total) if total > 0 else 0.5,
            "source_week": f"{key[0]}-{key[1]}",
        })
    return states


def _cycled(states: Sequence[Mapping[str, Any]], n: int) -> list:
    if not states:
        return []
    return [states[i % len(states)] for i in range(n)]


def _survival_summary(ladder: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Approximate moments/quantiles from the ladder survival curve."""
    pts = sorted(
        (float(r["line"]), float(r["estimate_p"])) for r in ladder)
    # Extend the curve: S(y) ~ S(first line) below the first rung.
    mean = 0.0
    prev_line, prev_s = 0.0, pts[0][1] if pts else 0.0
    for line, s in pts:
        mean += prev_s * (line - prev_line)
        prev_line, prev_s = line, s
    mean += prev_s * 10.0  # one grid step of tail allowance, declared

    def _quantile(q):
        target = 1.0 - q  # survival level at the q-quantile
        prev_line, prev_s = 0.0, 1.0
        for line, s in pts:
            if s <= target:
                if prev_s == s:
                    return line
                frac = (prev_s - target) / (prev_s - s)
                return prev_line + frac * (line - prev_line)
            prev_line, prev_s = line, s
        return pts[-1][0] if pts else 0.0

    return {
        "mean_yards_trapezoid_approx": mean,
        "p10_yards_approx": _quantile(0.10),
        "p50_yards_approx": _quantile(0.50),
        "p90_yards_approx": _quantile(0.90),
        "approximation": (
            "moments/quantiles interpolated from the priced survival "
            "ladder; exact path values remain inside the runner"),
    }


def qb_passing_yards_research(
    *,
    game_id: str,
    priced_team: str,
    opponent_team: str,
    target_season: int,
    target_week: int,
    kickoff: Any,
    as_of: Any,
    depth_rows: Sequence[Mapping[str, Any]],
    player_stat_rows: Sequence[Mapping[str, Any]],
    injury_rows: Sequence[Mapping[str, Any]] = (),
    inactive_rows: Sequence[Mapping[str, Any]] = (),
    inactive_snapshots: Sequence[Mapping[str, Any]] = (),
    snap_rows: Sequence[Mapping[str, Any]] = (),
    expected_qb_id: str | None = None,
    ladder_lines: Sequence[float] | None = None,
    seed: int = 21,
    min_paths: int = 200,
    state_weeks: int = 8,
    max_depth_age_hours: float = DEFAULT_MAX_DEPTH_AGE_HOURS,
) -> dict[str, Any]:
    """Produce a QB passing-yards RESEARCH distribution behind the gate.

    The priced team's QB must be CONFIRMED_STARTER under
    :func:`assess_qb_participation`; every other state refuses by name.
    The opponent's verdict is computed and disclosed, not gated: the
    opponent payload still has to build under ``build_live_team_model``,
    which itself fails closed on a missing or OUT depth-chart QB.
    """
    cutoff = _utc(as_of, "as_of")
    verdict = assess_qb_participation(
        team=priced_team, depth_rows=depth_rows, injury_rows=injury_rows,
        inactive_rows=inactive_rows, inactive_snapshots=inactive_snapshots,
        game_id=game_id,
        target_season=target_season, target_week=target_week,
        kickoff=kickoff, as_of=as_of,
        expected_player_id=expected_qb_id,
        max_depth_age_hours=max_depth_age_hours)
    _assert_identity_binding(verdict, depth_rows=depth_rows, as_of=cutoff)
    if verdict["state"] != STATE_CONFIRMED:
        raise _gate_refusal(verdict)

    opponent_verdict = assess_qb_participation(
        team=opponent_team, depth_rows=depth_rows, injury_rows=injury_rows,
        inactive_rows=inactive_rows, inactive_snapshots=inactive_snapshots,
        game_id=game_id,
        target_season=target_season, target_week=target_week,
        kickoff=kickoff, as_of=as_of,
        max_depth_age_hours=max_depth_age_hours)

    models: dict[str, Any] = {}
    for code in (verdict["team"], opponent_verdict["team"]):
        try:
            models[code] = build_live_team_model(
                team=code, target_season=int(target_season),
                target_week=int(target_week), kickoff=kickoff,
                observed_at=as_of, depth_rows=depth_rows,
                player_rows=player_stat_rows, injury_rows=injury_rows)
        except NFLContextError as exc:
            raise NFLParticipationError(
                f"NFL_PARTICIPATION_TEAM_MODEL_UNAVAILABLE:{code}:{exc}"
            ) from exc

    model_qb_id = str(models[verdict["team"]]["qb"].get("player_id") or "")
    if model_qb_id != verdict["candidate_id"]:
        raise NFLParticipationError(
            "NFL_PARTICIPATION_IDENTITY_BINDING_MISMATCH:"
            f"{verdict['candidate_id']}:{model_qb_id}")

    states_by_team: dict[str, list] = {}
    for code in models:
        states = trailing_team_week_states(
            team=code, player_stat_rows=player_stat_rows,
            target_season=target_season, target_week=target_week,
            state_weeks=state_weeks)
        if not states:
            raise NFLParticipationError(
                f"NFL_PARTICIPATION_TEAM_STATES_MISSING:{code}")
        states_by_team[code] = states
    n_paths = max(len(states_by_team[models_key]) for models_key in models)
    n_paths = max(n_paths, int(min_paths))
    states_by_team = {
        code: _cycled(states, n_paths)
        for code, states in states_by_team.items()}

    teams_payload = [
        {"team": code, "qb": models[code]["qb"],
         "skill_players": models[code]["skill_players"]}
        for code in (verdict["team"], opponent_verdict["team"])
    ]
    lines = (list(ladder_lines) if ladder_lines is not None else
             [50.5 + 10.0 * i for i in range(41)])
    markets = [
        {"player_id": verdict["candidate_id"], "market": "passing_yards",
         "selection": "OVER", "line": float(line)} for line in lines]
    rows = run_coherent_prop_estimates(
        game_id=str(game_id), teams=teams_payload,
        game_states_by_team=states_by_team, markets=markets, seed=int(seed))
    ladder = [
        {"line": row["line"], "p_over": row["estimate_p"],
         "push_p": row["push_p"]}
        for row in rows]

    return {
        "sport": "NFL",
        "game_id": str(game_id),
        "market": "PLAYER_PASSING_YARDS",
        "status": "RESEARCH_ONLY",
        "research_only": True,
        "validated": False,
        "official_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
        "player_id": verdict["candidate_id"],
        "player_name": verdict["candidate_name"],
        "team": verdict["team"],
        "opponent": opponent_verdict["team"],
        "participation_status": verdict["state"],
        "participation": {
            "priced_team": verdict,
            "opponent_team": opponent_verdict,
        },
        "opportunity_shares": opportunity_shares(
            player_id=verdict["candidate_id"], team=verdict["team"],
            player_stat_rows=player_stat_rows,
            target_season=target_season, target_week=target_week,
            snap_rows=snap_rows),
        "passing_yards_distribution": {
            "paths": rows[0]["paths"] if rows else 0,
            "ladder": ladder,
            **_survival_summary(rows),
        },
        "provenance": {
            "depth_as_of": verdict["depth_as_of"],
            "team_model_source": {
                code: models[code]["source"] for code in models},
            "script_source":
                "trailing_team_week_states_participation_bridge_v1",
            "state_weeks": int(state_weeks),
            "evidence":
                "NFLVERSE_DEPTH_CHARTS+INJURIES+OFFICIAL_INACTIVES_AS_OF",
        },
    }


__all__ = [
    "CONFIRMED_STATES",
    "DEFAULT_MAX_DEPTH_AGE_HOURS",
    "INACTIVES_SNAPSHOT_MAX_LEAD_HOURS",
    "MIN_OFFICIAL_INACTIVE_SNAPSHOT_ROWS",
    "NFLParticipationError",
    "STATE_CONFIRMED",
    "STATE_CONFIRMED_ACTIVE",
    "STATE_OUT",
    "STATE_PROJECTED",
    "STATE_PROJECTED_ROTATION",
    "STATE_QUESTIONABLE",
    "STATE_UNKNOWN",
    "assess_qb_participation",
    "assess_skill_participation",
    "opportunity_shares",
    "qb_passing_yards_research",
    "require_confirmed_qb_role",
    "require_confirmed_skill_role",
    "skill_role_assessment",
    "trailing_team_week_states",
]
