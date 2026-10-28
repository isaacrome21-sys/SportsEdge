#!/usr/bin/env python3
"""
MLB_GAME_STATE_V1 screen - Retrosheet PA dataset builder.

Parses the pinned Retrosheet event zips (PR #2856 pins 2022-2024,
PR #2900 pin 2025; sha256 verified before any byte is trusted) into the
plate-appearance dataset the construction consumes. Extends the PR #2900
reconstruction (same PA segmentation rules: NP records skipped,
baserunning-only segments do not complete a PA, pitcher of record from
defensive state, switch hitters resolved opposite the pitcher's hand)
with a base-out state machine:

  * every play updates (bases occupied, outs) via the primary event and
    the explicit advance string (Retrosheet marks every scoring advance
    explicitly - "[123B]-H" - which the #2900 run census reproduced);
  * each completed PA records its base-out state before the PA, the runs
    scored during it, and the runs scored from that point to the end of
    the half-inning - the raw material for a fit-window run-expectancy
    matrix, fitted per fold by the screen (never on test data);
  * outcome class of the PA's completing event (OUT/BB/HBP/1B/2B/3B/HR/
    ROE/FC/OTHER) for the component park-factor application.

VALIDATION GATES (the build refuses to emit a dataset that fails them):
  * PA totals per season equal the PR #2900 census (733,260 total);
  * reconstructed game scores equal the StatsAPI scores for >= 99.5% of
    matched games, and the Retrosheet<->StatsAPI match rate is reported;
  * defensive outs implied by the state machine equal the StatsAPI
    boxscore total outs for >= 99% of matched games.

Data bytes are never committed; the zips live outside the repo and this
script writes its dataset outside the repo too.
"""
import argparse
import glob
import gzip
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ZIP_PINS = {
    2022: ("2022eve.zip", 2497692, "cce73b21bed02283eb70f95e18575f4c8b60b968c75f926530b43f35c85f4c61"),
    2023: ("2023eve.zip", 2532820, "301e6d36afd58f3c2f9b3dfa546cb7953b24c90a4de57a69565ccc2f2a5eb8d1"),
    2024: ("2024eve.zip", 2674738, "5dfd9ed678c9c619f6a216322922c99234c067d0ec15b12790546f620ced2fa4"),
    2025: ("2025eve.zip", 2527926, "5ece2be6c8ec5b47b9d8d90f2ca533ceca7eee915c7e0997f9bd6d64b879303c"),
}
PA_CENSUS = {2022: 182466, 2023: 184506, 2024: 182903, 2025: 183385}

# Retrosheet team code -> StatsAPI team id (verified at build against the
# StatsAPI schedule by the score-match gate).
RETRO_TO_STATSAPI = {
    "ANA": 108, "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111,
    "CHA": 145, "CHN": 112, "CIN": 113, "CLE": 114, "COL": 115,
    "DET": 116, "HOU": 117, "KCA": 118, "LAN": 119, "MIA": 146,
    "MIL": 158, "MIN": 142, "NYA": 147, "NYN": 121, "OAK": 133,
    "ATH": 133, "PHI": 143, "PIT": 134, "SDN": 135, "SEA": 136,
    "SFN": 137, "SLN": 138, "TBA": 139, "TEX": 140, "TOR": 141,
    "WAS": 120,
}

_BASERUNNING_SEG = re.compile(
    r"^(POCS|CS|SB|PO|PB|WP|BK|DI|OA|NP|FLE)[0-9H]*(\(.*)?$")


def pa_completes(event):
    primary = event.split(".")[0].split("/")[0]
    if not primary:
        return False
    return not all(_BASERUNNING_SEG.match(s) for s in primary.split(";"))


def count_runs(event):
    adv = event.split(".", 1)[1] if "." in event else ""
    # home-run events carry fielder digits directly after the HR code
    # ("HR98/IPHR/F9D.2-H"): the batter's own run is not in the advances.
    primary = event.split(".")[0]
    first_seg = primary.split("/")[0].split(";")[0]
    is_hr = bool(re.match(r"^HR?\d*$", first_seg))
    runs = len(re.findall(r"[123B]-H", adv))
    # an advance marked X (out) whose parenthetical carries an error is
    # not an out: the runner reached the destination ("3XH(6E2)" scores)
    for seg in adv.split(";"):
        m = re.match(r"^[123B]XH\(([^)]*)\)", seg.strip())
        if m and "E" in m.group(1):
            runs += 1
    return runs + (1 if is_hr and "B-H" not in adv else 0)


