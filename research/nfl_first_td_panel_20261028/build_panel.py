"""Build the NFL first-scoring attribution panel from pinned nflverse inputs.

Implements design step 1 of research/nfl_activation_20261027/
DESIGN_NFL_GAME_PROPS_TD_V1.md (attribution panel admission):

  per game, the credited first scorer (player + team + type) from the
  scoring plays, joined to verified player IDs, with the panel's own
  hash pin and the evidence layer's refusal classes (missing scorer
  identity, incomplete PBP, out-of-order events) applied as panel
  exclusions, counted and reported.

Labels are extracted ONLY through the merged evidence layer
(sportsedge/nfl_first_td_pbp_evidence.first_td_from_complete_pbp):
the explicit credited player on the first touchdown event, including
defensive/return scores; never inferred from the passer.

Seasons derived: 2019-2025. The admitted panel is 2020-2025 (the
design's seasons); 2019 rows are derived as PRIOR_ONLY training data
(the Part 2 calibration convention: training seasons exist outside
the scored window) and are flagged role=PRIOR_ONLY in the outputs.

Derivation rules (pinned by this script's version string):
  ORDER      plays are ordered by (period ascending,
             quarter_seconds_remaining descending, play_id) --
             the feed's event-time chronology. play_id alone
             interleaves administrative rows (timeouts, no-plays)
             whose play_id sits in the next period's id range, and
             game_seconds_remaining restarts at the overtime
             boundary; those naive orders manufacture false
             out-of-order games (49 and 121 of 1,960). The label is
             provably insensitive to the choice: the first TD under
             play_id order and under the pinned order is the same
             player in all 1,949 games with a touchdown (verified at
             admission). OUT_OF_ORDER_EVENTS applies where event
             time itself is missing: any play without a period, or
             a touchdown play without a clock stamp (a non-scoring
             play without a clock stamp is placed last within its
             period; 68 such administrative rows exist, none is a
             touchdown).
  TEAM CODES the schedules file is the fixture authority. The PBP
             feed retroactively recodes the 2019 Raiders as LV where
             the schedules file carries OAK; td_team is normalized
             per TEAM_CODE_NORMALIZATION before any identity check,
             and the panel records the fixture (schedules) code.
  COMPLETE   a game is structurally complete iff PBP rows exist,
             periods span 1..max>=4, and play count >= 100, else
             INCOMPLETE_PBP. (Completeness is asserted on these
             structural checks against the schedules file -- the
             evidence layer's own posture: provider completeness is
             an operator assertion, not independent certification.)
  IDENTITY   every touchdown play must carry td_player_id (the
             evidence packet refuses as a whole otherwise) ->
             MISSING_SCORER_IDENTITY; the credited team must be one
             of the fixture's two teams -> CREDITED_TEAM_NOT_IN_FIXTURE;
             the credited player must resolve in the pinned players
             file -> UNVERIFIED_PLAYER_ID.
  TYPE       touchdown_type is mapped from the nflverse flags:
             pass_touchdown -> RECEIVING; rush_touchdown -> RUSHING;
             return_touchdown -> INTERCEPTION_RETURN (interception
             play) / KICKOFF_RETURN (kickoff) / PUNT_RETURN (punt) /
             BLOCKED_KICK_RETURN (field_goal) / FUMBLE_RETURN (other
             return); any other touchdown -> OTHER_EXPLICIT_CREDIT.
  PACKET     each admitted game is passed through the evidence layer
             as a complete packet: scheduled start from the schedules
             file (America/New_York -> UTC); completed/observed time
             = the pinned PBP asset's own release updated_at (the
             packet was observed in that release, postgame by
             construction); source_snapshot_sha256 = the season PBP
             file's sha256. The evidence digest is stored per row.

Outputs (in --out-dir):
  first_td_panel_2019_2025.csv   one row per admitted game
  player_td_game_2019_2025.csv   every credited TD of admitted games
                                 (the construction's PIT history store)
  panel_manifest.json            input pins (full tuple + pulled
                                 sha256), output hashes, coverage and
                                 exclusion counts
Research tooling only: no pricing authority, nothing frozen.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from sportsedge.nfl_first_td_pbp_evidence import (  # noqa: E402
    FirstTDEvidenceError,
    first_td_from_complete_pbp,
)

DERIVATION_VERSION = "NFL_FIRST_TD_PANEL_DERIVATION_V1"
PANEL_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)
ALL_SEASONS = (2019,) + PANEL_SEASONS
MIN_PLAYS_PER_GAME = 100
DEF_RETURN_TYPES = frozenset({
    "INTERCEPTION_RETURN", "FUMBLE_RETURN", "KICKOFF_RETURN",
    "PUNT_RETURN", "BLOCKED_KICK_RETURN",
})

PBP_COLS = [
    "play_id", "game_id", "qtr", "quarter_seconds_remaining", "posteam",
    "td_team", "td_player_id", "td_player_name", "touchdown",
    "pass_touchdown", "rush_touchdown", "return_touchdown",
    "interception", "play_type",
]
# (season, pbp td_team) -> schedules fixture code. Same-source identity
# normalization only; the franchise is identical in both files.
TEAM_CODE_NORMALIZATION = {(2019, "LV"): "OAK"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def td_type(row) -> str:
    if row["pass_touchdown"] == 1:
        return "RECEIVING"
    if row["rush_touchdown"] == 1:
        return "RUSHING"
    if row["return_touchdown"] == 1:
        if row["interception"] == 1:
            return "INTERCEPTION_RETURN"
        if row["play_type"] == "kickoff":
            return "KICKOFF_RETURN"
        if row["play_type"] == "punt":
            return "PUNT_RETURN"
        if row["play_type"] == "field_goal":
            return "BLOCKED_KICK_RETURN"
        return "FUMBLE_RETURN"
    return "OTHER_EXPLICIT_CREDIT"


def classify_game(plays: pd.DataFrame):
    """Return (exclusion_class | None, ordered plays | None).

    Applies the structural refusal classes before any packet is built.
    """
    if plays.empty:
        return "INCOMPLETE_PBP", None
    if plays["qtr"].isna().any():
        return "OUT_OF_ORDER_EVENTS", None
    td_rows = plays[plays["touchdown"] == 1]
    if td_rows["quarter_seconds_remaining"].isna().any():
        return "OUT_OF_ORDER_EVENTS", None
    ordered = plays.sort_values(
        ["qtr", "quarter_seconds_remaining", "play_id"],
        ascending=[True, False, True], kind="mergesort",
        na_position="last")
    qtrs = ordered["qtr"].tolist()
    if any(b < a for a, b in zip(qtrs, qtrs[1:])):
        return "OUT_OF_ORDER_EVENTS", None
    if len(ordered) < MIN_PLAYS_PER_GAME or qtrs[0] != 1 or max(qtrs) < 4:
        return "INCOMPLETE_PBP", None
    tds = ordered[ordered["touchdown"] == 1]
    for _, row in tds.iterrows():
        pid = row["td_player_id"]
        if not isinstance(pid, str) or not pid.strip():
            return "MISSING_SCORER_IDENTITY", None
    return None, ordered


def build_packet(game_row, ordered: pd.DataFrame, source_sha: str,
                 observed_iso: str):
    et = ZoneInfo("America/New_York")
    start_local = datetime.combine(
        game_row["gameday"].date(),
        datetime.strptime(str(game_row["gametime"]), "%H:%M").time(),
        tzinfo=et)
    plays = []
    for idx, (_, row) in enumerate(ordered.iterrows(), 1):
        is_td = bool(row["touchdown"] == 1)
        play = {
            "source_event_id": f'{row["game_id"]}:{int(row["play_id"])}',
            "play_index": idx,
            "period": int(row["qtr"]),
            "is_touchdown": is_td,
            "source_game_id": str(row["game_id"]),
        }
        if is_td:
            play.update({
                "credited_player_id": str(row["td_player_id"]),
                "credited_team_id": str(row["td_team"]),
                "touchdown_type": td_type(row),
            })
        plays.append(play)
    return {
        "game_id": str(game_row["game_id"]),
        "scheduled_start_utc": start_local.astimezone(
            timezone.utc).isoformat(),
        "completed_at_utc": observed_iso,
        "observed_at_utc": observed_iso,
        "source_snapshot_sha256": source_sha,
        "away_team_id": str(game_row["away_team"]),
        "home_team_id": str(game_row["home_team"]),
        "final_status": "FINAL",
        "complete_play_by_play": True,
        "expected_play_count": len(plays),
        "plays": plays,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--metadata", required=True,
                    help="release metadata JSON (full pin tuples)")
    args = ap.parse_args()
    data = Path(args.data_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads(Path(args.metadata).read_text())

    pins = {}

    def pin(tag, name, path):
        asset = meta[tag]["assets"][name]
        digest = sha256_file(path)
        pins[name] = {
            "release_tag": tag,
            "release_id": meta[tag]["release_id"],
            "asset_id": asset["id"],
            "asset_name": name,
            "asset_size": asset["size"],
            "asset_updated_at": asset["updated_at"],
            "pulled_size": path.stat().st_size,
            "pulled_sha256": digest,
            "size_match": path.stat().st_size == asset["size"],
        }
        return digest

    games_sha = pin("schedules", "games.csv.gz", data / "games.csv.gz")
    players_sha = pin("players", "players.csv", data / "players.csv")
    pbp_sha, pbp_observed = {}, {}
    for s in ALL_SEASONS:
        name = f"play_by_play_{s}.csv.gz"
        pbp_sha[s] = pin("pbp", name, data / name)
        pbp_observed[s] = meta["pbp"]["assets"][name]["updated_at"]
    for s in ALL_SEASONS:
        name = f"roster_weekly_{s}.csv"
        pin("weekly_rosters", name, data / name)
    bad = [n for n, p in pins.items() if not p["size_match"]]
    if bad:
        print(f"SIZE MISMATCH vs release metadata: {bad}")
        return 1

    players = pd.read_csv(data / "players.csv", usecols=["gsis_id",
                                                         "display_name"])
    player_name = dict(zip(players["gsis_id"].astype(str),
                           players["display_name"].astype(str)))
    verified_ids = set(player_name)

    games = pd.read_csv(data / "games.csv.gz", low_memory=False)
    games = games[games["season"].isin(ALL_SEASONS)].copy()
    games["gameday"] = pd.to_datetime(games["gameday"])

    panel_rows, td_rows = [], []
    exclusions = Counter()
    excl_by_season = defaultdict(Counter)
    universe = Counter()

    for season in ALL_SEASONS:
        pbp = pd.read_csv(data / f"play_by_play_{season}.csv.gz",
                          usecols=PBP_COLS, low_memory=False)
        for (s_norm, raw_code), fixture_code in (
                TEAM_CODE_NORMALIZATION.items()):
            if s_norm == season:
                pbp["td_team"] = pbp["td_team"].replace(
                    raw_code, fixture_code)
        by_game = {gid: g for gid, g in pbp.groupby("game_id")}
        season_games = games[games["season"] == season]
        for _, grow in season_games.iterrows():
            gid = str(grow["game_id"])
            universe[season] += 1
            plays = by_game.get(gid)
            if plays is None:
                exclusions["INCOMPLETE_PBP"] += 1
                excl_by_season[season]["INCOMPLETE_PBP"] += 1
                continue
            excl, ordered = classify_game(plays)
            if excl is None:
                tds = ordered[ordered["touchdown"] == 1]
                for _, row in tds.iterrows():
                    if str(row["td_team"]) not in (
                            str(grow["away_team"]), str(grow["home_team"])):
                        excl = "CREDITED_TEAM_NOT_IN_FIXTURE"
                        break
                    if str(row["td_player_id"]) not in verified_ids:
                        excl = "UNVERIFIED_PLAYER_ID"
                        break
            if excl is not None:
                exclusions[excl] += 1
                excl_by_season[season][excl] += 1
                continue
            packet = build_packet(grow, ordered, pbp_sha[season],
                                  pbp_observed[season])
            try:
                cand = first_td_from_complete_pbp(packet)
            except FirstTDEvidenceError as err:  # pragma: no cover
                exclusions[f"EVIDENCE_REFUSAL:{err}"] += 1
                excl_by_season[season][f"EVIDENCE_REFUSAL:{err}"] += 1
                continue
            # Cross-check the evidence layer against direct derivation.
            tds = ordered[ordered["touchdown"] == 1]
            if cand.touchdown_found:
                first_row = tds.iloc[0]
                assert cand.credited_player_id == str(
                    first_row["td_player_id"])
                assert cand.scoring_team_id == str(first_row["td_team"])
                assert cand.touchdown_type == td_type(first_row)
                first_idx = int(first_row["play_id"])
                outcome = "PLAYER_TD"
                prow = {
                    "first_td_player_id": cand.credited_player_id,
                    "first_td_player_name": player_name.get(
                        cand.credited_player_id,
                        str(first_row["td_player_name"])),
                    "first_td_team": cand.scoring_team_id,
                    "first_td_type": cand.touchdown_type,
                    "first_td_period": int(first_row["qtr"]),
                    "first_td_play_id": first_idx,
                }
            else:
                assert tds.empty
                outcome = "NO_TD"
                prow = {
                    "first_td_player_id": "", "first_td_player_name": "",
                    "first_td_team": "", "first_td_type": "",
                    "first_td_period": "", "first_td_play_id": "",
                }
            panel_rows.append({
                "game_id": gid, "season": season,
                "week": int(grow["week"]),
                "season_type": str(grow["game_type"]),
                "game_date": grow["gameday"].strftime("%Y-%m-%d"),
                "away_team": str(grow["away_team"]),
                "home_team": str(grow["home_team"]),
                "outcome": outcome,
                "role": "PANEL" if season in PANEL_SEASONS else "PRIOR_ONLY",
                "evidence_sha256": cand.evidence_sha256,
                "pbp_sha256": pbp_sha[season],
                **prow,
            })
            for j, (_, row) in enumerate(tds.iterrows()):
                td_rows.append({
                    "game_id": gid, "season": season,
                    "week": int(grow["week"]),
                    "player_id": str(row["td_player_id"]),
                    "player_name": player_name.get(
                        str(row["td_player_id"]),
                        str(row["td_player_name"])),
                    "team": str(row["td_team"]),
                    "td_type": td_type(row),
                    "is_first_td": bool(cand.touchdown_found and j == 0),
                    "play_id": int(row["play_id"]),
                })

    panel = pd.DataFrame(panel_rows)
    comp = pd.DataFrame(td_rows)
    panel_path = out / "first_td_panel_2019_2025.csv"
    comp_path = out / "player_td_game_2019_2025.csv"
    panel.to_csv(panel_path, index=False)
    comp.to_csv(comp_path, index=False)

    manifest = {
        "derivation_version": DERIVATION_VERSION,
        "evidence_module": "sportsedge/nfl_first_td_pbp_evidence.py",
        "panel_seasons": list(PANEL_SEASONS),
        "prior_only_seasons": [2019],
        "inputs": pins,
        "outputs": {
            panel_path.name: {
                "sha256": sha256_file(panel_path), "rows": len(panel)},
            comp_path.name: {
                "sha256": sha256_file(comp_path), "rows": len(comp)},
        },
        "coverage": {
            str(s): {
                "games_in_schedules": int(universe[s]),
                "admitted": int((panel["season"] == s).sum()),
                "exclusions": dict(excl_by_season[s]),
            } for s in ALL_SEASONS
        },
        "exclusions_total": dict(exclusions),
        "outcome_counts": {
            str(s): dict(Counter(
                panel[panel["season"] == s]["outcome"]))
            for s in ALL_SEASONS
        },
    }
    (out / "panel_manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(json.dumps({
        "panel_rows": len(panel), "companion_rows": len(comp),
        "exclusions": dict(exclusions),
        "coverage": manifest["coverage"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
