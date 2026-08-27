"""MLB-specific adapters into the canonical SportsEdge evidence contract."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .evidence import EvidencePacket, lineup_status_evidence, starter_evidence
from .live_slate import lineup_from_rows
from .mlb_source import GameSnapshot, parse_confirmed_lineup


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
    as AUTHORITATIVE. The adapter records the confirmed nine as one team fact plus
    positive member facts. It deliberately does not emit roster-wide negative
    player facts because batting-lineup absence must never block pitcher markets for
    the same player identity (including two-way players). Hitter absence is already
    fail-closed in the canonical live-slate assembler and may also be supplied as a
    market-scoped manual evidence gate.
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
        ordered_starting_ids = tuple(
            int(row["player_id"])
            for row in sorted(rows, key=lambda item: int(item["slot"]))
            if int(row.get("sequence", 0)) == 0 and row.get("player_id") is not None
        )
        if len(ordered_starting_ids) != 9:
            continue
        packets.append(EvidencePacket(
            game_id=game_id,
            fact_type="STARTING_LINEUP_IDS",
            subject_id=str(team_id),
            value=list(ordered_starting_ids),
            source_name="MLB_STATSAPI_BOXSCORE",
            observed_at_utc=observed_at_utc,
            acquisition_mode=acquisition_mode,
            authority="AUTHORITATIVE",
            verified=True,
            scope="GAME",
            metadata={"side": side, "confirmed": True},
        ))
        for player_id in ordered_starting_ids:
            packets.append(lineup_status_evidence(
                game_id=game_id,
                player_id=str(player_id),
                in_starting_lineup=True,
                source_name="MLB_STATSAPI_BOXSCORE",
                observed_at_utc=observed_at_utc,
                acquisition_mode=acquisition_mode,
                authority="AUTHORITATIVE",
                verified=True,
            ))
    return tuple(packets)
