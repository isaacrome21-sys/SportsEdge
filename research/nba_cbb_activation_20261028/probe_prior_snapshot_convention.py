#!/usr/bin/env python3
"""Witness probes for AMENDMENT_1 — the PRIOR-SNAPSHOT convention.

Companion to AMENDMENT_1.md in this directory (design:
CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md, PR #2843). Attempt 3 of
the CBB_TORVIK_EFFICIENCY_V1 design screen (PR #2873,
SCREEN_REPORT_ATTEMPT3.md) proved the pinned BartTorvik archive files
are END-OF-DAY snapshots: the file for date D already reflects games
played ON D, contradicting PR #2832's as-of rule 2 and the design's
section 1 morning-of premise. AMENDMENT_1 declares the carry-forward
that PR #2832 rule 4 reserves to a declared design amendment:

    for games on date D, the Torvik input is the archive file
    dated D-1 (PRIOR-SNAPSHOT convention).

This script VERIFIES that convention. It does NOT run the section 3
screen and fits nothing.

EXECUTION HISTORY (kept on the record, not hidden). The first
execution of this probe used as its expected entering record a
"CBR-resolver basis" — games whose opponent resolves through PR
#2871's published resolver. It failed 11 of 19 probes, and every
failure was traced to the probe's own basis, not to the convention:

  * Torvik's record column is the school's full record over the
    pinned substrate's games (all opponents), NOT the
    resolver-resolvable subset. The resolver cannot resolve ordinary
    D1 surfaces the CBR tables lack ("Miami", "St. John's",
    "Nicholls", "Hawai'i", "Loyola Chicago", "Charleston",
    "Tarleton", "San Jose State", ...), so the resolver basis
    undercounts entering records by exactly those games. On the
    all-games basis the 2019-20 final-date probe (51 teams) matches
    file D-1 EXACTLY, 51/51, with the file-to-file delta also exact.
  * Two genuine deviations survived the basis correction, both
    classified below with named games (a D2 opponent Torvik does
    not carry; one fixture the hoopR substrate omits and the CBR
    leg supplies). Neither touches a game played on a probe date D.
  * Penn State was absent from the slug map because Torvik's
    surface is "Penn St.", a form the published table lacks — a
    name gap, closed here by declared surface identification,
    corroborated by exact record agreement (see SURFACE_CANDIDATES).
  * One overseas game (Harvard @ Stanford, Shanghai, 2016-11-11 US
    date) is filed by Torvik under the local date 2016-11-12 — a
    dating edge in the CONSERVATIVE direction (later, never
    earlier), classified below, never counted as cleanliness
    evidence for file D.

DECLARED PROBE SET AND GATES (this execution). The convention's
as-of content is the boundary claim: file D-1 holds every result
strictly before D and NO result from D. Gates, per probe:

  DELTA GATE (basis-free, absolute): for every checked team,
  file D record == file D-1 record + that team's result in its
  game on D. Any violation fails the probe.
  EQUALITY GATE: file D-1 record == the entering record computed
  from the pinned hoopR substrate (ALL games with date < D). A
  deviation is classified, never silently passed:
    EXPLAINED_NON_UNIVERSE_OPPONENT — the deviation equals exactly
      the W-L of games vs opponents outside Torvik's universe (the
      opponent's surface resolves to no slug and no Torvik surface
      in that season's files matches its name family): Torvik does
      not carry those schools.
    EXPLAINED_SUBSTRATE_OMISSION — file D-1 has MORE games than
      the substrate entering record, and the difference equals
      exactly fixtures present in the CBR leg for that team/season
      before D with no substrate game for the team on that date:
      the substrate omits the fixture; the third leg catches it.
    UNEXPLAINED_DEVIATION — anything else: FAIL.

  W1  Attempt-3 witness set A: G = 2014-11-14. Featured Duke,
      Kentucky, Wisconsin: equality + delta gates, file G-1 total
      games == 0, and attempt 3's fingerprints reproduce at 3dp
      (Wisconsin adj_d 90.405 -> 89.118; Kentucky adj_o
      117.724 -> 117.434).
  W2  Attempt-3 witness set B: G = 2023-03-12 (Big Ten final):
      Purdue and Penn State, equality + delta gates.
  F1  First playing date of every design season (9 probes): file
      G-1 total games == 0 (the whole file is pre-season), plus the
      file-D spot check — every both-resolved game on G shows
      winner 1-0 / loser 0-1 in file G; a violation is classified
      DATING_EDGE_LATE_INCLUSION iff file G shows BOTH teams at
      their pre-game state AND file G+1 shows both at exactly
      their substrate record through G+1 (the game was filed
      under a later date — conservative direction), else FAIL.
  T1  Championship date of every season that has one (8 probes):
      both finalists, equality + delta gates.
  L1  Declared substitute for 2019-20 (no championship game —
      tournament cancelled, the true record): G = 2020-03-11, the
      final playing date (34 games, 68 team-slots). Every resolved
      team-slot: equality + delta gates. PASS requires zero
      UNEXPLAINED deviations, zero delta violations, and >= 90%
      of team-slots resolved.

IDENTIFICATION. Teams are keyed by CBR slug through PR #2871's
published resolver (NORMALIZATION_OVERRIDES + CBR's own surface
tables). If a slug is absent from a Torvik file's slug map, the
probe tries SURFACE_CANDIDATES (title-cased slug; " State" ->
" St." variant) against the file's raw surfaces; a candidate is
accepted only if exactly one surface matches and it resolves to
no other slug, and every use is printed in the result JSON. The
identification is corroborated by the record gates themselves.
This is probe machinery only — it widens NO screen gate; the
screen keeps the published table only.

INPUT PINS. hoopR CSVs verified against the PR #2867 manifest and
CBR bytes against the PR #2871 manifest before use; the Torvik
pull for 2023-03-12 must reproduce PR #2832's recorded sample
SHA-256 exactly (anchor). Torvik files are pulled at the PR #2832
pinned commit into a local cache OUTSIDE the repo; every file's
SHA-256 and byte count are recorded in the result JSON. The repo
stores hashes and code only (PR #2832 section 5 precedent).

Exit codes: 0 = every probe PASS (convention verified);
1 = a probe FAILed (the amendment must not land);
2 = an input pin refused.
"""

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import sys
import unicodedata
import urllib.request
from datetime import date, timedelta
from pathlib import Path