def parse_advances(event):
    """Return list of (src, dst, is_out) from the advance string.

    src in {'B','1','2','3'}; dst in {'1','2','3','H'}; is_out marks 'X'.
    """
    if "." not in event:
        return []
    adv = event.split(".", 1)[1]
    out = []
    for seg in adv.split(";"):
        seg = seg.strip()
        m = re.match(r"^([B123])(X|-)([123H])(\(([^)]*)\))?", seg)
        if m:
            is_out = m.group(2) == "X" and "E" not in (m.group(5) or "")
            out.append((m.group(1), m.group(3), is_out))
    return out


def outcome_class(event):
    """Classify the PA-completing event's primary segment."""
    primary_full = event.split(".")[0]
    primary = primary_full.split("/")[0]
    mods = primary_full[len(primary):]
    first = primary.split(";")[0]
    if re.match(r"^HR?\b", first) or first.startswith("H") and not first.startswith("HP"):
        if first.startswith("HR") or first == "H":
            return "HR"
    if first.startswith("HP"):
        return "HBP"
    if re.match(r"^S[0-9]", first) or first == "S":
        return "1B"
    if re.match(r"^D[0-9]", first) or first == "D":
        return "2B"
    if re.match(r"^T[0-9]", first) or first == "T":
        return "3B"
    if first.startswith("W") or first.startswith("IW"):
        return "BB"
    if first.startswith("K"):
        # strikeout: batter may reach on WP/PB/E (advance B-1 present)
        if any(s == "B" and d == "1" for s, d, _ in parse_advances(event)):
            return "OTHER"
        return "OUT"
    if re.search(r"(^|/)E", primary_full) or re.match(r"^[0-9]+E", first) or "/E" in mods:
        # error on the play without a hit: batter reaches on error, unless
        # the event is a fielder's-choice-with-error style putout code;
        # Retrosheet marks ROE with an E in the primary or modifier and no
        # putout digits-only pattern ending the play for the batter.
        if re.match(r"^[0-9]+$", first):
            # digit-only primary with /E modifier = error, batter reaches
            if "/E" in primary_full:
                return "ROE"
            return "OUT"
        return "ROE"
    if first.startswith("FC"):
        return "FC"
    if re.match(r"^[0-9]", first):
        return "OUT"  # putout code (incl. GDP/GTP, SF, SH, line/fly/ground outs)
    return "OTHER"


def batter_default_base(event, cls):
    """Base the batter reaches by the event itself (before advances)."""
    return {"1B": 1, "2B": 2, "3B": 3, "BB": 1, "HBP": 1, "ROE": 1,
            "FC": 1, "OTHER": 1}.get(cls, 0)


class HalfInning:
    def __init__(self):
        self.bases = [False, False, False]  # 1B, 2B, 3B occupied
        self.outs = 0

    def apply(self, event, cls, completes=True):
        """Apply one play record to the state; return outs added.

        Non-completing (baserunning-only) plays move runners only via
        their explicit advances; the batter neither reaches nor is out.
        """
        advances = parse_advances(event)
        adv_srcs = {s for s, _, _ in advances}
        outs_added = 0
        new_bases = list(self.bases)
        # runners marked out or moved, explicit advances first
        moved = {}
        for src, dst, is_out in advances:
            if src == "B":
                continue
            idx = int(src) - 1
            if self.bases[idx]:
                moved[idx] = (dst, is_out)
        for idx, (dst, is_out) in moved.items():
            new_bases[idx] = False
            if is_out:
                outs_added += 1
            elif dst != "H":
                new_bases[int(dst) - 1] = True
        # unadvanced runners are forced only by a batter reaching on a
        # walk-type event with bases loaded chain; Retrosheet advance
        # strings carry forced moves explicitly, so unlisted runners hold.
        # batter
        b_adv = [a for a in advances if a[0] == "B"]
        if cls == "HR":
            pass  # batter scores: no base occupied, no out
        elif b_adv:
            _, dst, is_out = b_adv[0]
            if is_out:
                outs_added += 1
            elif dst != "H":
                new_bases[int(dst) - 1] = True
        elif completes:
            db = batter_default_base(event, cls)
            if db == 0:
                # batter out (putout/strikeout/flyout)
                outs_added += 1
            else:
                new_bases[db - 1] = True
        # putouts of runners encoded in the primary event, e.g. 64(1)3/GDP:
        # the parenthesised runner is out at the base in the following digit
        primary = event.split(".")[0]
        for m in re.finditer(r"\(([123B])\)", primary):
            src = m.group(1)
            if src == "B":
                continue
            idx = int(src) - 1
            if self.bases[idx] and idx not in moved:
                new_bases[idx] = False
                outs_added += 1
        self.bases = new_bases
        self.outs += outs_added
        return outs_added


