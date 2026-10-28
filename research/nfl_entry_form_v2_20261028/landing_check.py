"""NFL_ENTRY_FORM_V2 — §7 landing check on a NON-COUNTED slate.

Runs the full path end-to-end — design-data walk -> features -> price ->
record -> close attachment -> grade -> diagnostics — on one historical
slate (2025 Week 10), with counting REFUSED throughout, proving the
machinery works and records everything the evaluator needs before any
freeze package can propose a first counted slate (PREREG_DRAFT §7.8's
landing check, executed at build stage).

Stand-ins, disclosed on the face of the output: no DraftKings T-1H entry
snapshots exist for a historical slate (gap G7), so the entry snapshot
is the nflverse closing-snapshot line at a flat -110/-110, stamped
T-60m, and the close snapshot is the same line/prices stamped T-10m
(every row therefore grades READABLE with CLV 0 — the LINE_MOVED and
failure paths are covered by the adapter's unit tests, not here).
Starter identity comes from the games file's recorded starters
(post-hoc identity, the named leak class). Every record and the output
itself are labeled NON_COUNTED; the counted entry points are exercised
and their EF_V2_FREEZE_NOT_AUTHORIZED refusals recorded as proof.
"""
import argparse
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import design_data as dd
from sportsedge import nfl_entry_form_v2 as efv2
from sportsedge import nfl_entry_form_v2_evaluator as ev

ET = ZoneInfo("America/New_York")
SEASON, WEEK = 2025, 10


def kickoff_of(gm):
    t = gm.gametime if isinstance(gm.gametime, str) and gm.gametime else "13:00"
    hh, mm = (int(x) for x in t.split(":"))
    day = datetime.fromisoformat(str(gm.gameday)).replace(hour=hh, minute=mm)
    return day.replace(tzinfo=ET).astimezone(ZoneInfo("UTC"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default=dd.default_games_path())
    ap.add_argument("--data-dir", default=dd.default_data_dir())
    ap.add_argument("--out", default=os.path.join(dd.HERE, "landing_check_result.json"))
    args = ap.parse_args()

    dd.ensure_parquets(args.data_dir)
    games = dd.load_games(args.games)
    walk = dd.DesignWalk(games, dd.load_team_week(args.data_dir),
                         dd.load_qb_week(args.data_dir))
    walk.run_until(lambda gm: gm.season == SEASON and gm.week == WEEK)

    slate = [gm for gm in games.itertuples(index=False)
             if gm.season == SEASON and gm.week == WEEK]
    if not slate:
        raise SystemExit("slate empty — refusing")

    records, closes, results, kickoffs = [], [], {}, {}
    for gm in slate:
        ctx = dd.game_context(gm)
        ko = kickoff_of(gm)
        kickoffs[gm.game_id] = ko.isoformat()
        entry_ts = (ko - timedelta(minutes=60)).isoformat()
        close_ts = (ko - timedelta(minutes=10)).isoformat()
        quotes = {
            "SPREAD": efv2.EntryQuote(line=float(gm.spread_line),
                                      price_first=-110, price_second=-110,
                                      captured_at=entry_ts),
            "TOTAL": efv2.EntryQuote(line=float(gm.total_line),
                                     price_first=-110, price_second=-110,
                                     captured_at=entry_ts),
        }
        records.extend(efv2.price_game(walk.books, walk.qb_book, ctx, quotes))
        for market, line in (("SPREAD", float(gm.spread_line)),
                             ("TOTAL", float(gm.total_line))):
            first, second = ("HOME", "AWAY") if market == "SPREAD" \
                else ("OVER", "UNDER")
            closes.append({"game_id": gm.game_id, "market": market,
                           "line": line,
                           "prices": {first: -110, second: -110},
                           "captured_at": close_ts})
        results[gm.game_id] = {"home_score": int(gm.home_score),
                               "away_score": int(gm.away_score)}

    assert all(r["counted"] is False and r["verified_play"] is False
               for r in records), "a record escaped the NON_COUNTED stamps"
    diagnostics = ev.grade_records(records, closes, results, kickoffs)

    refusal_proof = {}
    for name, fn, call in (
            ("count_rows", ev.count_rows, lambda: ev.count_rows(records)),
            ("score_counted", ev.score_counted,
             lambda: ev.score_counted(records, closes, results, kickoffs)),
            ("verdict", ev.verdict,
             lambda: ev.verdict(records, closes, results, kickoffs))):
        try:
            call()
            refusal_proof[name] = {"raised": False}
        except ev.EFV2FreezeNotAuthorized as exc:
            refusal_proof[name] = {"raised": True, "reason": exc.reason}

    out = {
        "label": "NON_COUNTED LANDING CHECK — no freeze, no clock, no "
                 "counted rows; counting refused (EF_V2_FREEZE_NOT_AUTHORIZED)",
        "counted": False,
        "slate": {"season": SEASON, "week": WEEK, "games": len(slate),
                  "game_ids": [gm.game_id for gm in slate]},
        "standins": {
            "entry_snapshot": "nflverse closing-snapshot line, flat "
                              "-110/-110, stamped T-60m (HISTORICAL "
                              "STAND-IN — no DK T-1H snapshots exist for "
                              "historical slates, gap G7)",
            "close_snapshot": "same line/prices stamped T-10m "
                              "(HISTORICAL STAND-IN — all rows READABLE, "
                              "CLV 0; moved/failure paths are unit-tested)",
            "starter_identity": "games file recorded starters (post-hoc "
                                "identity, named leak class)",
        },
        "construction_sha256": efv2.CONSTRUCTION_SHA256,
        "constants_id": records[0]["constants_id"] if records else None,
        "n_records": len(records),
        "records": diagnostics["rows"],
        "diagnostics": diagnostics["markets"],
        "refusal_proof": refusal_proof,
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1)
    picks = {m: d["n_picks"] for m, d in diagnostics["markets"].items()}
    print(f"priced {len(slate)} games -> {len(records)} records; picks: {picks}")
    print(f"refusals: { {k: v.get('reason') for k, v in refusal_proof.items()} }")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
