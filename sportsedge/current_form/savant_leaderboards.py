"""Baseball Savant public leaderboards (free, keyless CSV).

Savant's leaderboard pages serve CSV twins via ?csv=true. Wired here:
the Expected Statistics leaderboard (batter and pitcher) -- the
current-form signal is the gap between expected and actual outcomes
(est_woba - woba, est_ba - ba, est_slg - slg): a hitter running far
below his expected line is producing better contact than his results,
and vice versa. Pitch-level Statcast is already wired separately in
sportsedge/mlb_savant_features.py; this module is deliberately only
the leaderboard surface and does not duplicate it.

Verified live 2026-10-27: expected-statistics batter CSV (2026,
qualified) sha256 6e261fb91d7c5656b5805f6fcea3052e6894b2fdba13e787999c39f403532803;
pitcher CSV sha256 cf503494a1559ea058df78d5f30120028c993d4af5d2ab964213f9b76e106232;
the custom leaderboard endpoint also serves CSV (sha256
29bd051e12d5aa9472d01f531529246e9d0731c2d7942f570a2baae5a20566b5).

POINT-IN-TIME NOTE: Savant leaderboards are season-to-date as of the
pull; they carry no as-of timestamp of their own. The fetcher stamps
retrieval time + sha256, and the factoring spec requires pulls to be
archived pre-game; a leaderboard pulled after first pitch may not be
used for that game.

RESEARCH-ONLY: labeled context only.
"""
from __future__ import annotations

from typing import Any

from .common import Opener, fetch_bytes, parse_csv_body, receipt_of, require_columns, to_float, to_int

SAVANT = "https://baseballsavant.mlb.com/leaderboard"
EXPECTED_COLUMNS = [
    "player_id",
    "year",
    "pa",
    "ba",
    "est_ba",
    "est_ba_minus_ba_diff",
    "slg",
    "est_slg",
    "est_slg_minus_slg_diff",
    "woba",
    "est_woba",
    "est_woba_minus_woba_diff",
]


def expected_statistics(
    *, entity: str, season: int, min_plate_appearances: str = "q", opener: Opener | None = None
) -> dict[str, Any]:
    """Expected-vs-actual leaderboard for batters or pitchers.

    Returns per-player rows with the published expected-minus-actual
    differentials (Savant computes them; we pass them through and add
    no formula of our own).
    """
    if entity not in ("batter", "pitcher"):
        return {"status": "MISSING", "reason": "SAVANT_UNKNOWN_ENTITY"}
    url = (
        f"{SAVANT}/expected_statistics?type={entity}&year={season}"
        f"&position=&team=&min={min_plate_appearances}&csv=true"
    )
    result = fetch_bytes(url, opener=opener)
    if result["status"] != "OK":
        return result
    try:
        rows = parse_csv_body(result["body"])
    except Exception:
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    if not require_columns(rows, EXPECTED_COLUMNS):
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    players: dict[str, dict[str, Any]] = {}
    for row in rows:
        player_id = to_int(row.get("player_id"))
        if player_id is None:
            continue
        players[str(player_id)] = {
            "name": row.get("last_name, first_name"),
            "pa_or_bf": to_int(row.get("pa")),
            "ba": to_float(row.get("ba")),
            "est_ba": to_float(row.get("est_ba")),
            "est_ba_minus_ba": to_float(row.get("est_ba_minus_ba_diff")),
            "slg": to_float(row.get("slg")),
            "est_slg": to_float(row.get("est_slg")),
            "est_slg_minus_slg": to_float(row.get("est_slg_minus_slg_diff")),
            "woba": to_float(row.get("woba")),
            "est_woba": to_float(row.get("est_woba")),
            "est_woba_minus_woba": to_float(row.get("est_woba_minus_woba_diff")),
        }
    return {
        "status": "OK",
        "source": "Baseball Savant expected statistics leaderboard (CSV)",
        "label": "RESEARCH_CONTEXT_ONLY",
        "entity": entity,
        "season": season,
        "receipt": receipt_of(result),
        "players": players,
    }