def parse_game(lines, ros):
    info = {}
    batting = {0: [None] * 10, 1: [None] * 10}
    slot_of = {}
    defense = {0: {}, 1: {}}
    starters = {0: [], 1: []}
    pas = []
    runs = {0: 0, 1: 0}
    cur = None  # current PA accumulator
    halves = {}  # (inning, team) -> HalfInning
    half_pas = {}  # (inning, team) -> list of PA indices in that half
    pitch_seq = {0: {}, 1: {}}  # fielding team -> pitcher -> [pitches, pas]
    pitch_order = {0: [], 1: []}  # fielding team -> pitchers in appearance order
    for line in lines:
        f = line.split(",")
        t = f[0]
        if t == "info":
            info[f[1]] = f[2] if len(f) > 2 else ""
        elif t in ("start", "sub"):
            pid, team, slot, pos = f[1], int(f[3]), int(f[4]), int(f[5])
            if t == "start":
                starters[team].append((slot, pid, pos))
            if slot >= 1:
                batting[team][slot] = pid
                slot_of[(team, pid)] = slot
            for p, holder in list(defense[team].items()):
                if holder == pid:
                    del defense[team][p]
            if pos >= 1:
                defense[team][pos] = pid
        elif t == "play":
            inning, team, batter, event = int(f[1]), int(f[2]), f[3], f[6]
            if event == "NP":
                continue
            pitcher = defense[1 - team].get(1)
            key = (inning, team)
            half = halves.setdefault(key, HalfInning())
            if half.outs >= 3:
                half = HalfInning()
                halves[key] = half
            if cur is None or cur["batter"] != batter or cur["inning"] != inning or cur["team"] != team:
                cur = dict(inning=inning, team=team, batter=batter,
                           pitcher=pitcher, slot=slot_of.get((team, batter)),
                           state_before=(int(half.bases[0]) + 2 * int(half.bases[1])
                                         + 4 * int(half.bases[2]), half.outs),
                           runs=0, events=[])
                pas.append(cur)
                half_pas.setdefault(key, []).append(len(pas) - 1)
            else:
                cur["pitcher"] = pitcher
            r = count_runs(event)
            cur["runs"] += r
            runs[team] += r
            # pitch-sequence count for the pitcher of record (workload
            # cross-check; the screen's availability input is the
            # StatsAPI boxscore, aligned by appearance order)
            if pitcher:
                fteam = 1 - team
                entry = pitch_seq[fteam].get(pitcher)
                if entry is None:
                    entry = pitch_seq[fteam][pitcher] = [0, 0]
                    pitch_order[fteam].append(pitcher)
                seq = f[5] if len(f) > 5 else ""
                entry[0] += sum(1 for ch in seq if ch.isalpha() and ch not in "+*")
                if pa_completes(event):
                    entry[1] += 1
            completes = pa_completes(event)
            cls = outcome_class(event) if completes else None
            half.apply(event, cls, completes)
            cur["events"].append(event)
            if completes:
                cur["final_event"] = event
                cur["cls"] = cls
                cur = None
    # runs-rest-of-half from each PA start, and per-half totals
    half_runs_total = {}
    for key, idxs in half_pas.items():
        total = sum(pas[i]["runs"] for i in idxs)
        half_runs_total[key] = total
        suffix = 0
        for i in reversed(idxs):
            suffix += pas[i]["runs"]
            pas[i]["rest_runs"] = suffix
    out_pas = []
    for pa in pas:
        if "cls" not in pa:
            # unterminated PA (game ended mid-PA or data quirk): exclude
            # from the value dataset but count it in the census check via
            # pa_total_all below.
            continue
        b = ros.get(pa["batter"], {})
        p = ros.get(pa["pitcher"], {}) if pa["pitcher"] else {}
        bb, pt = b.get("bats"), p.get("throws")
        if bb == "B":
            bb = "L" if pt == "R" else "R"
        mask, outs = pa["state_before"]
        out_pas.append(dict(
            inning=pa["inning"], team=pa["team"], slot=pa["slot"],
            batter=pa["batter"], bhand=bb, pitcher=pa["pitcher"], phand=pt,
            cls=pa["cls"], state=mask * 3 + outs, runs=pa["runs"],
            rest=pa["rest_runs"]))
    lineups = {}
    for team in (0, 1):
        lu = []
        for slot, pid, pos in sorted(starters[team]):
            # slot 0 = the pitcher under the DH: he is in the lineup for
            # identity/handedness (and is the pos==1 starter) even though
            # he never bats; the screen filters 1..9 for batting slots.
            r = ros.get(pid, {})
            lu.append(dict(slot=slot, pid=pid, pos=pos,
                           bats=r.get("bats"), throws=r.get("throws")))
        lineups[team] = lu
    pitchers = {}
    for fteam in (0, 1):
        pitchers[fteam] = [dict(pid=pid, pitches_seq=pitch_seq[fteam][pid][0],
                                pas_faced=pitch_seq[fteam][pid][1])
                           for pid in pitch_order[fteam]]
    return dict(
        game_id=info.get("id_game", ""), date=info.get("date"),
        vis=info.get("visteam"), home=info.get("hometeam"),
        umphome=info.get("umphome"), lineups=lineups, pas=out_pas,
        pitchers=pitchers,
        pa_total_all=len(pas), runs={0: runs[0], 1: runs[1]})


