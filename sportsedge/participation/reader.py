"""As-of reader for the participation archive.

The reader answers one honest question: *given a player/team/game and an
as-of timestamp, what can the archive prove was knowable then?*

Rules enforced here (foundation doc sections 1 and 3), independent of the
``available_from_utc`` bounds already stamped on records (defense in
depth -- both must pass):

- Designations (S3/S4): admissible only at/after the final-report bound
  for the bound game.
- Roster status (S5): PRIOR-WEEK rule -- a week-W snapshot is never used
  for a week-W game; only snapshots from weeks < W, and only once the
  snapshot week's bound has passed.
- Depth charts (S6): prior-week chart only (lag rule), backup identity
  only; snap evidence outranks chart evidence (see ``primary_qb_entering``
  / ``backup_qb_for`` ordering).
- Snap/starter actuals (S1/S2/S9): TRAINING_TARGET / VALIDATION_LABEL
  only. Requesting a game's OWN snaps as pregame features is refused with
  ``PIT_SAME_GAME_SNAPS_REFUSED_AS_FEATURE``. Prior games' snaps are
  returnable as feature *inputs* for a later game once their completion
  bound has passed.
- Forward-capture-only signals (S7/S8): visible only at/after their real
  capture timestamp.

Every answer carries a reason: either the record found, or the exact
fail-closed reason nothing was provable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .archive import ParticipationArchive
from .schema import (
    REJ_NOT_YET_AVAILABLE,
    REJ_SAME_GAME_SNAPS_FEATURE,
    REJ_TEAM_WEEK_ABSENT,
    SIGNAL_DEPTH_CHART,
    SIGNAL_INACTIVE,
    SIGNAL_INJURY_DESIGNATION,
    SIGNAL_PRACTICE_STATUS,
    SIGNAL_REPORT_REVISION,
    SIGNAL_ROSTER_STATUS,
    SIGNAL_SNAP_ACTUAL,
    SIGNAL_STARTER_ACTUAL,
    ParticipationRecord,
)


def _ts(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _available(rec: ParticipationRecord, as_of: datetime) -> bool:
    bound = _ts(rec.available_from_utc)
    return bound is not None and bound <= as_of


class AsOfReader:
    def __init__(self, archive: ParticipationArchive):
        self.archive = archive
        self._cache: dict[str, list[ParticipationRecord]] = {}

    def _records(self, signal_type: str, as_of=None) -> list[ParticipationRecord]:
        """Resolve superseding corrections only when genuinely visible at as-of.

        The original historical source may carry a named cadence-inferred
        bound; that is not publication-time proof. A subsequently archived
        correction must be both captured AND available by the query cutoff.
        This prevents a newer record from hiding a still-valid older version
        in retrospective as-of reads. Reload each query to see appended data.
        """
        records = self.archive.load_records(signal_type)
        if as_of is None:
            superseded = {r.supersedes_record_id for r in records
                          if r.supersedes_record_id}
            return [r for r in records if r.record_id not in superseded]
        cutoff = _ts(as_of)
        eligible = []
        seen_ids = set()
        for rec in records:
            if not _available(rec, cutoff):
                continue
            if rec.supersedes_record_id:
                if _ts(rec.captured_at_utc) > cutoff:
                    continue
                if rec.supersedes_record_id not in seen_ids:
                    continue
            eligible.append(rec)
            seen_ids.add(rec.record_id)
        superseded = {r.supersedes_record_id for r in eligible
                      if r.supersedes_record_id}
        return [r for r in eligible if r.record_id not in superseded]

    @staticmethod
    def _answer(record, reason=None):
        if record is None:
            return {"status": "UNAVAILABLE", "record": None, "reason": reason}
        return {"status": "OK", "record": record, "reason": None}

    # -- S3 / S4 ------------------------------------------------------------
    def _player_week_lookup(self, signal_type, gsis_id, season, week, as_of):
        # Distinguish an absent source row from a row that exists but was not
        # yet visible at the requested cutoff, preserving fail-closed reasons.
        original = [r for r in self.archive.iter_records(signal_type)
                    if r.gsis_id == gsis_id and r.season == season and r.week == week]
        if not original:
            return self._answer(None, REJ_TEAM_WEEK_ABSENT)
        visible = [r for r in self._records(signal_type, as_of)
                   if r.gsis_id == gsis_id and r.season == season and r.week == week]
        if not visible:
            return self._answer(None, REJ_NOT_YET_AVAILABLE)
        return self._answer(visible[-1])

    def designation_for(self, gsis_id: str, season: int, week: int, as_of) -> dict:
        """Final injury designation (S3) provable at ``as_of``."""
        return self._player_week_lookup(
            SIGNAL_INJURY_DESIGNATION, gsis_id, season, week, _ts(as_of)
        )

    def practice_status_for(self, gsis_id: str, season: int, week: int, as_of) -> dict:
        """Final practice status (S4, restricted) provable at ``as_of``."""
        return self._player_week_lookup(
            SIGNAL_PRACTICE_STATUS, gsis_id, season, week, _ts(as_of)
        )

    # -- S5 -----------------------------------------------------------------
    def roster_status_for(self, gsis_id: str, season: int, week: int, as_of) -> dict:
        """Roster/reserve status under the PRIOR-WEEK lag rule.

        Only snapshots from weeks strictly before ``week`` are eligible,
        and only once their week-conclusion bound is <= as_of. The most
        recent eligible snapshot wins.
        """
        as_of = _ts(as_of)
        cands = [
            r
            for r in self._records(SIGNAL_ROSTER_STATUS, as_of)
            if r.gsis_id == gsis_id
            and r.season == season
            and r.week is not None
            and r.week < week
            and _available(r, as_of)
        ]
        if not cands:
            return self._answer(None, REJ_NOT_YET_AVAILABLE)
        cands.sort(key=lambda r: (r.week, r.captured_at_utc))
        return self._answer(cands[-1])

    # -- S6 -----------------------------------------------------------------
    def depth_chart_qb_for(self, team: str, season: int, week: int, depth_rank: int, as_of) -> dict:
        """Depth-chart QB at ``depth_rank`` under the prior-week lag rule."""
        as_of = _ts(as_of)
        cands = [
            r
            for r in self._records(SIGNAL_DEPTH_CHART, as_of)
            if r.team == team
            and r.season == season
            and r.week is not None
            and r.week < week
            and r.payload.get("depth_rank") == depth_rank
            and _available(r, as_of)
        ]
        if not cands:
            return self._answer(None, REJ_NOT_YET_AVAILABLE)
        cands.sort(key=lambda r: (r.week, r.captured_at_utc))
        return self._answer(cands[-1])

    # -- S1 / S2 / S9 ---------------------------------------------------------
    def label_snaps_for_game(self, game_id: str) -> dict:
        """Same-game snaps as TRAINING_TARGET / VALIDATION_LABEL (S9)."""
        recs = [r for r in self._records(SIGNAL_SNAP_ACTUAL) if r.game_id == game_id]
        if not recs:
            return {"status": "UNAVAILABLE", "records": [], "reason": REJ_TEAM_WEEK_ABSENT}
        return {"status": "OK", "records": recs, "reason": None}

    def feature_snaps_for_game(self, game_id: str, as_of) -> dict:
        """Pregame-feature request for a game's snaps.

        Same-game snaps are NEVER pregame features -- refused outright.
        (Feature inputs about a team come from PRIOR games via
        ``prior_game_snaps``.)
        """
        return {
            "status": "REFUSED",
            "records": [],
            "reason": REJ_SAME_GAME_SNAPS_FEATURE,
        }

    def prior_game_snaps(self, team: str, season: int, before_week: int, as_of) -> dict:
        """Snap records of the team's most recent game before ``before_week``
        whose completion bound is <= as_of (feature inputs for a later game)."""
        as_of = _ts(as_of)
        cands = [
            r
            for r in self._records(SIGNAL_SNAP_ACTUAL, as_of)
            if r.team == team
            and r.season == season
            and r.week is not None
            and r.week < before_week
            and _available(r, as_of)
        ]
        if not cands:
            return {"status": "UNAVAILABLE", "records": [], "reason": REJ_NOT_YET_AVAILABLE}
        latest_week = max(r.week for r in cands)
        return {
            "status": "OK",
            "records": [r for r in cands if r.week == latest_week],
            "reason": None,
        }

    def starter_label_for(self, team: str, game_id: str) -> dict:
        """Actual starter (S1) as a validation label for a played game."""
        recs = [
            r
            for r in self._records(SIGNAL_STARTER_ACTUAL)
            if r.team == team and r.game_id == game_id
        ]
        if not recs:
            return self._answer(None, REJ_TEAM_WEEK_ABSENT)
        return self._answer(recs[-1])

    # -- S7 / S8 (forward capture only) --------------------------------------
    def _forward_lookup(self, signal_type, gsis_id, game_id, as_of):
        as_of = _ts(as_of)
        cands = [
            r
            for r in self._records(signal_type, as_of)
            if r.gsis_id == gsis_id and r.game_id == game_id and _available(r, as_of)
        ]
        if not cands:
            return self._answer(None, REJ_NOT_YET_AVAILABLE)
        return self._answer(cands[-1])

    def inactive_for(self, gsis_id: str, game_id: str, as_of) -> dict:
        return self._forward_lookup(SIGNAL_INACTIVE, gsis_id, game_id, as_of)

    def revision_for(self, gsis_id: str, game_id: str, as_of) -> dict:
        return self._forward_lookup(SIGNAL_REPORT_REVISION, gsis_id, game_id, as_of)
