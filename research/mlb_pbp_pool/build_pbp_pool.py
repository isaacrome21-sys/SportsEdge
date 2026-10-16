"""MLB plate-appearance (PA) play-by-play pool builder — stage 1.

Builds the verified, PIT-disciplined PA pool described in DESIGN.md
from MLB StatsAPI play-by-play (free, no key), reconciling EVERY game
against the official StatsAPI box score before the game is admitted.

Usage:
    python3 build_pbp_pool.py build [--seasons 2024,2025,2026]
        [--out DIR] [--cache-dir DIR] [--boxscore-cache DIR]
        [--workers 8] [--limit N] [--sample-per-season 10]
    python3 build_pbp_pool.py verify --out DIR --manifest MANIFEST.json
        [--boxscore-cache DIR]

The pool artifact is deterministic: rows sorted by
(game_date, game_id, pa_index), JSON with sorted keys and fixed
separators, gzip with mtime=0. Rebuilding from the same source
reproduces the artifact byte-for-byte; the manifest records SHA-256
of both the gzip bytes and the uncompressed JSONL.

No pricing, no engines, no gate/registry state is touched by this
script. It reads box scores from the shared sandbox cache read-only
and writes only under --out and --cache-dir.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

API = "https://statsapi.mlb.com/api/v1"
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "SportsEdge research pbp-pool/1.0 (stage-1 foundation)"}

# ---------------------------------------------------------------------------
# Outcome classification (DESIGN.md). The builder fails closed on any
# event type not in this table.
# ---------------------------------------------------------------------------
OUTCOME_CLASS = {
    "single": "HIT_SINGLE",
    "double": "HIT_DOUBLE",
    "triple": "HIT_TRIPLE",
    "home_run": "HOME_RUN",
    "walk": "WALK",
    "intent_walk": "INTENT_WALK",
    "hit_by_pitch": "HIT_BY_PITCH",
    "strikeout": "STRIKEOUT",
    "strikeout_double_play": "STRIKEOUT",
    "strikeout_triple_play": "STRIKEOUT",
    "sac_fly": "SAC_FLY",
    "sac_fly_double_play": "SAC_FLY",
    "sac_bunt": "SAC_BUNT",
    "sac_bunt_double_play": "SAC_BUNT",
    "catcher_interf": "INTERFERENCE",
    "batter_interf": "INTERFERENCE",
    "fan_interf": "INTERFERENCE",
    "field_error": "REACH_ON_ERROR",
    "fielders_choice": "FIELDERS_CHOICE",
    "fielders_choice_out": "FIELDERS_CHOICE",
    "field_out": "OUT_IN_PLAY",
    "force_out": "OUT_IN_PLAY",
    "grounded_into_double_play": "OUT_IN_PLAY",
    "double_play": "OUT_IN_PLAY",
    "triple_play": "OUT_IN_PLAY",
    "other_out": "OUT_IN_PLAY",
}
HIT_CLASSES = {"HIT_SINGLE", "HIT_DOUBLE", "HIT_TRIPLE", "HOME_RUN"}

ROW_FIELDS = (
    "game_id", "season", "game_date", "game_completed_date", "game_type",
    "away_team_id", "home_team_id", "pa_index", "at_bat_index",
    "inning", "half", "batting_team_id", "fielding_team_id",
    "batter_id", "pitcher_id", "bat_side", "pitch_hand",
    "batting_order_slot", "batter_pa_number", "pitcher_bf_number",
    "event_type", "outcome_class",
    "is_hit", "is_home_run", "is_walk", "is_intent_walk",
    "is_hit_by_pitch", "is_strikeout", "is_sac_fly", "is_sac_bunt",
    "result_is_out", "rbi", "runs_scored_on_play", "scoring_runner_ids",
    "outs_after", "away_score_after", "home_score_after",
)


class PoolError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Fetching (cache-first, resumable)
# ---------------------------------------------------------------------------

def _fetch_json(url: str, cache_path: str, *, retries: int = 4) -> dict:
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as resp:
                payload = json.load(resp)
            tmp = cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, cache_path)
            return payload
        except Exception as err:  # noqa: BLE001 - retried, then raised
            last_err = err
            time.sleep(1.5 * (attempt + 1))
    raise PoolError(f"fetch failed after {retries} tries: {url}: {last_err}")


def enumerate_games(season: int, cache_dir: str) -> tuple[list[int], dict[int, list[str]], int]:
    """Distinct Final regular-season gamePks for a season.

    The schedule endpoint lists some games twice (original date +
    makeup date); enumeration is by distinct gamePk. Returns
    (game_ids, official_dates_by_game, non_final_count)."""
    path = os.path.join(cache_dir, f"schedule_{season}.json")
    sched = _fetch_json(
        f"{API}/schedule?sportId=1&season={season}&gameType=R", path)
    dates: dict[int, list[str]] = {}
    non_final = 0
    for day in sched.get("dates", []):
        for game in day.get("games", []):
            pk = int(game["gamePk"])
            if game.get("status", {}).get("abstractGameState") != "Final":
                non_final += 1
                continue
            dates.setdefault(pk, [])
            if game["officialDate"] not in dates[pk]:
                dates[pk].append(game["officialDate"])
    return sorted(dates), dates, non_final


# ---------------------------------------------------------------------------
# PA identification and row derivation
# ---------------------------------------------------------------------------

def is_pa_play(play: dict) -> bool:
    """The load-bearing PA rule (DESIGN.md): a real plate appearance
    iff the play is a completed atBat AND the batter's own runner
    record is resolved on it. Baserunning plays during someone
    else's PA (inning-ending caught stealing, pickoffs) satisfy the
    first two conditions but never the third."""
    if play.get("result", {}).get("type") != "atBat":
        return False
    if not play.get("about", {}).get("isComplete"):
        return False
    batter_id = play.get("matchup", {}).get("batter", {}).get("id")
    return any(
        r.get("details", {}).get("runner", {}).get("id") == batter_id
        for r in play.get("runners", []))


def _et_date(iso_ts: str) -> str:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(ET).date().isoformat()


def derive_game_rows(game_id: int, season: int, feed: dict) -> tuple[list[dict], list[dict], dict]:
    """Derive pool rows for one game from its playByPlay payload.

    Returns (rows, orphans, stats). Orphans are runs scored on
    non-PA plays (a wild pitch or a caught-stealing throw that
    scores a runner during / between plate appearances): they
    belong to no plate appearance, so they are carried in a side
    table rather than folded into a PA row — folding would
    mis-attribute the run to whichever PA the entry sits beside,
    and team totals cannot detect that error (they are invariant
    under which row carries the run). Every feed entry's score
    delta must equal its own movement scorers; that invariant is
    verified here for PA and non-PA entries alike."""
    plays = feed.get("allPlays", [])
    if not plays:
        raise PoolError(f"game {game_id}: empty allPlays")
    first_ts = plays[0]["about"]["startTime"]
    last_ts = plays[-1]["about"].get("endTime") or plays[-1]["about"]["startTime"]
    game_date = _et_date(first_ts)
    completed_date = _et_date(last_ts)

    rows: list[dict] = []
    orphans: list[dict] = []
    team_pa_ordinal = {"top": 0, "bottom": 0}
    batter_pa_count: dict[int, int] = {}
    pitcher_bf_count: dict[int, int] = {}
    stats = {"incomplete_plays": 0, "non_pa_complete_plays": 0,
             "feed_outs_by_half": {}}
    prev_total = 0
    for pos, play in enumerate(plays):
        half = play["about"]["halfInning"]
        key = f"{play['about']['inning']}:{half}"
        if play.get("about", {}).get("isComplete"):
            stats["feed_outs_by_half"].setdefault(key, []).append(
                int(play["count"]["outs"]))
        play_scorers = [int(r["details"]["runner"]["id"])
                        for r in play.get("runners", [])
                        if r.get("movement", {}).get("end") == "score"]
        play_total = int(play["result"]["awayScore"]) + int(play["result"]["homeScore"])
        if play_total - prev_total != len(play_scorers):
            raise PoolError(
                f"game {game_id}: feed delta invariant violated at play "
                f"{pos} (delta {play_total - prev_total} != scorers "
                f"{len(play_scorers)})")
        prev_total = play_total
        if not is_pa_play(play):
            if not play.get("about", {}).get("isComplete"):
                stats["incomplete_plays"] += 1
            elif play.get("result", {}).get("type") == "atBat":
                stats["non_pa_complete_plays"] += 1
            if play_scorers:
                orphans.append({
                    "game_id": game_id,
                    "season": season,
                    "game_date": game_date,
                    "game_completed_date": completed_date,
                    "play_index": pos,
                    "inning": int(play["about"]["inning"]),
                    "half": half,
                    "batting_team_id": None,  # attached from box score
                    "event_type": play["result"].get("eventType"),
                    "runs": len(play_scorers),
                    "scoring_runner_ids": play_scorers,
                })
            continue
        matchup = play["matchup"]
        result = play["result"]
        event_type = result["eventType"]
        if event_type not in OUTCOME_CLASS:
            raise PoolError(f"game {game_id}: unmapped eventType {event_type!r}")
        outcome = OUTCOME_CLASS[event_type]
        ordinal = team_pa_ordinal[half]
        team_pa_ordinal[half] += 1
        batter_id = int(matchup["batter"]["id"])
        pitcher_id = int(matchup["pitcher"]["id"])
        batter_pa_count[batter_id] = batter_pa_count.get(batter_id, 0) + 1
        pitcher_bf_count[pitcher_id] = pitcher_bf_count.get(pitcher_id, 0) + 1
        scoring = play_scorers  # this PA's own resolution scorers only
        away_after = int(result["awayScore"])
        home_after = int(result["homeScore"])
        runs = len(scoring)
        rows.append({
            "game_id": game_id,
            "season": season,
            "game_date": game_date,
            "game_completed_date": completed_date,
            "game_type": "R",
            "away_team_id": None,  # attached by caller from box score
            "home_team_id": None,
            "pa_index": len(rows),
            "at_bat_index": int(play["about"]["atBatIndex"]),
            "inning": int(play["about"]["inning"]),
            "half": half,
            "batting_team_id": None,
            "fielding_team_id": None,
            "batter_id": batter_id,
            "pitcher_id": pitcher_id,
            "bat_side": matchup.get("batSide", {}).get("code"),
            "pitch_hand": matchup.get("pitchHand", {}).get("code"),
            "batting_order_slot": (ordinal % 9) + 1,
            "batter_pa_number": batter_pa_count[batter_id],
            "pitcher_bf_number": pitcher_bf_count[pitcher_id],
            "event_type": event_type,
            "outcome_class": outcome,
            "is_hit": outcome in HIT_CLASSES,
            "is_home_run": outcome == "HOME_RUN",
            "is_walk": outcome in ("WALK", "INTENT_WALK"),
            "is_intent_walk": outcome == "INTENT_WALK",
            "is_hit_by_pitch": outcome == "HIT_BY_PITCH",
            "is_strikeout": outcome == "STRIKEOUT",
            "is_sac_fly": outcome == "SAC_FLY",
            "is_sac_bunt": outcome == "SAC_BUNT",
            "result_is_out": bool(result.get("isOut")),
            "rbi": int(result.get("rbi", 0)),
            "runs_scored_on_play": runs,
            "scoring_runner_ids": scoring,
            "outs_after": int(play["count"]["outs"]),
            "away_score_after": away_after,
            "home_score_after": home_after,
        })
    if not rows:
        raise PoolError(f"game {game_id}: no PA rows derived")
    return rows, orphans, stats


def minimize_boxscore(boxscore: dict) -> dict:
    """The sample-fixture extract of a box score: exactly the fields
    the reconciliation contract reads (team ids, team batting
    totals, per-player battingOrder codes). Full-fidelity
    reconciliation runs against the real box scores at build /
    verify time; the shipped fixture is this extract so the sample
    stays small."""
    out = {"teams": {}}
    for side in ("away", "home"):
        team = boxscore["teams"][side]
        players = {key: {"battingOrder": p["battingOrder"]}
                   for key, p in team["players"].items()
                   if "battingOrder" in p}
        out["teams"][side] = {
            "team": {"id": team["team"]["id"]},
            "teamStats": {"batting": team["teamStats"]["batting"]},
            "players": players,
        }
    return out


def attach_teams(rows: list[dict], orphans: list[dict], boxscore: dict) -> None:
    away_id = int(boxscore["teams"]["away"]["team"]["id"])
    home_id = int(boxscore["teams"]["home"]["team"]["id"])
    for row in rows:
        row["away_team_id"] = away_id
        row["home_team_id"] = home_id
        if row["half"] == "top":
            row["batting_team_id"] = away_id
            row["fielding_team_id"] = home_id
        else:
            row["batting_team_id"] = home_id
            row["fielding_team_id"] = away_id
    for orphan in orphans:
        orphan["batting_team_id"] = away_id if orphan["half"] == "top" else home_id


# ---------------------------------------------------------------------------
# Reconciliation against the official box score (DESIGN.md contract)
# ---------------------------------------------------------------------------

def _team_batting(boxscore: dict, side: str) -> dict:
    return boxscore["teams"][side]["teamStats"]["batting"]


def _slot_codes(boxscore: dict, side: str) -> dict[int, str]:
    codes = {}
    for key, player in boxscore["teams"][side]["players"].items():
        if "battingOrder" in player:
            codes[int(key[2:])] = str(player["battingOrder"])
    return codes


def reconcile_game(rows: list[dict], orphans: list[dict], boxscore: dict,
                   feed_stats: dict) -> list[str]:
    """All integrity checks for one game. Returns a list of failure
    strings (empty = the game is admitted). Team runs are checked
    as PA-resolution runs + orphan (non-PA) runs vs the box score."""
    failures: list[str] = []
    sides = {"top": "away", "bottom": "home"}
    for half, side in sides.items():
        grows = [r for r in rows if r["half"] == half]
        gorphans = [o for o in orphans if o["half"] == half]
        bat = _team_batting(boxscore, side)
        pa_box = int(bat["plateAppearances"])
        if len(grows) != pa_box:
            failures.append(f"{side} PA {len(grows)} != box {pa_box}")
        components = (
            int(bat["atBats"]) + int(bat["baseOnBalls"]) + int(bat["hitByPitch"])
            + int(bat["sacFlies"]) + int(bat["sacBunts"])
            + int(bat.get("catchersInterference") or 0))
        if components != pa_box:
            failures.append(f"{side} PA components {components} != PA {pa_box}")
        totals = {
            "hits": sum(1 for r in grows if r["is_hit"]),
            "homeRuns": sum(1 for r in grows if r["is_home_run"]),
            "baseOnBalls": sum(1 for r in grows if r["is_walk"]),
            "strikeOuts": sum(1 for r in grows if r["is_strikeout"]),
            "rbi": sum(r["rbi"] for r in grows),
            "runs": (sum(r["runs_scored_on_play"] for r in grows)
                     + sum(o["runs"] for o in gorphans)),
        }
        for name, got in totals.items():
            if got != int(bat[name]):
                failures.append(f"{side} {name} pool {got} != box {bat[name]}")
        codes = _slot_codes(boxscore, side)
        for r in grows:
            code = codes.get(r["batter_id"])
            if code is None:
                failures.append(f"{side} batter {r['batter_id']} has no box battingOrder code")
                break
            if int(code[0]) != r["batting_order_slot"]:
                failures.append(
                    f"{side} slot mismatch batter {r['batter_id']}: pool "
                    f"{r['batting_order_slot']} vs box code {code}")
                break
    # Final score anchor: the last pool row's running score plus any
    # orphan runs scored after it (a game can end on an orphan play,
    # e.g. a walk-off wild pitch during an unresolved final PA) must
    # equal the box-score runs for each team. (The per-team totals
    # check above already covers the full-game sum; this anchors the
    # running-score fields themselves.)
    last = rows[-1]
    for side, field in (("away", "away_score_after"), ("home", "home_score_after")):
        team_id = last["away_team_id"] if side == "away" else last["home_team_id"]
        trailing = sum(o["runs"] for o in orphans
                       if o["play_index"] > last["at_bat_index"]
                       and o["batting_team_id"] == team_id)
        box_runs = int(_team_batting(boxscore, side)["runs"])
        if last[field] + trailing != box_runs:
            failures.append(
                f"final {side} score pool {last[field]} + trailing orphans "
                f"{trailing} != box {box_runs}")
    # Outs progression over the full feed (incl. non-PA plays): within
    # each half, outs non-decreasing, steps of 0..3, ending at exactly
    # 3 except in the game's final half-inning.
    # Order halves chronologically: (inning, top before bottom).
    halves = sorted(feed_stats["feed_outs_by_half"].items(),
                    key=lambda kv: (int(kv[0].split(":")[0]), 0 if kv[0].endswith("top") else 1))
    for idx, (key, seq) in enumerate(halves):
        for a, b in zip(seq, seq[1:]):
            if b < a or b - a > 3:
                failures.append(f"outs progression {key}: {a} -> {b}")
                break
        if seq and seq[-1] != 3 and idx != len(halves) - 1:
            failures.append(f"half {key} ends at {seq[-1]} outs (not final half)")
    # Row-level sanity.
    for r in rows:
        if r["runs_scored_on_play"] != len(r["scoring_runner_ids"]):
            failures.append("runs_scored_on_play != len(scoring_runner_ids)")
            break
        if r["rbi"] > r["runs_scored_on_play"]:
            failures.append("rbi > runs_scored_on_play")
            break
        if not (0 <= r["outs_after"] <= 3):
            failures.append("outs_after out of range")
            break
    return failures


# ---------------------------------------------------------------------------
# Schema validation (used by verify mode and the test suite)
# ---------------------------------------------------------------------------

def validate_row(row: dict) -> list[str]:
    errs = []
    if tuple(sorted(row.keys())) != tuple(sorted(ROW_FIELDS)):
        errs.append(f"fields {sorted(row.keys())} != schema")
        return errs
    ints = ("game_id", "season", "pa_index", "at_bat_index", "inning",
            "away_team_id", "home_team_id", "batting_team_id",
            "fielding_team_id", "batter_id", "pitcher_id",
            "batting_order_slot", "batter_pa_number", "pitcher_bf_number",
            "rbi", "runs_scored_on_play", "outs_after",
            "away_score_after", "home_score_after")
    for f in ints:
        if not isinstance(row[f], int) or isinstance(row[f], bool):
            errs.append(f"{f} not int")
    if row["half"] not in ("top", "bottom"):
        errs.append("half invalid")
    if not (1 <= row["batting_order_slot"] <= 9):
        errs.append("slot out of range")
    if row["outcome_class"] != OUTCOME_CLASS.get(row["event_type"]):
        errs.append("outcome_class inconsistent with event_type")
    if row["game_completed_date"] < row["game_date"]:
        errs.append("completed before start date")
    bools = ("is_hit", "is_home_run", "is_walk", "is_intent_walk",
             "is_hit_by_pitch", "is_strikeout", "is_sac_fly",
             "is_sac_bunt", "result_is_out")
    for f in bools:
        if not isinstance(row[f], bool):
            errs.append(f"{f} not bool")
    if row["is_hit"] != (row["outcome_class"] in HIT_CLASSES):
        errs.append("is_hit inconsistent")
    if row["is_walk"] != (row["outcome_class"] in ("WALK", "INTENT_WALK")):
        errs.append("is_walk inconsistent")
    if not isinstance(row["scoring_runner_ids"], list):
        errs.append("scoring_runner_ids not a list")
    return errs


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_jsonl_gz(rows: list[dict], out_path: str) -> tuple[str, str, int]:
    """Deterministic gzip JSONL write; returns (gz sha256, jsonl
    sha256, gz bytes)."""
    buf = io.BytesIO()
    plain_hash = hashlib.sha256()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        for row in rows:
            line = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
            plain_hash.update(line)
            gz.write(line)
    data = buf.getvalue()
    with open(out_path, "wb") as fh:
        fh.write(data)
    return _sha256_bytes(data), plain_hash.hexdigest(), len(data)


_write_pool = _write_jsonl_gz


def build_game(game_id: int, season: int, cache_dir: str, boxscore_cache: str) -> dict:
    feed = _fetch_json(f"{API}/game/{game_id}/playByPlay",
                       os.path.join(cache_dir, f"pbp_{game_id}.json"))
    box_path = os.path.join(boxscore_cache, f"{game_id}.json")
    if os.path.exists(box_path):
        with open(box_path, "r", encoding="utf-8") as fh:
            boxscore = json.load(fh)
    else:
        boxscore = _fetch_json(f"{API}/game/{game_id}/boxscore",
                               os.path.join(cache_dir, f"box_{game_id}.json"))
    rows, orphans, stats = derive_game_rows(game_id, season, feed)
    attach_teams(rows, orphans, boxscore)
    failures = reconcile_game(rows, orphans, boxscore, stats)
    return {"game_id": game_id, "rows": rows, "orphans": orphans,
            "stats": stats, "failures": failures, "boxscore": boxscore}


def cmd_build(args: argparse.Namespace) -> int:
    seasons = [int(s) for s in args.seasons.split(",")]
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.cache_dir, exist_ok=True)
    manifest: dict = {
        "artifact": "mlb_pbp_pool",
        "stage": 1,
        "source": "MLB StatsAPI playByPlay + boxscore (statsapi.mlb.com)",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "builder_file": os.path.basename(__file__),
        "builder_sha256": _sha256_bytes(open(__file__, "rb").read()),
        "pit_rule": "pool game G feeds target T only if G.game_completed_date < T.game_date",
        "seasons": {},
    }
    report: list[str] = ["# MLB PBP Pool — Build Report", ""]
    sample_rows: list[dict] = []
    sample_boxes: dict[str, dict] = {}

    for season in seasons:
        game_ids, official_dates, non_final = enumerate_games(season, args.cache_dir)
        if args.limit:
            game_ids = game_ids[: args.limit]
        # Fetch phase (parallel, cache-first). Failures are tolerated
        # here: the build phase re-fetches and excludes the game
        # fail-closed if the feed is truly unavailable.
        def _warm(gid: int) -> None:
            try:
                _fetch_json(f"{API}/game/{gid}/playByPlay",
                            os.path.join(args.cache_dir, f"pbp_{gid}.json"))
            except Exception:  # noqa: BLE001 - build phase adjudicates
                pass

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(_warm, game_ids))
        # cache is warm; build phase reads from cache
        season_rows: list[dict] = []
        season_orphans: list[dict] = []
        excluded: list[tuple[int, list[str]]] = []
        census: dict[str, int] = {}
        tot_incomplete = tot_nonpa = 0
        date_exceptions = 0
        multi_date = 0
        game_dates: dict[int, tuple[str, str]] = {}
        built_games: list[dict] = []
        for gid in game_ids:
            try:
                result = build_game(gid, season, args.cache_dir, args.boxscore_cache)
            except Exception as err:  # noqa: BLE001 - fail-closed per game
                excluded.append((gid, [f"{type(err).__name__}: {err}"]))
                continue
            tot_incomplete += result["stats"]["incomplete_plays"]
            tot_nonpa += result["stats"]["non_pa_complete_plays"]
            rows0 = result["rows"][0]
            game_dates[gid] = (rows0["game_date"], rows0["game_completed_date"])
            if rows0["game_date"] not in official_dates.get(gid, []):
                date_exceptions += 1
            if rows0["game_completed_date"] != rows0["game_date"]:
                multi_date += 1
            if result["failures"]:
                excluded.append((gid, result["failures"]))
                continue
            for r in result["rows"]:
                census[r["event_type"]] = census.get(r["event_type"], 0) + 1
            season_rows.extend(result["rows"])
            season_orphans.extend(result["orphans"])
            built_games.append(result)
        season_rows.sort(key=lambda r: (r["game_date"], r["game_id"], r["pa_index"]))
        season_orphans.sort(key=lambda o: (o["game_date"], o["game_id"], o["play_index"]))
        out_name = f"pool_{season}.jsonl.gz"
        gz_hash, plain_hash, nbytes = _write_pool(
            season_rows, os.path.join(args.out, out_name))
        orph_name = f"pool_orphans_{season}.jsonl.gz"
        o_gz, o_plain, o_bytes = _write_jsonl_gz(
            season_orphans, os.path.join(args.out, orph_name))
        manifest["seasons"][str(season)] = {
            "file": out_name,
            "rows": len(season_rows),
            "games_admitted": len(built_games),
            "games_excluded": len(excluded),
            "sha256_gz": gz_hash,
            "sha256_jsonl": plain_hash,
            "bytes_gz": nbytes,
            "first_game_date": season_rows[0]["game_date"] if season_rows else None,
            "last_game_date": season_rows[-1]["game_date"] if season_rows else None,
            "orphans_file": orph_name,
            "orphan_rows": len(season_orphans),
            "orphan_runs": sum(o["runs"] for o in season_orphans),
            "orphans_sha256_gz": o_gz,
            "orphans_sha256_jsonl": o_plain,
            "orphans_bytes_gz": o_bytes,
        }
        report += [
            f"## {season}",
            f"- games enumerated (distinct Final R): {len(game_ids)} "
            f"(non-Final schedule entries ignored: {non_final})",
            f"- games admitted: {len(built_games)}; excluded: {len(excluded)}",
            f"- pool rows (PAs): {len(season_rows)}",
            f"- incomplete plays excluded (not PAs): {tot_incomplete}",
            f"- non-PA complete plays excluded (baserunning during a PA): {tot_nonpa}",
            f"- games whose derived game_date is not a schedule officialDate: {date_exceptions}",
            f"- orphan scoring plays (runs on non-PA plays, side table): "
            f"{len(season_orphans)} plays, {sum(o['runs'] for o in season_orphans)} runs "
            f"-> {orph_name}",
            f"- games ending on a later ET date than they started "
            f"(post-midnight finishes incl. suspended/resumed): {multi_date}",
            f"- artifact: {out_name} ({nbytes} bytes gz)",
            f"  - sha256(gz): `{gz_hash}`",
            f"  - sha256(jsonl): `{plain_hash}`",
            "- event-type census (admitted games):",
        ]
        for et, n in sorted(census.items(), key=lambda kv: -kv[1]):
            report.append(f"  - {et}: {n}")
        if excluded:
            report.append("- EXCLUDED games (fail-closed):")
            for gid, fails in excluded:
                report.append(f"  - {gid}: {'; '.join(fails[:4])}")
        report.append("")
        # Sample: evenly spaced admitted games across the season.
        if built_games and args.sample_per_season:
            built_games.sort(key=lambda g: (g["rows"][0]["game_date"], g["game_id"]))
            step = max(1, len(built_games) // args.sample_per_season)
            picks = built_games[::step][: args.sample_per_season]
            for g in picks:
                sample_rows.extend(g["rows"])
                sample_boxes[str(g["game_id"])] = {
                    "boxscore": minimize_boxscore(g["boxscore"]),
                    "feed_outs_by_half": g["stats"]["feed_outs_by_half"],
                    "orphans": g["orphans"],
                }
    # Sample excerpt + fixture (for the in-repo test suite).
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    sample_dir = os.path.join(pkg_dir, "sample")
    os.makedirs(sample_dir, exist_ok=True)
    with open(os.path.join(sample_dir, "pool_sample.jsonl"), "w", encoding="utf-8") as fh:
        for r in sorted(sample_rows, key=lambda r: (r["game_date"], r["game_id"], r["pa_index"])):
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    with open(os.path.join(sample_dir, "sample_boxscores.json"), "w", encoding="utf-8") as fh:
        json.dump(sample_boxes, fh)
    manifest["sample"] = {
        "games": len(sample_boxes),
        "rows": len(sample_rows),
        "pool_file": "sample/pool_sample.jsonl",
        "boxscore_fixture": "sample/sample_boxscores.json",
        "sha256_jsonl": _sha256_bytes(
            open(os.path.join(sample_dir, "pool_sample.jsonl"), "rb").read()),
    }
    with open(os.path.join(args.out, "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    with open(os.path.join(pkg_dir, "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    with open(os.path.join(pkg_dir, "BUILD_REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    print(json.dumps({s: manifest["seasons"][s] for s in manifest["seasons"]}, indent=1))
    print(f"sample: {manifest['sample']}")
    return 0


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def cmd_verify(args: argparse.Namespace) -> int:
    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    problems: list[str] = []
    for season, info in manifest["seasons"].items():
        path = os.path.join(args.out, info["file"])
        raw = open(path, "rb").read()
        if _sha256_bytes(raw) != info["sha256_gz"]:
            problems.append(f"{season}: gz hash mismatch")
            continue
        text = gzip.decompress(raw).decode("utf-8")
        if _sha256_bytes(text.encode()) != info["sha256_jsonl"]:
            problems.append(f"{season}: jsonl hash mismatch")
            continue
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        if len(rows) != info["rows"]:
            problems.append(f"{season}: row count {len(rows)} != {info['rows']}")
        for r in rows:
            errs = validate_row(r)
            if errs:
                problems.append(f"{season}: schema: {errs[0]} (game {r.get('game_id')})")
                break
        # Orphan side table: hash + load.
        oraw = open(os.path.join(args.out, info["orphans_file"]), "rb").read()
        if _sha256_bytes(oraw) != info["orphans_sha256_gz"]:
            problems.append(f"{season}: orphans gz hash mismatch")
            continue
        otext = gzip.decompress(oraw).decode("utf-8")
        if _sha256_bytes(otext.encode()) != info["orphans_sha256_jsonl"]:
            problems.append(f"{season}: orphans jsonl hash mismatch")
            continue
        orphans = [json.loads(line) for line in otext.splitlines() if line.strip()]
        if len(orphans) != info["orphan_rows"]:
            problems.append(f"{season}: orphan count {len(orphans)} != {info['orphan_rows']}")
        orphans_by_game: dict[int, list[dict]] = {}
        for o in orphans:
            orphans_by_game.setdefault(o["game_id"], []).append(o)
        # Per-game reconciliation from cached box scores.
        by_game: dict[int, list[dict]] = {}
        for r in rows:
            by_game.setdefault(r["game_id"], []).append(r)
        if len(by_game) != info["games_admitted"]:
            problems.append(f"{season}: games {len(by_game)} != {info['games_admitted']}")
        n_fail = 0
        for gid, grows in by_game.items():
            box_path = os.path.join(args.boxscore_cache, f"{gid}.json")
            if not os.path.exists(box_path):
                problems.append(f"{season}: no cached boxscore for {gid}")
                continue
            with open(box_path, "r", encoding="utf-8") as fh:
                boxscore = json.load(fh)
            # Rebuild the feed-level outs sequence from pool rows only:
            # verify mode checks row-level invariants that do not need
            # the feed (PA counts, totals, slots, finals, sanity).
            stats = {"feed_outs_by_half": {}}
            fails = [f for f in reconcile_game(
                grows, orphans_by_game.get(gid, []), boxscore, stats)
                if not f.startswith("outs progression")
                and not f.startswith("half ")]
            if fails:
                n_fail += 1
                if n_fail <= 5:
                    problems.append(f"{season} game {gid}: {fails[:2]}")
        print(f"{season}: {len(rows)} rows, {len(by_game)} games re-reconciled, "
              f"{n_fail} reconciliation failures")
    if problems:
        print("VERIFY FAILED:")
        for p in problems:
            print(" -", p)
        return 1
    print("VERIFY OK: hashes, schema, and box-score reconciliation all pass")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--seasons", default="2024,2025,2026")
    b.add_argument("--out", default=os.path.expanduser(
        "~/workspace/sportsedge/mlb_pbp_pool_20261016"))
    b.add_argument("--cache-dir", default=os.path.expanduser(
        "~/workspace/tmp/bt_data/pbp_cache"))
    b.add_argument("--boxscore-cache", default=os.path.expanduser(
        "~/workspace/tmp/bt_data/boxscore_cache"))
    b.add_argument("--workers", type=int, default=8)
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--sample-per-season", type=int, default=10)
    v = sub.add_parser("verify")
    v.add_argument("--out", default=os.path.expanduser(
        "~/workspace/sportsedge/mlb_pbp_pool_20261016"))
    v.add_argument("--manifest", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "MANIFEST.json"))
    v.add_argument("--boxscore-cache", default=os.path.expanduser(
        "~/workspace/tmp/bt_data/boxscore_cache"))
    args = parser.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(args)
    return cmd_verify(args)


if __name__ == "__main__":
    sys.exit(main())