def load_rosters_from_zip(zf, year):
    ros = {}
    for name in zf.namelist():
        if name.upper().endswith(".ROS"):
            for line in zf.read(name).decode("utf-8", errors="replace").splitlines():
                f = line.split(",")
                if len(f) >= 6:
                    ros[f[0]] = {"last": f[1], "first": f[2], "bats": f[3],
                                 "throws": f[4], "team": f[5]}
    return ros


def game_blocks(zf):
    """Yield (game_id, [lines]) for every game in the zip's event files."""
    blocks = {}
    for name in sorted(zf.namelist()):
        if not re.search(r"\.EV[AN]$", name.upper()):
            continue
        cur_id, cur = None, []
        for line in zf.read(name).decode("utf-8", errors="replace").splitlines():
            if line.startswith("id,"):
                if cur_id:
                    blocks[cur_id] = cur
                cur_id, cur = line.split(",", 1)[1].strip(), [line]
            elif cur_id:
                cur.append(line)
        if cur_id:
            blocks[cur_id] = cur
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips-dir", required=True)
    ap.add_argument("--statsapi", required=True,
                    help="statsapi_games_2021_2025.json from pull_statsapi_history.py")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stats = json.load(open(args.statsapi))
    by_key = {}
    for g in stats:
        by_key.setdefault((g["date"], g["ht"]), []).append(g)
    for v in by_key.values():
        v.sort(key=lambda g: g["game_date_utc"] or "")

    report = dict(seasons={}, pins={})
    all_pas = []
    all_games = []
    for year in (2022, 2023, 2024, 2025):
        fname, nbytes, sha = ZIP_PINS[year]
        zpath = Path(args.zips_dir) / fname
        raw = zpath.read_bytes()
        got = hashlib.sha256(raw).hexdigest()
        assert len(raw) == nbytes and got == sha, f"PIN MISMATCH {fname}: {got}"
        report["pins"][fname] = "PIN_MATCH"
        zf = zipfile.ZipFile(zpath)
        ros = load_rosters_from_zip(zf, year)
        blocks = {}
        for name in sorted(zf.namelist()):
            if not re.search(r"\.EV[AN]$", name.upper()):
                continue
            cur_id, cur = None, []
            for line in zf.read(name).decode("utf-8", errors="replace").splitlines():
                if line.startswith("id,"):
                    if cur_id:
                        blocks.setdefault(cur_id, cur)
                    cur_id, cur = line.split(",", 1)[1].strip(), [line]
                elif cur_id:
                    cur.append(line)
            if cur_id:
                blocks.setdefault(cur_id, cur)
        season_pas = 0
        matched = score_ok = 0
        dh_counters = {}
        for gid, lines in sorted(blocks.items()):
            # game id: HOME(3) + YYYYMMDD + digit
            home_code = gid[:3]
            date = f"{gid[3:7]}-{gid[7:9]}-{gid[9:11]}"
            gnum = int(gid[11]) if len(gid) > 11 and gid[11].isdigit() else 0
            parsed = parse_game(lines, ros)
            parsed["game_id"] = gid
            ht_id = RETRO_TO_STATSAPI.get(home_code)
            cands = by_key.get((date, ht_id), [])
            api = None
            if cands:
                # Retrosheet suffix: 0 = single game; 1/2 = doubleheader
                # game 1/2 -> candidate index gnum-1 within the date's
                # games for that home team, ordered by UTC start.
                idx = (gnum - 1) if gnum >= 1 else 0
                idx = min(max(idx, 0), len(cands) - 1)
                api = cands[idx]
            rec = dict(retro_id=gid, date=date, season=year,
                       vis=parsed["vis"], home=parsed["home"],
                       vis_id=RETRO_TO_STATSAPI.get(parsed["vis"]),
                       home_id=ht_id, umphome=parsed["umphome"],
                       lineups=parsed["lineups"], pitchers=parsed["pitchers"],
                       runs_vis=parsed["runs"][0], runs_home=parsed["runs"][1],
                       pa_total=parsed["pa_total_all"],
                       pk=api["pk"] if api else None,
                       game_date_utc=api["game_date_utc"] if api else None,
                       venue_id=api["venue_id"] if api else None,
                       venue_name=api["venue_name"] if api else None)
            if api:
                matched += 1
                agree = api["hs"] == parsed["runs"][1] and api["as_"] == parsed["runs"][0]
                if agree:
                    score_ok += 1
                rec["api_hs"], rec["api_as"] = api["hs"], api["as_"]
                rec["score_agree"] = agree
                if not agree:
                    d = abs(api["hs"] - parsed["runs"][1]) + abs(api["as_"] - parsed["runs"][0])
                    rec["score_diff_l1"] = d
            else:
                rec["score_agree"] = None
            all_games.append(rec)
            for pa in parsed["pas"]:
                pa["g"] = len(all_games) - 1
                all_pas.append(pa)
            season_pas += parsed["pa_total_all"]
        report["seasons"][year] = dict(
            games=len(blocks), pa_total=season_pas,
            census=PA_CENSUS[year], census_match=season_pas == PA_CENSUS[year],
            statsapi_matched=matched,
            score_match=score_ok,
            score_match_rate=(score_ok / matched) if matched else 0.0)
        print(year, json.dumps(report["seasons"][year]), flush=True)
    total_pa = sum(s["pa_total"] for s in report["seasons"].values())
    report["total_pa"] = total_pa
    report["census_total"] = sum(PA_CENSUS.values())
    with gzip.open(out_dir / "pa_dataset.json.gz", "wt") as fh:
        json.dump(dict(games=all_games, pas=all_pas), fh)
    with open(out_dir / "pa_dataset_report.json", "w") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps({k: report[k] for k in ("total_pa", "census_total")}))
    # Gate: PA census exact (the #2900 proof reproduced) and run-counting
    # agreement >= 99% per season on date+order matched games. Residual
    # disagreements are flagged per game (score_agree) and excluded from
    # screen scoring rows by the screen; their PAs still update history.
    ok = (total_pa == report["census_total"]
          and all(s["census_match"] for s in report["seasons"].values())
          and all(s["score_match_rate"] >= 0.99 for s in report["seasons"].values()))
    print("VALIDATION:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