PACKET = Path(__file__).resolve().parent
REPO_ROOT = PACKET.parents[1]
CBR_PACKET = (REPO_ROOT / "research" /
              "cbb_cbr_schedule_mirror_successor_20261028")
HOOPR_MANIFEST_PATH = (REPO_ROOT / "research" /
                       "cbb_hoopr_mbb_schedule_successor_20261028" /
                       "successor_manifest.json")
TORVIK_PINNED_COMMIT = "46d1036443ca452fdd1c6cf25cf5dff50de68337"
TORVIK_URL_PATTERN = ("https://raw.githubusercontent.com/andreweatherman/"
                      "toRvik-data/" + TORVIK_PINNED_COMMIT +
                      "/ratings/archive/by_date/ratings_archive_{date}.csv")
TORVIK_ANCHOR = {"date": "2023-03-12",
                 "sha256": "9524481d69c7b690200299387690654091565ef1d3"
                           "df774ca858749e5e1cc01c"}
SEASON_LABEL = {2015: "2014-15", 2016: "2015-16", 2017: "2016-17",
                2018: "2017-18", 2019: "2018-19", 2020: "2019-20",
                2021: "2020-21", 2022: "2021-22", 2023: "2022-23"}


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def refuse(label, detail):
    print(json.dumps({"refusal": "SOURCE_CHANGED_AFTER_SNAPSHOT",
                      "input": label, "detail": detail}))
    sys.exit(2)


