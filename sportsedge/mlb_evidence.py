"""MLB-specific adapters into the canonical SportsEdge evidence contract."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .evidence import EvidencePacket, lineup_status_evidence, starter_evidence
from .live_slate import lineup_from_rows
from .mlb_source import GameSnapshot, parse_confirmed_lineup


def _roster_player_ids(boxscore: Mapping[str, Any], side: str) -> tuple[int, ...]:
    team = ((boxscore.get("teams") or {}).get(side) or {})
    players = team.get("players") or {}
    out: set[int] = set()
    if not isinstance(players, Mapping):
        return ()
    for raw in players.values():
        if not isinstance(raw, Mapping):
            continue
        person = raw.get("person") or {}
        try:
            player_id = int(person.get("id"))
        except (TypeError, ValueError):
            continue
        if player_id > 0:
            out.add(player_id)
    return tuple(sorted(out))


def official_mlb_evidence(
    *,
    snapshot: GameSnapshot,
    boxscore: Mapping[str, Any] | None,
    observed_at_utc: datetime | str,
    acquisition_mode: str = "AUTOMATIC",
) -> tuple[EvidencePacket, ...]:
    """Build official MLB starter/lineup evidence without inventing missing facts.

    Schedule probable pitchers are PRIMARY evidence because they may change before
    first pitch. A complete nine-slot batting order from MLB's boxscore is treated
    as AUTHORITATIVE. Once a batting order is confirmed, rostered players outside
    those nine are emitted as confirmed absent so player markets can fail closed.
    """
    packets: list[EvidencePacket] = []
    game_id = str(snapshot.game_pk)
    starter_rows = (
        (snapshot.away_id, snapshot.away_probable_pitcher_id, "away"),
        (snapshot.home_id, snapshot.home_probable_pitcher_id, "home"),
    )
    for team_id, pitcher_id, side in starter_rows:
        if pitcher_id is None:
            continue
        packet = starter_evidence(
            game_id=game_id,
            team_id=str(team_id),
            starter_id=str(pitcher_id),
            source_name="MLB_STATSAPI_SCHEDULE",
            observed_at_utc=observed_at_utc,
            acquisition_mode=acquisition_mode,
            authority="PRIMARY",
            verified=True,
        )
        # Preserve the fact that this is a probable-pitcher designation without
        # weakening the normalized identity used by the resolver.
        packets.append(EvidencePacket(
            game_id=packet.game_id,
            fact_type=packet.fact_type,
            subject_id=packet.subject_id,
            value=packet.value,
            source_name=packet.source_name,
            observed_at_utc=packet.observed_at_utc,
            acquisition_mode=packet.acquisition_mode,
            authority=packet.authority,
            verified=packet.verified,
            scope=packet.scope,
            metadata={"side": side, "designation": "probable_pitcher"},
        ))

    if boxscore is None:
        return tuple(packets)

    for side, team_id in (("away", snapshot.away_id), ("home", snapshot.home_id)):
        rows = parse_confirmed_lineup(dict(boxscore), side)
        try:
            lineup = lineup_from_rows(team_id, side, rows)
        except Exception:
            # The live slate builder owns malformed-lineup failure semantics. The
            # evidence adapter simply refuses to manufacture a lineup fact here.
            continue
        if not lineup.confirmed:
            continue
        starting_ids = {
            int(row["player_id"])
            for row in rows
            if int(row.get("sequence", 0)) == 0 and row.get("player_id") is not None
        }
        roster_ids = set(_roster_player_ids(boxscore, side))
        for player_id in sorted(roster_ids | starting_ids):
            packets.append(lineup_status_evidence(
                game_id=game_id,
                player_id=str(player_id),
                in_starting_lineup=player_id in starting_ids,
                source_name="MLB_STATSAPI_BOXSCORE",
                observed_at_utc=observed_at_utc,
                acquisition_mode=acquisition_mode,
                authority="AUTHORITATIVE",
                verified=True,
            ))
    return tuple(packets)
