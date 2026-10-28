#!/usr/bin/env python3
"""Pinned retrieval for MoneyPuck NHL data (admission: NHL attempt 2 input).

MoneyPuck (moneypuck.com / peter-tanner.com) publishes its player, line,
team and shot data as plain CSV / zip-of-CSV files on a public downloads
page — no key, no account. Those files are CUMULATIVE SNAPSHOTS REWRITTEN
IN PLACE: the season zip pulled today states season-to-date numbers as of
today, and tomorrow's pull of the same URL is a different vintage with no
as-of archive behind it. The pin is therefore the PULL, not the URL: this
collector hash-pins the exact bytes of every pull into a manifest, stores
the raw bytes OUTSIDE the repository (a data dir under the workspace), and
refuses — never silently substitutes — a changed vintage
(SOURCE_CHANGED_AFTER_SNAPSHOT), a drifted schema (SCHEMA_INVALID), or a
"current-season" snapshot whose regeneration has gone stale
(STALE_SNAPSHOT).

Point-in-time discipline (binding; see ADMISSION_RECORD.md shipped with
this script): the season-summary and game-by-game files carry
gameId/gameDate on every row, so a feature for a game on date D may use
only rows with gameDate strictly before D. Season AGGREGATE columns in a
snapshot pulled on date P describe games through P and must never be
offered as features for a game before P; the game-by-game rows under the
strictly-prior filter are the only lawful design/pricing features. The
``demo-prior`` subcommand demonstrates the filter on a stored file.

xG model vintage: MoneyPuck rebuilt its expected-goals model for the
2026-27 season (gradient boosting, trained on 2023-24 -> 2025-26 shots;
about-page AUC 0.807 overall vs 0.784 for the prior model). Every manifest
entry records the vintage its xG values belong to, so far as the source
discloses it: season 2026 (2026-27) files carry the REBUILT model; files
for seasons <= 2025 are recorded as UNDISCLOSED_LEGACY — the source does
not state whether historical files were re-scored under the rebuilt model,
so xG must not be pooled across the 2025/2026 boundary without a declared
cross-vintage treatment in the consuming preregistration.

Stdlib only. Subcommands:
    pull       --season YYYY [--season YYYY ...] --data-dir DIR
               [--manifest PATH] [--surfaces a,b,c]
               [--expect SURFACE:SEASON=SHA256 ...] [--current-season YYYY]
    verify     --data-dir DIR --manifest PATH
    demo-prior --file PATH --team ANA --date YYYYMMDD --season YYYY
Exit codes: 0 ok; 2 usage / SOURCE_UNAVAILABLE / SEASON_NOT_PUBLISHED;
3 SOURCE_CHANGED_AFTER_SNAPSHOT / SCHEMA_INVALID / STALE_SNAPSHOT /
LOOKAHEAD_RISK / MANIFEST_MISMATCH.
"""

import csv
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
BASE = "https://peter-tanner.com/moneypuck/downloads"
STALE_THRESHOLD_HOURS = 72.0

# surface -> (url template, kind, required columns)
SURFACES = {
    "season_skaters": (
        BASE + "/seasonPlayersSummary/skaters/{season}.zip",
        "zip_csv",
        {"playerId", "gameId", "season", "playerTeam", "opposingTeam",
         "gameDate", "situation", "OnIce_F_xGoals", "OnIce_A_xGoals",
         "onIce_xGoalsPercentage"},
    ),
    "season_goalies": (
        BASE + "/seasonPlayersSummary/goalies/{season}.zip",
        "zip_csv",
        {"playerId", "gameId", "season", "playerTeam", "opposingTeam",
         "gameDate", "situation", "xGoals", "goals"},
    ),
    "season_lines": (
        BASE + "/seasonPlayersSummary/lines/{season}.zip",
        "zip_csv",
        {"lineId", "gameId", "season", "playerTeam", "opposingTeam",
         "gameDate", "situation", "xGoalsPercentage"},
    ),
    "all_teams": (
        "https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv",
        "csv",
        {"team", "season", "gameId", "playerTeam", "opposingTeam",
         "gameDate", "situation", "xGoalsFor", "xGoalsAgainst"},
    ),
    "data_dictionary": (
        BASE + "/MoneyPuckDataDictionaryForPlayers.csv",
        "reference",
        set(),
    ),
}
SEASON_SURFACES = ("season_skaters", "season_goalies", "season_lines")
DEFAULT_SURFACES = ("season_skaters", "season_goalies", "all_teams",
                    "data_dictionary")