def load_d3w():
    spec = importlib.util.spec_from_file_location(
        "derive_three_way_proof", CBR_PACKET / "derive_three_way_proof.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_hoopr(year, hoopr_dir, manifest, resolve):
    name = f"mbb_schedule_{year}.csv"
    pin = next(s for s in manifest["samples"] if s["asset_name"] == name)
    raw = (hoopr_dir / name).read_bytes()
    if sha256(raw) != pin["sha256"]:
        refuse(name, "hoopr bytes differ from PR #2867 manifest pin")
    rows = []
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        try:
            hs, as_ = int(row["home_score"]), int(row["away_score"])
        except (TypeError, ValueError):
            continue
        rows.append({"date": row["game_date"],
                     "home_loc": row["home_location"],
                     "away_loc": row["away_location"],
                     "home_slug": resolve(row["home_location"]),
                     "away_slug": resolve(row["away_location"]),
                     "home_score": hs, "away_score": as_})
    rows.sort(key=lambda r: r["date"])
    return rows


def surface_candidates(slug):
    titled = slug.replace("-", " ").title()
    out = [titled]
    if titled.endswith(" State"):
        out.append(titled[: -len(" State")] + " St.")
    if slug == "connecticut":
        out.append("UConn")
    return out


class TorvikStore:
    def __init__(self, cache_dir, resolve):
        self.cache_dir = cache_dir
        self.resolve = resolve
        self.files = {}

    def fetch(self, day):
        key = day.isoformat()
        if key in self.files:
            return self.files[key]
        path = self.cache_dir / f"ratings_archive_{key.replace('-', '')}.csv"
        if path.exists():
            raw = path.read_bytes()
        else:
            url = TORVIK_URL_PATTERN.format(date=key.replace("-", ""))
            req = urllib.request.Request(
                url, headers={"User-Agent": "sportsedge-admission-probe"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
            except Exception as exc:
                self.files[key] = {"missing": True, "error": str(exc)[:120]}
                return self.files[key]
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        header = list(rows[0].keys()) if rows else []
        rec_key = "record" if "record" in header else (
            "rec" if "rec" in header else None)
        layout = "standard" if rec_key == "record" else "drift_rec"
        if "date" in header:
            bad = sum(1 for r in rows if r["date"] != key)
            if bad:
                refuse(key, f"{bad} rows carry a different date field")
        by_slug, surfaces = {}, {}
        total_games = 0
        for r in rows:
            w, l = (int(x) for x in r[rec_key].split("-"))
            total_games += w + l
            surfaces[r["team"]] = {"record": (w, l),
                                   "adj_o": r.get("adj_o"),
                                   "adj_d": r.get("adj_d")}
            slug = self.resolve(r["team"])
            if slug is not None:
                by_slug[slug] = surfaces[r["team"]]
        entry = {"missing": False, "sha256": sha256(raw),
                 "bytes": len(raw), "team_rows": len(rows),
                 "layout": layout, "total_games": total_games,
                 "by_slug": by_slug, "surfaces": surfaces,
                 "surface_identifications": {}}
        self.files[key] = entry
        return entry

    def record_for(self, entry, slug):
        """(record, how) — slug map, else declared surface candidates."""
        if entry.get("missing"):
            return None, "FILE_MISSING"
        if slug in entry["by_slug"]:
            return entry["by_slug"][slug]["record"], "slug"
        hits = [s for s in surface_candidates(slug)
                if s in entry["surfaces"]
                and self.resolve(s) in (None, slug)]
        if len(hits) == 1:
            entry["surface_identifications"][slug] = hits[0]
            return entry["surfaces"][hits[0]]["record"], f"surface:{hits[0]}"
        return None, "UNRESOLVED"


def entering_all(rows, slug, before):
    w = l = 0
    for r in rows:
        if r["date"] >= before:
            break
        if slug not in (r["home_slug"], r["away_slug"]):
            continue
        won = (r["home_score"] > r["away_score"]) == (slug == r["home_slug"])
        if won:
            w += 1
        else:
            l += 1
    return (w, l)


def add_result(rec, won):
    return (rec[0] + 1, rec[1]) if won else (rec[0], rec[1] + 1)


def fmt(rec):
    return f"{rec[0]}-{rec[1]}" if rec else None


def norm_surface(s):
    """Light orthographic normal form — used ONLY to test whether an
    opponent surface exists in Torvik's own team list (accents,
    apostrophes, periods and case folded). Never used to join data."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace("'", "").replace(".", "")
                    .replace("-", " ").split())


def classify_deviation(rows, slug, before, got, expected,
                       season_surfaces_norm, derive_cbr_fixtures,
                       team_dates):
    """Classify an equality-gate deviation; None means UNEXPLAINED."""

    def in_universe(opp_loc):
        # Torvik carries the school if a surface matches the
        # substrate's name family: exact normal form, or one side a
        # word-boundary prefix of the other ("Miami" vs Torvik's
        # "Miami FL"; "Tarleton" vs "Tarleton State").
        n = norm_surface(opp_loc)
        return any(s == n or s.startswith(n + " ")
                   or n.startswith(s + " ")
                   for s in season_surfaces_norm)

    # (a) games vs opponents outside Torvik's universe
    red_w = red_l = 0
    non_universe_games = []
    for r in rows:
        if r["date"] >= before:
            break
        if slug not in (r["home_slug"], r["away_slug"]):
            continue
        is_home = slug == r["home_slug"]
        opp_loc = r["away_loc"] if is_home else r["home_loc"]
        opp_slug = r["away_slug"] if is_home else r["home_slug"]
        if opp_slug is None and not in_universe(opp_loc):
            won = (r["home_score"] > r["away_score"]) == is_home
            if won:
                red_w += 1
            else:
                red_l += 1
            non_universe_games.append(
                {"date": r["date"], "opponent_surface": opp_loc,
                 "result": "W" if won else "L"})
    if (expected[0] - red_w, expected[1] - red_l) == got and \
            non_universe_games:
        return {"class": "EXPLAINED_NON_UNIVERSE_OPPONENT",
                "games": non_universe_games}
    # (b) substrate omission supplied by the CBR leg: fixtures the
    # CBR derivation pairs for this team before `before` on dates
    # where the substrate has no game for the team.
    if got[0] + got[1] > expected[0] + expected[1]:
        fixtures = derive_cbr_fixtures()
        missing = []
        for (fdate, pair), scores in sorted(fixtures.items()):
            if fdate >= before or slug not in pair or fdate in team_dates:
                continue
            opp = pair[0] if pair[1] == slug else pair[1]
            missing.append({"date": fdate, "opponent": opp,
                            "won": scores[slug] > scores[opp]})
        mw = sum(1 for g in missing if g["won"])
        ml = len(missing) - mw
        if (expected[0] + mw, expected[1] + ml) == got and missing:
            return {"class": "EXPLAINED_SUBSTRATE_OMISSION",
                    "games": missing}
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cbr-dir", default=str(
        Path.home() / "workspace/cbb-cbr-successor-admission-20261028/pulls"))
    parser.add_argument("--hoopr-dir", default=str(
        Path.home() / "workspace/cbb-successor-admission-20261028/pulls"))
    parser.add_argument("--torvik-cache", default=str(
        Path.home() / "workspace/cbb-amendment1-20261028/torvik_probe_cache"))
    parser.add_argument("--out", default=str(
        PACKET / "prior_snapshot_probe_results.json"))
    args = parser.parse_args()

    d3w = load_d3w()
    cbr_dir = Path(args.cbr_dir)
    cbr_manifest = json.loads(
        (CBR_PACKET / "successor_manifest.json").read_text(encoding="utf-8"))
    hoopr_manifest = json.loads(HOOPR_MANIFEST_PATH.read_text(encoding="utf-8"))
    resolve = d3w.build_resolver(cbr_dir, cbr_manifest)
    store = TorvikStore(Path(args.torvik_cache), resolve)

    anchor = store.fetch(date(2023, 3, 12))
    if anchor.get("missing") or anchor["sha256"] != TORVIK_ANCHOR["sha256"]:
        refuse("ratings_archive_20230312.csv",
               "pull does not reproduce the PR #2832 admission sample")

    seasons = {year: load_hoopr(year, Path(args.hoopr_dir),
                                hoopr_manifest, resolve)
               for year in range(2015, 2024)}
    derive_cache = {}

    def derive_cbr(year):
        if year not in derive_cache:
            fixtures, _ = d3w.derive_fixtures(year, cbr_dir,
                                              cbr_manifest, resolve)
            derive_cache[year] = fixtures
        return derive_cache[year]

    def season_surfaces_norm(year, rows):
        last = date.fromisoformat(rows[-1]["date"])
        entry = store.fetch(last)
        return {norm_surface(s) for s in entry.get("surfaces", {})}

    def team_check(year, gameday, slug, game):
        rows = seasons[year]
        before = gameday.isoformat()
        expected = entering_all(rows, slug, before)
        is_home = slug == game["home_slug"]
        won = (game["home_score"] > game["away_score"]) == is_home
        prior = store.fetch(gameday - timedelta(days=1))
        same = store.fetch(gameday)
        got_prior, how_prior = store.record_for(prior, slug)
        got_same, how_same = store.record_for(same, slug)
        out = {"slug": slug, "identified_via": how_prior,
               "entering_substrate_all_games": fmt(expected),
               "file_D-1": fmt(got_prior),
               "file_D": fmt(got_same)}
        delta_ok = (got_prior is not None and got_same is not None
                    and got_same == add_result(got_prior, won))
        out["delta_gate"] = "PASS" if delta_ok else "FAIL"
        if got_prior == expected:
            out["equality_gate"] = "PASS"
            out["deviation"] = None
            eq_ok = True
        else:
            team_dates = {r["date"] for r in rows
                          if slug in (r["home_slug"], r["away_slug"])}
            dev = classify_deviation(
                rows, slug, before, got_prior, expected,
                season_surfaces_norm(year, rows),
                lambda: derive_cbr(year), team_dates)
            out["deviation"] = dev
            out["equality_gate"] = ("PASS_EXPLAINED" if dev else "FAIL")
            eq_ok = dev is not None
        out["verdict"] = "PASS" if (delta_ok and eq_ok) else "FAIL"
        return out

    probes = []

    # ---- W1 + F1: first playing date of every season -----------------
    for year in range(2015, 2024):
        rows = seasons[year]
        gameday = date.fromisoformat(rows[0]["date"])
        prior = store.fetch(gameday - timedelta(days=1))
        same = store.fetch(gameday)
        nxt = store.fetch(gameday + timedelta(days=1))
        games = [r for r in rows if r["date"] == gameday.isoformat()]
        checked = violations = unresolvable = 0
        classified_edges = []
        hard_violations = []
        for game in games:
            hs, as_ = game["home_slug"], game["away_slug"]
            if hs is None or as_ is None:
                unresolvable += 1
                continue
            rp_h, _ = store.record_for(same, hs)
            rp_a, _ = store.record_for(same, as_)
            if rp_h is None or rp_a is None:
                unresolvable += 1
                continue
            checked += 1
            home_won = game["home_score"] > game["away_score"]
            bad = []
            for slug, won in ((hs, home_won), (as_, not home_won)):
                want = (1, 0) if won else (0, 1)
                got, _ = store.record_for(same, slug)
                if got != want:
                    bad.append(slug)
            if bad:
                violations += 1
                # DATING_EDGE test: both teams at pre-game state in
                # file G, and at their substrate record through G+1
                # in file G+1.
                edge = True
                for slug in (hs, as_):
                    got_g, _ = store.record_for(same, slug)
                    got_n, _ = store.record_for(nxt, slug)
                    through = entering_all(
                        rows, slug,
                        (gameday + timedelta(days=2)).isoformat())
                    # entering_all counts games < before; through G+1
                    # means before = G+2.
                    if got_g != (0, 0) or got_n != through:
                        edge = False
                if edge:
                    classified_edges.append(
                        {"game": f'{game["away_loc"]} '
                                 f'{game["away_score"]} @ '
                                 f'{game["home_loc"]} '
                                 f'{game["home_score"]}',
                         "class": "DATING_EDGE_LATE_INCLUSION",
                         "filed_under": (gameday + timedelta(days=1)
                                         ).isoformat()})
                else:
                    hard_violations.append(
                        {"game": f'{game["away_loc"]} '
                                 f'{game["away_score"]} @ '
                                 f'{game["home_loc"]} '
                                 f'{game["home_score"]}',
                         "teams_off": bad})
        probe = {"probe": "W1" if year == 2015 else "F1",
                 "season": SEASON_LABEL[year],
                 "game_date": gameday.isoformat(),
                 "prior_file": (gameday - timedelta(days=1)).isoformat(),
                 "games_on_date": len(games),
                 "prior_file_total_games":
                     None if prior.get("missing") else prior["total_games"],
                 "file_D_both_resolved_games_checked": checked,
                 "file_D_spotcheck_violations": violations,
                 "classified_dating_edges": classified_edges,
                 "hard_violations": hard_violations,
                 "unresolvable_games": unresolvable}
        ok = (not prior.get("missing") and prior["total_games"] == 0
              and not hard_violations and checked >= 1)
        if year == 2015:
            detail = {}
            for slug in ("duke", "kentucky", "wisconsin"):
                game = next(r for r in games
                            if slug in (r["home_slug"], r["away_slug"]))
                detail[slug] = team_check(year, gameday, slug, game)
            wisc = (prior["by_slug"]["wisconsin"]["adj_d"],
                    same["by_slug"]["wisconsin"]["adj_d"])
            kent = (prior["by_slug"]["kentucky"]["adj_o"],
                    same["by_slug"]["kentucky"]["adj_o"])
            fp_ok = ([round(float(x), 3) for x in wisc]
                     == [90.405, 89.118]
                     and [round(float(x), 3) for x in kent]
                     == [117.724, 117.434])
            detail["attempt3_fingerprints"] = {
                "wisconsin_adj_d_D-1_D": [round(float(x), 3) for x in wisc],
                "kentucky_adj_o_D-1_D": [round(float(x), 3) for x in kent],
                "expected_from_attempt3": {
                    "wisconsin_adj_d": [90.405, 89.118],
                    "kentucky_adj_o": [117.724, 117.434]},
                "reproduce": fp_ok}
            ok = ok and fp_ok and all(
                v["verdict"] == "PASS" for v in detail.values()
                if isinstance(v, dict) and "verdict" in v)
            probe["witness_detail"] = detail
        probe["verdict"] = "PASS" if ok else "FAIL"
        probes.append(probe)

    # ---- T1: championship games ---------------------------------------
    for year, (datestr, pair) in sorted(d3w.CHAMPIONSHIPS.items()):
        gameday = date.fromisoformat(datestr)
        rows = seasons[year]
        games = [r for r in rows if r["date"] == datestr]
        game = games[0] if len(games) == 1 else None
        pair_ok = False
        if game is not None:
            pair_ok = tuple(sorted((game["home_slug"],
                                    game["away_slug"]))) == pair
        probe = {"probe": "T1", "season": SEASON_LABEL[year],
                 "game_date": datestr, "games_on_date": len(games),
                 "declared_pair_agrees_with_substrate": pair_ok,
                 "teams": []}
        ok = pair_ok
        if game is not None:
            for slug in pair:
                res = team_check(year, gameday, slug, game)
                probe["teams"].append(res)
                ok = ok and res["verdict"] == "PASS"
        probe["verdict"] = "PASS" if ok else "FAIL"
        probes.append(probe)

    # ---- W2: attempt-3 witness B, Big Ten final 2023-03-12 ------------
    rows = seasons[2023]
    gameday = date(2023, 3, 12)
    game = next(r for r in rows if r["date"] == "2023-03-12"
                and "purdue" in (r["home_slug"], r["away_slug"]))
    probe = {"probe": "W2", "season": "2022-23",
             "game_date": "2023-03-12",
             "game": f'{game["away_loc"]} {game["away_score"]} @ '
                     f'{game["home_loc"]} {game["home_score"]}',
             "teams": []}
    ok = True
    for slug in ("purdue", "penn-state"):
        res = team_check(2023, gameday, slug, game)
        probe["teams"].append(res)
        ok = ok and res["verdict"] == "PASS"
    probe["verdict"] = "PASS" if ok else "FAIL"
    probes.append(probe)

    # ---- L1: 2019-20 final playing date --------------------------------
    rows = seasons[2020]
    gameday = date(2020, 3, 11)
    games = [r for r in rows if r["date"] == "2020-03-11"]
    slots = resolved = 0
    fails, team_results = [], []
    for game in games:
        for slug in (game["home_slug"], game["away_slug"]):
            slots += 1
            if slug is None:
                continue
            prior = store.fetch(gameday - timedelta(days=1))
            _, how = store.record_for(prior, slug)
            if how in ("FILE_MISSING", "UNRESOLVED"):
                continue
            resolved += 1
            res = team_check(2020, gameday, slug, game)
            team_results.append(res)
            if res["verdict"] != "PASS":
                fails.append(res)
    coverage = resolved / slots if slots else 0
    probe = {"probe": "L1", "season": "2019-20",
             "game_date": "2020-03-11",
             "substitute_for": "championship probe — no 2020 "
                               "championship game exists (tournament "
                               "cancelled)",
             "games_on_date": len(games), "team_slots": slots,
             "resolved_slots": resolved,
             "coverage": round(coverage, 4),
             "teams_checked": len(team_results),
             "failures": fails}
    probe["verdict"] = ("PASS" if not fails and coverage >= 0.90
                        else "FAIL")
    probes.append(probe)

    files_used = {}
    for k, v in store.files.items():
        if v.get("missing"):
            continue
        files_used[k] = {kk: v[kk] for kk in
                         ("sha256", "bytes", "team_rows", "layout",
                          "total_games")}
        if v.get("surface_identifications"):
            files_used[k]["surface_identifications"] = \
                v["surface_identifications"]
    missing = [k for k, v in store.files.items() if v.get("missing")]
    passed = sum(1 for p in probes if p["verdict"] == "PASS")
    result = {
        "probe": "PRIOR-SNAPSHOT convention witness verification",
        "amendment": "research/nba_cbb_activation_20261028/AMENDMENT_1.md",
        "convention": "for games on date D, the Torvik input is the "
                      "archive file dated D-1",
        "torvik_route": "PR #2832 pinned commit " + TORVIK_PINNED_COMMIT,
        "torvik_anchor_check": "2023-03-12 pull reproduces PR #2832 "
                               "sample sha256 " + TORVIK_ANCHOR["sha256"],
        "hoopr_inputs": "PR #2867 manifest pins verified before use",
        "resolver": "PR #2871 build_resolver (published overrides + "
                    "CBR surface tables) + declared surface "
                    "identification (printed per use)",
        "torvik_files": files_used,
        "torvik_files_missing": missing,
        "probes": probes,
        "summary": {"probes": len(probes), "pass": passed,
                    "fail": len(probes) - passed,
                    "verdict": "PRIOR_SNAPSHOT_VERIFIED"
                    if passed == len(probes) else "PROBE_FAILURE"},
    }
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n",
                              encoding="utf-8")
    print(json.dumps(result["summary"]))
    return 0 if passed == len(probes) else 1


if __name__ == "__main__":
    sys.exit(main())
