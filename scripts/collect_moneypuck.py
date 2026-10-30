#!/usr/bin/env python3
"""MoneyPuck free CSV research collector (moneypuck.com downloads).

REGISTERED RESEARCH SOURCE — archive/intake only, zero pricing impact.
MoneyPuck publishes free team/player aggregates and shot-level data as
zip files on its data page. This collector archives the one-row-per-
season team/skater/goalie files and per-season shot files under one
provenance label, recording sha256 of both the zip and the extracted
CSV in a manifest. Output is never a pricing input: manifests carry
``pricing_input: false`` and ``play_eligible: false``, no pricing path
imports this module, and no model probability is produced here.

Live downloads happen only with an explicit ``--live`` flag naming one
dataset; the default run makes zero network requests. Downloads are
served from peter-tanner.com (the data page's own host). The
one-row-per-season rollups currently end at season 2024 (2024-25);
per-season game-by-game player zips exist on the data page but are a
different grain and are deliberately not registered here.

Admission cross-check (2026-10-24): MoneyPuck EDM 2024-25, situation
'all': 82 GP, 259 goals for — exactly matching the NHL API's official
standings. Goals against is 235 vs the API's 236: shot data does not
count the shootout-deciding goal, official standings do, and EDM lost
one shootout that season. The one-goal difference is a documented
convention gap, not an error in either source.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://peter-tanner.com/moneypuck/downloads"
SOURCE = "moneypuck"
USER_AGENT = "sportsedge-research-collector (moneypuck; archive only)"
SEASON_RE = re.compile(r"^\d{4}$")

# dataset -> (url path, expected CSV member name)
DATASETS = {
    "teams-history": ("historicalOneRowPerSeason/teams_2008_to_2024.zip",
                      "teams_2008_to_2024.csv"),
    "skaters-history": ("historicalOneRowPerSeason/skaters_2008_to_2024.zip",
                        "skaters_2008_to_2024.csv"),
    "goalies-history": ("historicalOneRowPerSeason/goalies_2008_to_2024.zip",
                        "goalies_2008_to_2024.csv"),
    "shots": ("shots_{season}.zip", "shots_{season}.csv"),
}


class IntakeRefusal(ValueError):
    """Expected fail-closed source, argument, or payload refusal."""


def dataset_url(dataset, season=None):
    """Resolve one registered dataset to its download URL."""
    if dataset not in DATASETS:
        raise IntakeRefusal(f"unknown dataset: {dataset!r}")
    path, _member = DATASETS[dataset]
    if "{season}" in path:
        if not isinstance(season, str) or not SEASON_RE.match(season):
            raise IntakeRefusal(
                f"shots dataset needs a 4-digit season start year, got {season!r}")
        if not 2007 <= int(season) <= 2100:
            raise IntakeRefusal(f"season out of range: {season!r}")
        path = path.format(season=season)
    return f"{BASE}/{path}"


def _expected_member(dataset, season=None):
    member = DATASETS[dataset][1]
    return member.format(season=season) if "{season}" in member else member


def fetch_bytes(url, opener=None, timeout=120):
    """GET raw bytes, failing closed on any transport error."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    open_fn = opener or urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise IntakeRefusal(f"GET {url} -> HTTP {exc.code}") from exc
    except URLError as exc:
        raise IntakeRefusal(f"GET {url} -> {exc.reason}") from exc


def extract_csv(zip_bytes, expected_member):
    """Return the text of the one expected CSV member, failing closed."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise IntakeRefusal("download is not a zip archive") from exc
    names = [n for n in archive.namelist() if n.endswith(".csv")]
    matches = [n for n in names if Path(n).name == expected_member]
    if len(matches) != 1:
        raise IntakeRefusal(
            f"expected exactly one {expected_member} in archive, found {names}")
    return archive.read(matches[0]).decode("utf-8-sig")


def parse_rows(csv_text):
    """Parse CSV text into a list of dict rows."""
    return list(csv.DictReader(io.StringIO(csv_text)))


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number == int(number) else number


def team_season(rows, team, season, situation="all"):
    """One team's aggregate row for one season/situation, or None."""
    for row in rows:
        if (row.get("team") == team and row.get("season") == str(season)
                and row.get("situation") == situation):
            return {
                "team": team,
                "season": str(season),
                "situation": situation,
                "games_played": _num(row.get("games_played")),
                "goals_for": _num(row.get("goalsFor")),
                "goals_against": _num(row.get("goalsAgainst")),
                "x_goals_for": _num(row.get("xGoalsFor")),
                "x_goals_against": _num(row.get("xGoalsAgainst")),
                "shots_on_goal_for": _num(row.get("shotsOnGoalFor")),
                "shots_on_goal_against": _num(row.get("shotsOnGoalAgainst")),
            }
    return None


def manifest(dataset, url, zip_bytes, csv_text, rows, fetched_at):
    """Provenance manifest for one archived dataset."""
    return {
        "source": SOURCE,
        "dataset": dataset,
        "url": url,
        "fetched_at_utc": fetched_at.astimezone(timezone.utc).isoformat(),
        "research_only": True,
        "pricing_input": False,
        "play_eligible": False,
        "model_p": None,
        "zip_sha256": hashlib.sha256(zip_bytes).hexdigest(),
        "csv_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        "rows": len(rows),
        "seasons": sorted({row.get("season") for row in rows
                           if row.get("season")}),
    }


def collect(dataset, *, season=None, live=False, out_dir=None,
            opener=None, now=None):
    """Plan or perform one dataset archive. Default: zero requests."""
    url = dataset_url(dataset, season=season)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not live:
        return {"status": "NO_LIVE_CALL", "source": SOURCE,
                "dataset": dataset, "url": url, "requests": 0}
    zip_bytes = fetch_bytes(url, opener=opener)
    csv_text = extract_csv(zip_bytes, _expected_member(dataset, season))
    rows = parse_rows(csv_text)
    if not rows:
        raise IntakeRefusal(f"{dataset}: CSV parsed to zero rows")
    body = manifest(dataset, url, zip_bytes, csv_text, rows, stamp)
    result = {"status": "RESEARCH_CAPTURED", "source": SOURCE,
              "dataset": dataset, "url": url, "requests": 1,
              "rows": body["rows"], "seasons": body["seasons"],
              "csv_sha256": body["csv_sha256"]}
    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        csv_name = _expected_member(dataset, season)
        (out_path / csv_name).write_text(csv_text, encoding="utf-8")
        manifest_name = f"{Path(csv_name).stem}.manifest.json"
        (out_path / manifest_name).write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["file"] = csv_name
        result["manifest"] = manifest_name
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="dataset", required=True)
    for name in DATASETS:
        p = sub.add_parser(name)
        if name == "shots":
            p.add_argument("--season", required=True,
                           help="season start year, e.g. 2024 for 2024-25")
        p.add_argument("--live", action="store_true",
                       help="perform the download (default: zero requests)")
        p.add_argument("--out-dir", default=None,
                       help="directory for the CSV + manifest JSON")
    args = parser.parse_args(argv)
    try:
        result = collect(args.dataset, season=getattr(args, "season", None),
                         live=args.live, out_dir=args.out_dir)
    except IntakeRefusal as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