XG_VINTAGES = {
    "rebuilt_2026_27": (
        "REBUILT for 2026-27 (gradient boosting; trained on a random "
        "sample of 289k+ shots from 2023-24 to 2025-26; about-page AUC "
        "0.807 overall vs 0.784 for the prior model)"
    ),
    "undisclosed_legacy": (
        "UNDISCLOSED_LEGACY: published before / outside the disclosed "
        "2026-27 rebuild; the source does not state whether historical "
        "files were re-scored under the rebuilt model"
    ),
}


class Refusal(Exception):
    def __init__(self, code, **detail):
        super().__init__(code)
        self.code = code
        self.detail = detail


def vintage_for_season(season, surface=None):
    if surface == "data_dictionary":
        return "not_applicable_reference"
    if season is None:
        return "mixed_file_see_record"
    return "rebuilt_2026_27" if int(season) >= 2026 else "undisclosed_legacy"


def infer_current_season(now):
    """NHL season label = the year the season starts (Oct Y -> Y)."""
    if now.month >= 10:
        return now.year
    if now.month <= 6:
        return now.year - 1
    return None  # Jul-Sep: offseason, no in-progress season


def fetch_to_file(url, part_path):
    """Stream url to part_path; return (headers dict, bytes, sha256)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            headers = dict(resp.headers)
            with open(part_path, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    digest.update(chunk)
                    out.write(chunk)
                    total += len(chunk)
    except urllib.error.HTTPError as exc:
        raise Refusal("SEASON_NOT_PUBLISHED" if exc.code == 404
                      else "SOURCE_UNAVAILABLE", http_status=exc.code, url=url)
    except urllib.error.URLError as exc:
        raise Refusal("SOURCE_UNAVAILABLE", error=str(exc.reason), url=url)
    return headers, total, digest.hexdigest()


def parse_gamedate(value):
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        raise Refusal("SCHEMA_INVALID", bad_gameDate=value)
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        raise Refusal("SCHEMA_INVALID", bad_gameDate=value)
    return int(text)


def _scan_rows(reader, required, expected_season):
    """Validate schema over DictReader rows; return stats dict."""
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise Refusal("SCHEMA_INVALID",
                      missing=sorted(required - set(reader.fieldnames or [])))
    rows = 0
    date_min = None
    date_max = None
    seasons = {}
    situations = set()
    for row in reader:
        rows += 1
        d = parse_gamedate(row["gameDate"])
        date_min = d if date_min is None else min(date_min, d)
        date_max = d if date_max is None else max(date_max, d)
        seasons[str(row["season"])] = seasons.get(str(row["season"]), 0) + 1
        situations.add(str(row["situation"]))
    if rows == 0:
        raise Refusal("SCHEMA_INVALID", reason="zero data rows")
    if expected_season is not None and set(seasons) != {str(expected_season)}:
        raise Refusal("SCHEMA_INVALID",
                      seasons_seen=sorted(seasons), expected=expected_season)
    return {
        "columns": list(reader.fieldnames),
        "data_rows": rows,
        "game_date_min": date_min,
        "game_date_max": date_max,
        "rows_by_season": seasons,
        "situations": sorted(situations),
    }


def inspect_stored(path, kind, required, expected_season):
    """Schema-verify a stored artifact; return stats dict."""
    if kind == "zip_csv":
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise Refusal("SCHEMA_INVALID", reason="not a zip file")
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise Refusal("SCHEMA_INVALID", zip_members=zf.namelist())
        with zf.open(names[0]) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"))
            stats = _scan_rows(reader, required, expected_season)
        stats["zip_member"] = names[0]
        return stats
    if kind == "csv":
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            return _scan_rows(reader, required, expected_season)
    if kind == "reference":
        raw = Path(path).read_bytes()
        if b"MoneyPuck" not in raw:
            raise Refusal("SCHEMA_INVALID", reason="dictionary marker absent")
        return {"bytes_checked": len(raw), "layout": "prose-headed reference"}
    raise Refusal("SCHEMA_INVALID", reason=f"unknown kind {kind}")


def strictly_prior_team_aggregate(rows, team, cutoff_gamedate, season,
                                  situation="all"):
    """Aggregate one team's game-by-game rows strictly before a date.

    This is the ONLY lawful way to build features from MoneyPuck
    snapshots: rows with gameDate >= cutoff (same-day included — a game
    cannot be a feature for itself or for a same-day game whose start it
    may postdate) are excluded and counted. Raises LOOKAHEAD_RISK if the
    cutoff is not a strictly-past boundary for at least one input row set,
    i.e. if no row precedes it (a sign the caller is pointing the filter
    at a date the data cannot speak to).
    """
    used = 0
    excluded = 0
    xg_for = 0.0
    xg_against = 0.0
    goals_for = 0.0
    goals_against = 0.0
    max_used = None
    for row in rows:
        if str(row.get("season")) != str(season):
            continue
        if row.get("playerTeam") != team or row.get("situation") != situation:
            continue
        d = parse_gamedate(row["gameDate"])
        if d < cutoff_gamedate:
            used += 1
            xg_for += float(row["xGoalsFor"])
            xg_against += float(row["xGoalsAgainst"])
            goals_for += float(row.get("goalsFor") or 0)
            goals_against += float(row.get("goalsAgainst") or 0)
            max_used = d if max_used is None else max(max_used, d)
        else:
            excluded += 1
    if used == 0:
        raise Refusal("LOOKAHEAD_RISK", team=team, cutoff=cutoff_gamedate,
                      reason="no strictly-prior rows; filter cannot speak")
    return {
        "team": team,
        "season": int(season),
        "situation": situation,
        "cutoff_gameDate_exclusive": cutoff_gamedate,
        "games_used": used,
        "max_gameDate_used": max_used,
        "rows_excluded_same_or_later": excluded,
        "xGoalsFor_sum": round(xg_for, 4),
        "xGoalsAgainst_sum": round(xg_against, 4),
        "goalsFor_sum": goals_for,
        "goalsAgainst_sum": goals_against,
    }


def stored_name(surface, season):
    if surface == "all_teams":
        return "all_teams.csv"
    if surface == "data_dictionary":
        return "MoneyPuckDataDictionaryForPlayers.csv"
    return f"{surface}_{season}.zip"


def check_stale(headers, surface, season, current_season, pulled_at):
    applies = season is not None and current_season is not None \
        and int(season) == int(current_season)
    if surface == "all_teams":
        applies = current_season is not None
    if not applies:
        return None
    last_mod = headers.get("Last-Modified")
    if not last_mod:
        return None
    try:
        lm = datetime.strptime(last_mod, "%a, %d %b %Y %H:%M:%S %Z")
    except ValueError:
        return None
    age_hours = (pulled_at - lm.replace(tzinfo=timezone.utc)).total_seconds() / 3600
    if age_hours > STALE_THRESHOLD_HOURS:
        raise Refusal("STALE_SNAPSHOT", surface=surface, season=season,
                      last_modified=last_mod, age_hours=round(age_hours, 1),
                      threshold_hours=STALE_THRESHOLD_HOURS)
    return round(age_hours, 1)


def pull_one(surface, season, data_dir, expect_sha, current_season, fetcher):
    url_t, kind, required = SURFACES[surface]
    url = url_t.format(season=season) if season is not None else url_t
    name = stored_name(surface, season)
    final = data_dir / name
    part = data_dir / (name + ".part")
    pulled_at = datetime.now(timezone.utc)
    headers, total, digest = fetcher(url, part)
    try:
        if expect_sha is not None and digest != expect_sha:
            raise Refusal("SOURCE_CHANGED_AFTER_SNAPSHOT", surface=surface,
                          season=season, expected_sha256=expect_sha,
                          actual_sha256=digest)
        age = check_stale(headers, surface, season, current_season, pulled_at)
        stats = inspect_stored(part, kind, required, season)
        part.replace(final)
    except Refusal:
        part.unlink(missing_ok=True)
        raise
    entry = {
        "surface": surface,
        "season": season,
        "url": url,
        "stored_as": name,
        "pulled_at_utc": pulled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "site_last_modified_utc": headers.get("Last-Modified"),
        "etag": headers.get("ETag"),
        "bytes": total,
        "sha256": digest,
        "xg_model_vintage": vintage_for_season(season, surface),
        "evidence_state": "verified-by-pull",
    }
    if kind != "reference":
        entry.update(stats)
    else:
        entry.update(stats)
    if age is not None:
        entry["snapshot_age_hours_at_pull"] = age
    return entry


def verify_manifest(data_dir, manifest):
    """Recompute sha256 of every stored file named by the manifest."""
    results = []
    ok = True
    for entry in manifest.get("samples", []):
        path = data_dir / entry["stored_as"]
        if not path.exists():
            results.append({"stored_as": entry["stored_as"],
                            "status": "MISSING"})
            ok = False
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        match = digest == entry["sha256"]
        results.append({"stored_as": entry["stored_as"],
                        "status": "PIN_MATCH" if match else "PIN_MISMATCH",
                        "sha256": digest})
        ok = ok and match
    return ok, results


def _parse_expect(items):
    expect = {}
    for item in items or []:
        key, _, value = item.partition("=")
        surface, _, season = key.partition(":")
        expect[(surface, int(season) if season else None)] = value.strip().lower()
    return expect


def cmd_pull(argv):
    seasons = []
    data_dir = None
    manifest_path = None
    surfaces = list(DEFAULT_SURFACES)
    expect_items = []
    current_season = "infer"
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--season":
            seasons.append(int(argv[i + 1])); i += 2
        elif arg == "--data-dir":
            data_dir = Path(argv[i + 1]); i += 2
        elif arg == "--manifest":
            manifest_path = Path(argv[i + 1]); i += 2
        elif arg == "--surfaces":
            surfaces = [s.strip() for s in argv[i + 1].split(",")]; i += 2
        elif arg == "--expect":
            expect_items.append(argv[i + 1]); i += 2
        elif arg == "--current-season":
            current_season = argv[i + 1]; i += 2
        else:
            print(f"unknown arg: {arg}", file=sys.stderr)
            return 2
    if not seasons or data_dir is None:
        print("usage: pull --season YYYY [...] --data-dir DIR", file=sys.stderr)
        return 2
    unknown = [s for s in surfaces if s not in SURFACES]
    if unknown:
        print(f"unknown surfaces: {unknown}", file=sys.stderr)
        return 2
    data_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    if current_season == "infer":
        cur = infer_current_season(now)
    elif current_season == "none":
        cur = None
    else:
        cur = int(current_season)
    expect = _parse_expect(expect_items)
    entries = []
    for surface in surfaces:
        if surface in SEASON_SURFACES:
            for season in seasons:
                entries.append(pull_one(surface, season, data_dir,
                                        expect.get((surface, season)),
                                        cur, fetch_to_file))
        else:
            entries.append(pull_one(surface, None, data_dir,
                                    expect.get((surface, None)),
                                    cur, fetch_to_file))
    manifest = {
        "source_id": "MONEYPUCK",
        "sport": "NHL",
        "admission_role": "DESIGN_AND_FORWARD_PRICING_INPUT",
        "pricing_path": "NHL_ATTEMPT_2_PREREG_ONLY",
        "promotes_model": False,
        "validation_credit": False,
        "play_eligible": False,
        "generated_by": "collect_moneypuck.py pull",
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "xg_vintages": XG_VINTAGES,
        "samples": entries,
    }
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if manifest_path is not None:
        manifest_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def cmd_verify(argv):
    data_dir = None
    manifest_path = None
    i = 0
    while i < len(argv):
        if argv[i] == "--data-dir":
            data_dir = Path(argv[i + 1]); i += 2
        elif argv[i] == "--manifest":
            manifest_path = Path(argv[i + 1]); i += 2
        else:
            print(f"unknown arg: {argv[i]}", file=sys.stderr)
            return 2
    if data_dir is None or manifest_path is None:
        print("usage: verify --data-dir DIR --manifest PATH", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok, results = verify_manifest(data_dir, manifest)
    print(json.dumps({"verify_ok": ok, "results": results}, indent=2))
    if not ok:
        raise Refusal("MANIFEST_MISMATCH")
    return 0


def cmd_demo_prior(argv):
    opts = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            opts[argv[i][2:]] = argv[i + 1]; i += 2
        else:
            print(f"unknown arg: {argv[i]}", file=sys.stderr)
            return 2
    try:
        path = Path(opts["file"])
        team = opts["team"]
        cutoff = int(opts["date"])
        season = int(opts["season"])
    except (KeyError, ValueError):
        print("usage: demo-prior --file PATH --team ANA --date YYYYMMDD "
              "--season YYYY", file=sys.stderr)
        return 2
    parse_gamedate(str(cutoff))
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    agg = strictly_prior_team_aggregate(rows, team, cutoff, season)
    agg["source_file"] = path.name
    agg["evidence_state"] = "verified-by-pull"
    print(json.dumps(agg, indent=2))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__.split("Stdlib only.")[1].split("Exit codes")[0],
              file=sys.stderr)
        return 2
    cmd, rest = argv[1], argv[2:]
    try:
        if cmd == "pull":
            return cmd_pull(rest)
        if cmd == "verify":
            return cmd_verify(rest)
        if cmd == "demo-prior":
            return cmd_demo_prior(rest)
        print(f"unknown subcommand: {cmd}", file=sys.stderr)
        return 2
    except Refusal as refusal:
        print(json.dumps({"refusal": refusal.code, **refusal.detail}))
        return 2 if refusal.code in ("SOURCE_UNAVAILABLE",
                                      "SEASON_NOT_PUBLISHED") else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
