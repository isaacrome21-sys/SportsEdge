#!/usr/bin/env python3
from schedule_completeness_v0_3 import derive_schedule_expectation, schedule_relative_coverage_check


def game(gid, a, h, status="Scheduled"):
    return {"game_id": gid, "away_short": a, "home_short": h, "status": status}


def snap(games, complete=True):
    return {
        "source_kind": "AUTHORITATIVE_SCHEDULE",
        "is_complete_day_snapshot": complete,
        "slate_date": "2026-08-10",
        "source_id": "mlb_schedule_2026-08-10T1300Z",
        "games": games,
    }


def main():
    # Real shortened Monday: 10 games, 20 unique clubs. Must pass at 20/20.
    teams = ["BOS","TOR","NYM","ATL","BAL","MIN","PHI","STL","TEX","LAA","TB","ATH","COL","ARI","MIL","SD","HOU","SF","KC","LAD"]
    games = [game(f"G{i+1}", teams[2*i], teams[2*i+1]) for i in range(10)]
    raw = [dict(g) for g in games]
    r = schedule_relative_coverage_check(raw, snap(games))
    assert r["pass"] and r["expected_games"] == 10 and r["expected_unique_teams"] == 20, r

    # Actual missing game/team still fails closed.
    r = schedule_relative_coverage_check(raw[:-1], snap(games))
    assert not r["pass"] and r["missing_game_ids"] == ["G10"], r

    # Athletics doubled-name relocation regression.
    games2 = [{"game_id":"A1","away_full":"Tampa Bay Rays","away_short":"TB","home_full":"Athletics Athletics","status":"Scheduled"}]
    raw2 = [{"game_id":"A1","away_short":"TB","home_full":"Athletics Athletics"}]
    r = schedule_relative_coverage_check(raw2, snap(games2))
    assert r["pass"], r

    # Doubleheader: repeated teams are valid; completeness is game-ID/appearance based.
    dh = [game("DH1","BOS","NYY"), game("DH2","BOS","NYY")]
    r = schedule_relative_coverage_check([dict(x) for x in dh], snap(dh))
    assert r["pass"] and r["expected_games"] == 2 and r["expected_unique_teams"] == 2, r

    # Postponed game remains in source snapshot but is not demanded from live candidate rows.
    mixed = [game("G1","BOS","TOR"), game("PPD","NYM","ATL",status="Postponed")]
    r = schedule_relative_coverage_check([dict(mixed[0])], snap(mixed))
    assert r["pass"] and r["expected_games"] == 1, r

    # Filtered/unattested schedule cannot be used as completeness truth.
    try:
        derive_schedule_expectation(snap(games, complete=False))
        raise AssertionError("filtered schedule incorrectly accepted")
    except ValueError:
        pass

    print("ALL SCHEDULE COMPLETENESS V0.3 TESTS PASS")


if __name__ == "__main__":
    main()
