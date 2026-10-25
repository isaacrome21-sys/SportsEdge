"""Per-game freshness evaluation + composite RUN IT card (issue #2359).

Owner contract (Isaac, Oct 15, 2026): the 180s quote-freshness bound is
UNCHANGED, timestamps are never rewritten, and no synthetic verification is
allowed.  What changes is the evaluation clock's scope: instead of judging
every row of a multi-game capture against ONE global ``--as-of`` (the final
read of the LAST game), each game's rows are evaluated with ``as_of`` set to
that game's own recorded operative instant -- its final verification read --
and the per-game cards are merged into one composite card.

Consequences, by construction:

* Cross-game delay no longer kills early games: a game captured first is
  judged against its own final read, not a later game's.
* A single game whose OWN capture span exceeds 180s still refuses its stale
  sections (REFRESH REQUIRED): per-game evaluation removes cross-game delay
  only, never an over-long single-game capture.
* A game's full market selection set is evaluated inside its own run; a
  selection set is never split across per-game runs (grouping is by game
  identity over the whole intake, regardless of row position).
* ``quote_captured_at`` values are inputs and are never rewritten; the
  composite card records each game's operative instant explicitly and is
  disclosed as a composite, never as a single-instant snapshot.
* The merge is fail-closed: the same selection appearing in two game runs
  (or twice in one) refuses the whole merge loudly instead of silently
  deduplicating.
* The merged card carries position accounting in the owner's correlated
  stack semantics (``sportsedge.card_correlation``: rows sharing a thesis
  or game are ONE evidence cluster / position, never independent
  positions), so grading can compute correlated evidence clusters across
  the whole composite.  That accounting keys on ``thesis_id`` else
  ``game_id`` and refuses a row with neither; rows of a game run that
  carry no ``game_id`` of their own are therefore stamped, additively,
  with the composite game identity at merge time (a row's own recorded
  ``game_id`` is never overwritten).
* Per-game PublicContext snapshots may diverge (each game run fetches its
  own point-in-time context as of its own operative instant); the composite
  records the per-game context stamps and discloses the divergence.

Owner audit hardening (issue #2359, Oct 15, 2026):

* Duplicate detection keys on selection identity only -- never on a
  capture/read ID -- so two captures of the same selection under
  different read IDs still refuse the merge.
* Declared selection sets (``set_id``/``set_size``) must be provably
  complete: a member missing its ``set_id`` refuses as an incomplete
  set, never silently bound by game grouping alone.
* The composite is research-only by permission, not just by label: any
  per-game evaluator emitting a PLAY row refuses the whole build.
* An operative instant must be evidenced by the game's own recorded
  capture stamps; a caller-declared instant with no matching capture
  record (a self-declared final re-read) refuses -- a declaration does
  not prove a quote was rechecked.

Release condition (owner, issue #2359): the composite card remains
RESEARCH-ONLY until audit-schema, PIT-context, freshness, deduplication,
and grading regressions pass.  That condition is recorded on the card
(``composite.release_status``) and in the PR description; it is not a
runtime gate.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

COMPOSITE_SCHEMA = "SPORTSEDGE_PER_GAME_COMPOSITE_V1"
RELEASE_STATUS = (
    "RESEARCH_ONLY_UNTIL_AUDIT_PIT_FRESHNESS_DEDUP_GRADING_REGRESSIONS_PASS"
)

# Payload keys the composite path knows how to route per game.  Anything
# else refuses: silently dropping an intake section would violate the
# complete market-set binding.
_SUPPORTED_PAYLOAD_KEYS = frozenset({
    "lines", "sport", "nfl_yardage_pairs", "dk_fixture_menu_snapshot",
})

# Card list surfaces merged by concatenation (after input_index remap).
_LIST_SURFACES = (
    "edges", "lane_b_edges", "lane_b_watchlist",
    "independent_candidates", "independent_watchlist",
    "evaluated_rows", "prop_candidates", "prop_watchlist", "prop_unpriced",
    "diagnostics", "source_receipts", "selection_intake",
)

# Optional per-game annex sections: kept per game inside the composite
# audit block (mirrored at top level only for a single-game composite,
# where the composite is exactly that game's card plus audit structure).
_PER_GAME_SECTIONS = (
    "cfb_research_projections", "dk_fixture_menu_audit",
    "qb_form2_bundle_loader_audit",
)

# Surfaces the owner's correlated-stack accounting reads (t208 semantics).
_ACCOUNTED_SURFACES = ("edges", "independent_candidates", "independent_watchlist")


class CompositeRefusal(ValueError):
    """Fail-closed refusal of a composite build; message carries the code."""


def _parse_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 instant; naive values are read as UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).isoformat()


def game_key_for_row(row: Mapping[str, Any], *, default_sport: str = "") -> tuple:
    """Game identity (sport, away, home, kickoff-utc) for one intake row.

    Kickoff is part of the identity so a doubleheader (same teams, two
    games) groups as two games, never one.
    """
    sport = str(row.get("sport") or default_sport or "").upper().strip()
    away = str(row.get("away") or "").strip()
    home = str(row.get("home") or "").strip()
    kickoff = _parse_instant(row.get("kickoff"))
    if not sport or not away or not home or kickoff is None:
        raise CompositeRefusal(
            "COMPOSITE_GAME_IDENTITY_MISSING: every intake row needs sport, "
            f"away, home and a parseable kickoff to be grouped per game; "
            f"got sport={sport!r} away={away!r} home={home!r} "
            f"kickoff={row.get('kickoff')!r}")
    return (sport, away, home, _iso(kickoff))


def group_intake_rows(
    rows: Sequence[Mapping[str, Any]], *, default_sport: str = "",
) -> list[tuple[tuple, list[dict]]]:
    """Group intake rows by game, first-appearance order, rows unmodified.

    Every row of a game lands in exactly one group, wherever it sits in
    the payload -- the complete market-set binding is structural.
    """
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for row in rows:
        key = game_key_for_row(row, default_sport=default_sport)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(dict(row))
    total = sum(len(groups[key]) for key in order)
    if total != len(rows):  # structural invariant; grouping never drops a row
        raise CompositeRefusal(
            f"COMPOSITE_GROUPING_ROW_COUNT_MISMATCH: grouped {total} of "
            f"{len(rows)} intake rows")
    return [(key, groups[key]) for key in order]


def operative_instant_for(
    stamps: Sequence[Any], *, override: Optional[datetime] = None,
    game_label: str = "",
) -> datetime:
    """A game's operative instant: its final verification read.

    The instant is DERIVED from the game's own recorded capture stamps
    (the maximum) -- it rests on capture evidence, never on a caller's
    declaration.  An explicit override is accepted only when it is exactly
    that recorded final read.  A declared instant later than every
    recorded capture claims a final re-read that no capture row evidences
    (a self-declaration does not prove a quote was rechecked) and refuses;
    an earlier one would mask staleness (and leave later captures in the
    future) and refuses; a declaration with no capture stamps at all is
    unsupported by definition and refuses.
    """
    parsed = [p for p in (_parse_instant(s) for s in stamps) if p is not None]
    latest = max(parsed) if parsed else None
    if override is not None:
        if latest is None:
            raise CompositeRefusal(
                "COMPOSITE_OPERATIVE_INSTANT_NOT_CAPTURE_EVIDENCED: declared "
                f"operative instant {_iso(override)} for game {game_label} "
                "is supported by no recorded capture stamp at all; a "
                "caller's declaration is not capture evidence and the "
                "operative instant must be the game's recorded final "
                "verification read")
        if override < latest:
            raise CompositeRefusal(
                "COMPOSITE_OPERATIVE_INSTANT_PRECEDES_CAPTURE: declared "
                f"operative instant {_iso(override)} precedes a recorded "
                f"capture {_iso(latest)} for game {game_label}; an earlier "
                "instant would mask staleness and is refused")
        if override > latest:
            raise CompositeRefusal(
                "COMPOSITE_OPERATIVE_INSTANT_NOT_CAPTURE_EVIDENCED: declared "
                f"operative instant {_iso(override)} for game {game_label} "
                f"is later than every recorded capture (latest "
                f"{_iso(latest)}); a self-declared final re-read does not "
                "prove a quote was rechecked -- the operative instant must "
                "equal the game's own recorded final verification read")
        return override
    if latest is None:
        raise CompositeRefusal(
            "COMPOSITE_OPERATIVE_INSTANT_UNRECORDED: no parseable "
            f"quote_captured_at on any row of game {game_label} and no "
            "recorded operative instant supplied; the game cannot be "
            "evaluated without inventing a clock, which is refused")
    return latest


def validate_selection_sets(
    keyed_rows: Sequence[tuple[tuple, Mapping[str, Any]]],
) -> None:
    """Declared selection-set completeness (owner audit, issue #2359).

    A row declares set membership by carrying ``set_id`` and/or
    ``set_size``.  Either marker alone is a broken declaration: a member
    whose ``set_id`` is missing must never slip past the completeness
    check and be silently bound by game grouping alone.  A declared set
    is complete only when every member carries both markers, all members
    agree on the size, the member count equals the declared size, and
    the whole set sits inside ONE game (a set never spans per-game runs).
    Rows carrying neither marker are ordinary rows and are unaffected.
    """
    sets: dict[str, list[tuple[tuple, Any]]] = {}
    for key, row in keyed_rows:
        set_id = row.get("set_id")
        has_id = set_id is not None and str(set_id).strip() != ""
        has_size = row.get("set_size") is not None
        if has_id != has_size:
            raise CompositeRefusal(
                "COMPOSITE_SELECTION_SET_INCOMPLETE: a selection-set member "
                f"declares {'set_size without set_id' if has_size else 'set_id without set_size'} "
                f"(set_id={set_id!r}, set_size={row.get('set_size')!r}); a "
                "set member missing its set identity is refused as "
                "incomplete, never silently bound")
        if not has_id:
            continue
        size = row.get("set_size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise CompositeRefusal(
                "COMPOSITE_SELECTION_SET_INCOMPLETE: set "
                f"{str(set_id)!r} declares invalid set_size {size!r}; the "
                "set cannot be proven complete and is refused")
        sets.setdefault(str(set_id), []).append((key, size))
    for set_id, members in sets.items():
        sizes = {size for _, size in members}
        if len(sizes) != 1:
            raise CompositeRefusal(
                "COMPOSITE_SELECTION_SET_INCOMPLETE: set "
                f"{set_id!r} members disagree on set_size {sorted(sizes)}; "
                "the set cannot be proven complete and is refused")
        declared = next(iter(sizes))
        if len(members) != declared:
            raise CompositeRefusal(
                "COMPOSITE_SELECTION_SET_INCOMPLETE: set "
                f"{set_id!r} declares {declared} members but {len(members)} "
                "were captured; an incomplete market set is refused, never "
                "silently bound")
        games = {key for key, _ in members}
        if len(games) != 1:
            raise CompositeRefusal(
                "COMPOSITE_SELECTION_SET_SPLIT_ACROSS_GAMES: set "
                f"{set_id!r} spans {len(games)} games; a selection set is "
                "evaluated whole inside its own game's run and is never "
                "split across per-game runs")


def selection_identity(
    row: Mapping[str, Any],
    intake_row: Optional[Mapping[str, Any]] = None,
    *, game_key: Optional[tuple] = None,
) -> tuple:
    """Merge-time identity of one evaluated row for duplicate detection.

    The identity is the SELECTION and nothing else: capture/read
    identifiers (``capture_id``, ``source_read_id``, ``read_id``,
    ``observation_id``), odds and capture stamps are deliberately NOT
    part of it -- a re-read of the same selection under a different read
    ID is still the same selection, and keying deduplication on a read
    ID would let duplicate captures of one selection survive the merge
    as if they were distinct rows.

    Thin evaluated rows (e.g. NFL derivative team totals, whose evaluated
    form is a bare "OVER" with no line, team or game fields) cannot
    distinguish two different selections of the same game on their own,
    so the identity falls back to the paired intake row -- the
    authoritative record of what was captured -- for the line, team and
    player distinguishers.  Two genuinely different selections (Seattle
    team-total OVER 20.5 vs Denver OVER 23.5) therefore never collide,
    while two captures of one selection always do.
    """
    intake = intake_row or {}
    game_ref = (
        row.get("game_id")
        or ("|".join(game_key) if game_key else None)
        or f"{row.get('game')}|{row.get('kickoff_utc')}")
    player_ref = (
        row.get("player_name") or row.get("player") or
        row.get("pitcher_name") or row.get("batter_name") or
        intake.get("player_name") or intake.get("player") or "")
    line = row.get("line")
    if line is None:
        line = intake.get("line")
    team_ref = (
        row.get("team_totals_team") or intake.get("team_side") or
        intake.get("team") or "")
    return (
        str(row.get("sport") or intake.get("sport") or "").upper(),
        str(game_ref),
        str(row.get("market") or intake.get("market") or "").upper(),
        str(row.get("selection") or intake.get("selection")
            or intake.get("side") or ""),
        line,
        str(player_ref),
        str(team_ref),
    )


def _refuse_on_duplicates(identities: Sequence[tuple]) -> None:
    seen: dict[tuple, int] = {}
    for position, identity in enumerate(identities):
        if identity in seen:
            raise CompositeRefusal(
                "COMPOSITE_DUPLICATE_SELECTION: the same selection appears "
                f"more than once across the merged runs (first at merged "
                f"input_index {seen[identity]}, again at {position}): "
                f"{identity!r}; the merge refuses rather than deduplicating "
                "silently, and duplicate rows must never grade as "
                "independent positions")
        seen[identity] = position


def _refuse_on_play_status(card: Mapping[str, Any], *, game_label: str) -> None:
    """Research-only permission guard (owner audit, issue #2359).

    PLAY is reserved for validated model families; none exist.  If any
    per-game (child) evaluator emits a row carrying PLAY status -- on any
    surface -- the composite refuses the whole card rather than letting
    the label reach a merged research card, where it would read as
    wagering authority it does not have.
    """
    for surface in _LIST_SURFACES:
        for row in card.get(surface) or []:
            if not isinstance(row, Mapping):
                continue
            if row.get("status") == "PLAY" or row.get("play") is True:
                raise CompositeRefusal(
                    "COMPOSITE_PLAY_STATUS_FORBIDDEN: a per-game evaluator "
                    f"emitted a PLAY row for game {game_label} (surface "
                    f"{surface}, selection {row.get('selection')!r}); PLAY "
                    "is reserved for validated families (none exist) and "
                    "a composite research card can never surface it")


def _attach_position_accounting(card: dict) -> None:
    """Owner's correlated-stack accounting over the merged card (t208).

    Rows sharing a thesis (or, absent one, a game) are ONE position for
    grading; the per-stack structure rides on the card so the grader can
    compute correlated evidence clusters across the whole composite.
    """
    from sportsedge.card_correlation import grade_card_positions

    seen: set = set()
    rows: list[dict] = []
    for surface in _ACCOUNTED_SURFACES:
        for row in card.get(surface) or []:
            identity = (row.get("input_index"), row.get("game_id") or row.get("game"),
                        row.get("thesis_id"), row.get("selection"))
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(row)
    try:
        accounting = grade_card_positions(rows)
    except ValueError as exc:
        raise CompositeRefusal(f"COMPOSITE_POSITION_ACCOUNTING_REFUSED:{exc}") from exc
    card["position_accounting"] = accounting
    card["summary"]["surfaced_positions"] = accounting["positions"]
    card["summary"]["surfaced_legs"] = accounting["legs"]


def run_composite(
    payload: Any,
    *,
    now: Any = None,
    operative_instants: Optional[Mapping[str, Any]] = None,
    run_full_fn: Optional[Callable[..., dict]] = None,
    **run_kwargs: Any,
) -> dict:
    """Evaluate each game at its own operative instant; merge one card.

    ``operative_instants`` optionally maps a game key (the
    ``game_key_for_row`` tuple, or its ``"|"``-joined string form) to that
    game's recorded operative instant.  ``run_kwargs`` are passed through
    to every per-game ``run_full`` call unchanged (``auto_context``,
    ``min_ev``, ``lane``, Form 2 arguments, ...).
    """
    if run_full_fn is None:
        from artifacts.run_it_full import run_full as run_full_fn  # noqa: F811

    if isinstance(payload, Mapping):
        unsupported = sorted(set(payload) - _SUPPORTED_PAYLOAD_KEYS)
        if unsupported:
            raise CompositeRefusal(
                "COMPOSITE_PAYLOAD_KEY_UNSUPPORTED: the composite path "
                f"cannot route payload keys {unsupported} per game; refusing "
                "rather than dropping an intake section silently")
        rows_in = payload.get("lines")
        default_sport = str(payload.get("sport") or "")
        pairs_in = list(payload.get("nfl_yardage_pairs") or [])
        menu_snapshot = payload.get("dk_fixture_menu_snapshot")
    elif isinstance(payload, list):
        rows_in, default_sport, pairs_in, menu_snapshot = payload, "", [], None
    else:
        raise CompositeRefusal(
            "COMPOSITE_PAYLOAD_MUST_BE_LIST_OR_MAPPING_WITH_LINES")
    if not isinstance(rows_in, list):
        raise CompositeRefusal("COMPOSITE_LINES_MUST_BE_LIST")
    rows_in = list(rows_in)
    if not rows_in and not pairs_in:
        raise CompositeRefusal("COMPOSITE_NO_INTAKE_ROWS")

    wall = _parse_instant(now) or datetime.now(timezone.utc)

    overrides: dict[tuple, datetime] = {}
    for raw_key, raw_value in (operative_instants or {}).items():
        instant = _parse_instant(raw_value)
        if instant is None:
            raise CompositeRefusal(
                f"COMPOSITE_OPERATIVE_INSTANT_INVALID: {raw_value!r}")
        if isinstance(raw_key, str):
            parts = raw_key.split("|")
            if len(parts) != 4:
                raise CompositeRefusal(
                    f"COMPOSITE_OPERATIVE_INSTANT_KEY_INVALID: {raw_key!r}")
            kickoff = _parse_instant(parts[3])
            if kickoff is None:
                raise CompositeRefusal(
                    f"COMPOSITE_OPERATIVE_INSTANT_KEY_INVALID: {raw_key!r}")
            key = (parts[0].upper(), parts[1], parts[2], _iso(kickoff))
        else:
            key = tuple(raw_key)  # type: ignore[arg-type]
        overrides[key] = instant

    groups = group_intake_rows(rows_in, default_sport=default_sport)
    group_keys = {key for key, _ in groups}

    # Yardage pairs belong to exactly one game each, by the same identity.
    pairs_by_game: dict[tuple, list[dict]] = {}
    for pair in pairs_in:
        key = game_key_for_row(pair, default_sport=default_sport)
        pairs_by_game.setdefault(key, []).append(dict(pair))
        if key not in group_keys:
            groups.append((key, []))
            group_keys.add(key)

    # Declared selection sets must be provably complete before any game
    # is evaluated; an incomplete set refuses the whole composite.
    validate_selection_sets(
        [(key, row) for key, game_rows in groups for row in game_rows]
        + [(key, pair) for key, plist in pairs_by_game.items()
           for pair in plist])

    # Preflight every game before invoking any pricing runner. A late invalid
    # game must not allow earlier games to produce partial side effects.
    from sportsedge.quote_freshness import check_quote_freshness, is_fresh
    preflight: dict[tuple, datetime] = {}
    for key, game_rows in groups:
        stamps: list[Any] = [r.get("quote_captured_at") for r in game_rows]
        stamps += [p.get("captured_at") for p in pairs_by_game.get(key, [])]
        operative = operative_instant_for(
            stamps, override=overrides.get(key), game_label="|".join(key))
        for stamp in stamps:
            freshness = check_quote_freshness(stamp, now=wall, max_age_seconds=1800)
            if not is_fresh(freshness):
                raise CompositeRefusal("COMPOSITE_WALL_QUOTE_NOT_CURRENT:" + freshness["code"])
        preflight[key] = operative

    game_cards: list[tuple[tuple, list[dict], datetime, dict]] = []
    for key, game_rows in groups:
        operative = preflight[key]
        sub_payload: dict[str, Any] = {"lines": [dict(r) for r in game_rows]}
        if default_sport:
            sub_payload["sport"] = default_sport
        if pairs_by_game.get(key):
            sub_payload["nfl_yardage_pairs"] = pairs_by_game[key]
        card = run_full_fn(
            sub_payload, now=wall, as_of=_iso(operative), **run_kwargs)
        _refuse_on_play_status(card, game_label="|".join(key))
        game_cards.append((key, game_rows, operative, card))

    return _merge_game_cards(
        game_cards, wall=wall, default_sport=default_sport,
        menu_snapshot=menu_snapshot, total_intake_rows=len(rows_in),
        pairs_by_game=pairs_by_game)


def _merge_game_cards(
    game_cards: Sequence[tuple[tuple, list[dict], datetime, dict]],
    *, wall: datetime, default_sport: str, menu_snapshot: Any,
    total_intake_rows: int,
    pairs_by_game: Mapping[tuple, list[dict]],
) -> dict:
    first = game_cards[0][3]
    merged: dict[str, Any] = {
        "schema": first["schema"],
        "authority": first.get("authority"),
        "quote_freshness_policy": first.get("quote_freshness_policy"),
        "min_ev": first.get("min_ev"),
        "primary_lane": first.get("primary_lane"),
        "play_gate": first.get("play_gate"),
        "canonical_coverage": first.get("canonical_coverage"),
        "runner": first.get("runner"),
        "research_projection_note": first.get("research_projection_note"),
    }
    for surface in _LIST_SURFACES:
        merged[surface] = []

    # --- input_index remap + surface concatenation, in game order --------
    labeled_inputs: list[dict] = []
    merged_identities: list[tuple] = []
    factor_entries: list[dict] = []
    factor_status_counts: Counter = Counter()
    prepricing_entries: list[dict] = []
    next_index = 0
    for key, game_rows, operative, card in game_cards:
        index_map: dict[Any, int] = {}
        for row in card.get("evaluated_rows") or []:
            index_map[row.get("input_index")] = next_index
            next_index += 1

        def remapped(row: Mapping[str, Any], *, enrich_game_id: bool = False) -> dict:
            out = dict(row)
            local = out.get("input_index")
            if local is not None:
                if local not in index_map:
                    raise CompositeRefusal(
                        "COMPOSITE_AUDIT_INDEX_UNMAPPED: a surfaced row "
                        f"carries input_index {local} that is not among its "
                        f"game run's evaluated rows (game {'|'.join(key)})")
                out["input_index"] = index_map[local]
            if enrich_game_id and not out.get("game_id"):
                # Cluster-key enrichment (additive): the owner's stack
                # accounting keys on thesis_id else game_id and refuses a
                # row with neither.  Rows of this game run that carry no
                # game_id of their own are stamped with the composite game
                # identity so grading can cluster the whole composite; a
                # row's own recorded game_id is never overwritten.
                out["game_id"] = "|".join(key)
            return out

        for surface in _LIST_SURFACES:
            for row in card.get(surface) or []:
                merged[surface].append(
                    remapped(row, enrich_game_id=surface != "selection_intake"))

        coverage = card.get("factor_coverage") or {}
        for entry in coverage.get("by_input_index") or []:
            factor_entries.append(remapped(entry))
        factor_status_counts.update(coverage.get("status_counts") or {})
        audit = card.get("prepricing_factor_audit") or {}
        for entry in audit.get("by_input_index") or []:
            prepricing_entries.append(remapped(entry))

        # Expanded per-game intake (post yardage binding + ladder
        # expansion), rebuilt with the runner's own intake pipeline so the
        # merged full board zips 1:1 with the merged evaluated rows.  Pair
        # binding is deterministic given the game's operative instant,
        # which is exactly the as_of the per-game run used.
        from artifacts.run_it_full import expand_milestone_ladder_rows
        from sportsedge.paired_yardage_intake import bind_nfl_yardage_pair

        expanded = [dict(r) for r in game_rows]
        for pair in pairs_by_game.get(key, []):
            over_row, under_row = bind_nfl_yardage_pair(pair, as_of=operative)
            expanded.extend([over_row, under_row])
        expanded = expand_milestone_ladder_rows(
            expanded, default_sport=default_sport or None)
        labeled_inputs.extend(
            {**raw, "sport": str(raw.get("sport") or default_sport or "").upper()}
            for raw in expanded)

        # Per-game board alignment + duplicate identities: the expanded
        # intake zips 1:1 with the game's evaluated rows (the runner's
        # phone card already enforces input_index == position per run).
        game_evaluated = card.get("evaluated_rows") or []
        if len(expanded) != len(game_evaluated):
            raise CompositeRefusal(
                "COMPOSITE_BOARD_ALIGNMENT_MISMATCH: rebuilt intake for "
                f"game {'|'.join(key)} has {len(expanded)} rows vs "
                f"{len(game_evaluated)} evaluated rows; refusing to "
                "present a misaligned board")
        for intake_row, evaluated_row in zip(expanded, game_evaluated):
            merged_identities.append(
                selection_identity(evaluated_row, intake_row, game_key=key))

    # Duplicate detection runs before any presentation rebuild: a poisoned
    # merge refuses as a duplicate, never as a downstream shape error.
    _refuse_on_duplicates(merged_identities)

    if len(labeled_inputs) != len(merged["evaluated_rows"]):
        raise CompositeRefusal(
            "COMPOSITE_BOARD_ALIGNMENT_MISMATCH: rebuilt intake has "
            f"{len(labeled_inputs)} rows vs {len(merged['evaluated_rows'])} "
            "evaluated rows; refusing to present a misaligned board")

    # --- scalar / audit merges -------------------------------------------
    status_counts: Counter = Counter()
    for _, _, _, card in game_cards:
        status_counts.update((card.get("summary") or {}).get("status_counts") or {})
    merged["summary"] = {
        "rows": len(merged["evaluated_rows"]),
        "edges": len(merged["edges"]),
        "lane_b_edges": len(merged["lane_b_edges"]),
        "lane_b_watchlist": len(merged["lane_b_watchlist"]),
        "status_counts": dict(sorted(status_counts.items())),
    }
    merged["factor_coverage"] = {
        "schema": (first.get("factor_coverage") or {}).get("schema"),
        "coverage_is_not_validation": True,
        "by_input_index": factor_entries,
        "status_counts": dict(sorted(factor_status_counts.items())),
        "advanced_metrics": (first.get("factor_coverage") or {}).get("advanced_metrics"),
    }
    merged["prepricing_factor_audit"] = {
        "schema": (first.get("prepricing_factor_audit") or {}).get("schema"),
        "market_odds_as_features": (first.get("prepricing_factor_audit") or {}).get(
            "market_odds_as_features"),
        "by_input_index": prepricing_entries,
    }
    prop_status = dict(first.get("prop_model_status") or {})
    if prop_status:
        prop_status["unsupported_player_markets_blocked"] = len(merged["prop_unpriced"])
    merged["prop_model_status"] = prop_status

    if any(str(r.get("sport") or "").upper() == "MLB"
           for r in merged["evaluated_rows"]):
        from sportsedge.mlb_phone_full_board import phone_market_board
        merged["mlb_full_board"] = phone_market_board(
            labeled_inputs, merged["evaluated_rows"])
        merged["summary"]["mlb_market_coverage"] = dict(
            merged["mlb_full_board"]["input_coverage"])

    # --- composite audit block: per-game operative instants + PIT stamps --
    games_block = []
    for key, game_rows, operative, card in game_cards:
        entry: dict[str, Any] = {
            "game_key": {
                "sport": key[0], "away": key[1], "home": key[2],
                "kickoff_utc": key[3],
            },
            "operative_instant_utc": _iso(operative),
            "as_of_utc": card.get("as_of_utc"),
            "wall_utc": card.get("wall_utc"),
            "n_intake_rows": len(game_rows),
            "input_snapshot": card.get("input_snapshot"),
            "context_as_of_utc": (card.get("input_snapshot") or {}).get("as_of_utc"),
            "quote_captured_at_stamps": sorted(
                {str(r.get("quote_captured_at")) for r in game_rows
                 if r.get("quote_captured_at") is not None}),
        }
        sections = {name: card[name] for name in _PER_GAME_SECTIONS
                    if card.get(name) is not None}
        if sections:
            entry["sections"] = sections
        games_block.append(entry)

    operative_max = max(operative for _, _, operative, _ in game_cards)
    all_rows_sha = hashlib.sha1(json.dumps(
        [r for _, game_rows, _, _ in game_cards for r in game_rows],
        sort_keys=True, default=str).encode()).hexdigest()
    merged["as_of_utc"] = _iso(operative_max)
    merged["wall_utc"] = _iso(wall)
    merged["input_snapshot"] = {
        "n_rows": total_intake_rows,
        "rows_sha1": all_rows_sha,
        "as_of_utc": _iso(operative_max),
        "wall_utc": _iso(wall),
        "historical_repriced": bool(
            (first.get("input_snapshot") or {}).get("historical_repriced")),
        "composite": True,
    }
    merged["composite"] = {
        "schema": COMPOSITE_SCHEMA,
        "kind": "PER_GAME_EVALUATION_COMPOSITE",
        "disclosure": (
            "This card is a COMPOSITE of per-game runs: each game was "
            "evaluated as of its own recorded operative instant (its final "
            "verification read), not at one single instant. quote_captured_at "
            "values are the original recorded stamps and were never "
            "rewritten. Per-game PublicContext snapshots may diverge; the "
            "per-game context stamps are recorded below."),
        "research_only": True,
        "release_status": RELEASE_STATUS,
        "freshness_policy": "PER_GAME_OPERATIVE_INSTANT_180S_UNCHANGED",
        "pit_context": "PER_GAME_SNAPSHOTS_MAY_DIVERGE",
        "games_count": len(game_cards),
        "games": games_block,
    }
    if menu_snapshot is not None:
        merged["composite"]["dk_fixture_menu_snapshot_supplied"] = True

    if len(game_cards) == 1:
        only = game_cards[0][3]
        for name in _PER_GAME_SECTIONS:
            if only.get(name) is not None:
                merged[name] = only[name]

    _attach_position_accounting(merged)

    from sportsedge.phone_display import build_phone_card
    merged["phone_card"] = build_phone_card(merged)
    return merged
