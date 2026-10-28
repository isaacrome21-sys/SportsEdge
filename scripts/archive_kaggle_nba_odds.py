"""Download Kaggle historical odds datasets and normalize them to the
SportsEdge canonical schema on the data branch.

ACTIONS-SIDE ONLY. Credentials come from the environment ONLY:
  SPORTSEDGE_KAGGLE_USERNAME / SPORTSEDGE_KAGGLE_KEY (GitHub repo secrets,
  from the Kaggle account's API token). Values are NEVER logged, printed,
  or embedded in errors, file names, or URLs. Unit tests use fake
  credentials and stubbed transports — no network, no real secrets.

Pipeline per dataset:
  1. GET https://www.kaggle.com/api/v1/datasets/download/{owner}/{slug}
     with HTTP Basic auth (username:key) -> zip file. (Stdlib urllib; no
     kaggle CLI dependency. The CLI is the documented alternative.)
  2. Unzip, locate the CSV, record the RAW observed schema (column names,
     row count, sha256) in the manifest.
  3. Normalize raw columns -> canonical schema via an explicit alias
     registry. Unrecognized columns fail closed with the observed header
     in the error (column names are not secrets; safe to log). The
     current Kaggle file ships the spread as an unsigned magnitude plus
     a whos_favored indicator (documented on the dataset page); the
     magnitude is signed to home perspective from that indicator, rows
     whose indicator cannot be resolved drop their spread leg (counted
     in the manifest), and a file whose indicators mostly fail to
     resolve fails closed (KAGGLE_NBA_FAVORED_UNRESOLVED).
  4. Spread-orientation check: the raw spread's team perspective is
     verified empirically — on rows carrying both a spread and moneylines,
     the spread favorite must agree with the moneyline favorite on >=95%
     of rows. Disagreement fails closed (KAGGLE_NBA_SPREAD_ORIENTATION_
     UNRESOLVED) instead of guessing.
  5. Write archive/nba-kaggle-odds/{season_label}/games.csv (one file per
     season label) + archive/nba-kaggle-odds/manifest.json.

Canonical schema (runner-side loader contract):
  game_date, season_label, home_team, away_team, home_score, away_score,
  closing_spread_home, spread_home_juice, spread_away_juice,
  closing_total, over_juice, under_juice,
  closing_ml_home, closing_ml_away
Juice columns may be empty: the baseline loader then returns MISSING for
that market leg (probabilities are never built on invented juice).

Adding another dataset later: add an entry to DATASET_REGISTRY below
(owner/slug, archive subdir, column aliases, spread perspective) and pass
--dataset owner/slug (or extend the workflow matrix). No code changes
beyond the registry entry.

Exit codes: 0 = ran (downloaded+normalized or nothing due), 2 = failed closed.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
KAGGLE_API_ROOT = "https://www.kaggle.com/api/v1"
USER_ENV = "SPORTSEDGE_KAGGLE_USERNAME"
KEY_ENV = "SPORTSEDGE_KAGGLE_KEY"
SCHEMA_VERSION = "KAGGLE_NBA_BASELINE_V1"

# Canonical columns the runner-side loader reads.
CANONICAL_COLUMNS = (
    "game_date", "season_label", "home_team", "away_team",
    "home_score", "away_score",
    "closing_spread_home", "spread_home_juice", "spread_away_juice",
    "closing_total", "over_juice", "under_juice",
    "closing_ml_home", "closing_ml_away",
)


class KaggleArchiveError(RuntimeError):
    """Fail-closed error. Never downgraded to a warning."""


class KaggleCredentialsMissing(KaggleArchiveError):
    pass


# ---------------------------------------------------------------------------
# Dataset registry — how to add more datasets later
# ---------------------------------------------------------------------------
#
# Each entry: owner/slug -> {
#   "archive_subdir": where normalized files land under archive/,
#   "aliases": canonical column -> list of raw header spellings to accept,
#   "spread_home_perspective": True/False if the publisher documents which
#       team the raw spread applies to, else None (verified empirically),
#   "notes": provenance notes for the manifest.
# }
#
# To add a dataset: append an entry here and run with
#   --dataset owner/slug
# (or add a matrix leg in .github/workflows/archive-kaggle-nba-odds.yml).
DATASET_REGISTRY = {
    "cviaxmiwnptr/nba-betting-data": {
        "archive_subdir": "nba-kaggle-odds",
        "notes": ("CC0. NBA Oct 2007-Jun 2026. DESIGN ONLY segmented "
                  "baseline — provenance changes mid-file: "
                  "SportsbookReviewsOnline through Jan 16, 2023; ESPN "
                  "Jan 17, 2023-Jun 22, 2025 (no moneylines, no 2H); "
                  "Sportsbook Review median from Oct 21, 2025. Date-only, "
                  "no per-quote timestamps; post-2023 rows are "
                  "consensus/median, NOT per-book. Soft consensus-close "
                  "ceiling — harness verdict stays CONDITIONAL per spec. "
                  "Comparisons against this baseline must NEVER be "
                  "labeled verified CLV."),
        "spread_home_perspective": None,  # verified empirically at normalize
        "aliases": {
            "game_date": ["Date", "date", "game_date", "GAME_DATE",
                          "GameDate"],
            "home_team": ["Home Team", "home_team", "HomeTeam", "home",
                          "HOME_TEAM", "Home"],
            "away_team": ["Away Team", "away_team", "AwayTeam", "away",
                          "AWAY_TEAM", "Away", "Visitor", "visitor"],
            "home_score": ["Home Score", "home_score", "PTS_home",
                           "home_pts", "HomeScore", "Home Pts", "score_home"],
            "away_score": ["Away Score", "away_score", "PTS_away",
                           "away_pts", "AwayScore", "Away Pts", "score_away"],
            # Non-canonical: the current Kaggle file ships the spread as
            # an UNSIGNED magnitude ("always a positive number") plus this
            # favorite indicator. normalize_rows converts the magnitude
            # to a signed home-perspective spread from it — the
            # conversion is documented on the dataset page, and the
            # empirical orientation audit still verifies the result.
            "whos_favored": ["whos_favored", "Whos Favored",
                             "Who's Favored", "favored", "Favored"],
            "closing_spread_home": ["Spread", "spread", "spread_home",
                                    "home_spread", "closing_spread",
                                    "Close Spread"],
            "spread_home_juice": ["spread_home_juice", "Spread Home Juice",
                                  "home_spread_juice", "spread_home_odds"],
            "spread_away_juice": ["spread_away_juice", "Spread Away Juice",
                                  "away_spread_juice", "spread_away_odds"],
            "closing_total": ["Total", "total", "total_line", "OU",
                              "over_under", "closing_total", "Close Total"],
            "over_juice": ["over_juice", "Over Juice", "over_odds"],
            "under_juice": ["under_juice", "Under Juice", "under_odds"],
            "closing_ml_home": ["Moneyline Home", "moneyline_home",
                                "home_ml", "ML Home", "home_moneyline",
                                "Home ML"],
            "closing_ml_away": ["Moneyline Away", "moneyline_away",
                                "away_ml", "ML Away", "away_moneyline",
                                "Away ML"],
        },
    },
}


# ---------------------------------------------------------------------------
# Credentials (env only)
# ---------------------------------------------------------------------------

def read_credentials(env: dict | None = None) -> tuple[str, str]:
    source = env if env is not None else os.environ
    username = (source.get(USER_ENV) or "").strip()
    key = (source.get(KEY_ENV) or "").strip()
    if not username or not key:
        raise KaggleCredentialsMissing(
            "KAGGLE_CREDENTIALS_MISSING: set %s and %s (GitHub repo "
            "secrets from the Kaggle account API token; Actions-side only)"
            % (USER_ENV, KEY_ENV)
        )
    return username, key


# ---------------------------------------------------------------------------
# Download (stdlib urllib; the kaggle CLI is the documented alternative)
# ---------------------------------------------------------------------------

def download_dataset_zip(slug: str, username: str, key: str,
                         timeout: int = 120,
                         opener=None) -> bytes:
    """GET /api/v1/datasets/download/{owner}/{slug} -> zip bytes."""
    if "/" not in slug:
        raise KaggleArchiveError("KAGGLE_DATASET_SLUG_INVALID:%s" % slug)
    url = "%s/datasets/download/%s" % (KAGGLE_API_ROOT, slug)
    token = base64.b64encode(("%s:%s" % (username, key)).encode("utf-8")
                             ).decode("ascii")
    request = urllib.request.Request(
        url, headers={"Authorization": "Basic " + token,
                      "User-Agent": "SportsEdge-Kaggle-Archiver/1.0"})
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise KaggleArchiveError(
                "KAGGLE_AUTH_FAILED:http=401 — check the repo secrets; "
                "the value itself is never logged") from exc
        if exc.code == 404:
            raise KaggleArchiveError(
                "KAGGLE_DATASET_NOT_FOUND:%s" % slug) from exc
        raise KaggleArchiveError(
            "KAGGLE_HTTP_ERROR:http=%d slug=%s" % (exc.code, slug)) from exc
    except urllib.error.URLError as exc:
        raise KaggleArchiveError("KAGGLE_NETWORK_ERROR") from exc


def extract_csv(zip_bytes: bytes) -> tuple[str, bytes]:
    """Return (member_name, csv_bytes) for the single CSV in the zip."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise KaggleArchiveError("KAGGLE_ZIP_INVALID") from exc
    names = [n for n in archive.namelist()
             if n.lower().endswith(".csv") and not n.startswith("__MACOSX")]
    if not names:
        raise KaggleArchiveError("KAGGLE_ZIP_NO_CSV")
    if len(names) > 1:
        raise KaggleArchiveError(
            "KAGGLE_ZIP_MULTIPLE_CSV:%r — refusing to guess" % (names,))
    name = names[0]
    return name, archive.read(name)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _first_present(row: dict, aliases: list[str]):
    for alias in aliases:
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
    return None


def _parse_date(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S", "%m-%d-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # ISO with time component
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _season_label(game_date: str) -> int | None:
    """Season S covers Oct-Dec of year S and Jan-Jun of year S+1.

    Jul-Sep games (preseason/summer) return None and are excluded.
    """
    year, month, _ = (int(p) for p in game_date.split("-"))
    if month >= 10:
        return year
    if month <= 6:
        return year - 1
    return None


def _num(value):
    try:
        num = float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    import math
    return num if math.isfinite(num) else None


def normalize_rows(raw_header: list[str], rows: list[dict],
                   config: dict) -> tuple[list[dict], dict]:
    """Map raw rows to the canonical schema. Fails closed on bad schema."""
    aliases = config["aliases"]
    required = ("game_date", "home_team", "away_team")
    resolved: dict[str, str] = {}
    for canonical in CANONICAL_COLUMNS:
        for alias in aliases.get(canonical, []):
            if alias in raw_header:
                resolved[canonical] = alias
                break
    missing = [c for c in required if c not in resolved]
    if missing:
        raise KaggleArchiveError(
            "KAGGLE_NBA_RAW_SCHEMA_UNRECOGNIZED:missing=%r observed=%r"
            % (missing, raw_header))
    favored_col = None
    for alias in aliases.get("whos_favored", []):
        if alias in raw_header:
            favored_col = alias
            break
    out: list[dict] = []
    stats = {"rows_read": 0, "rows_accepted": 0, "rows_skipped": 0,
             "skipped_no_date": 0, "skipped_offseason": 0,
             "skipped_no_teams": 0,
             "spread_signed_from_favored": 0,
             "spread_dropped_favored_unresolved": 0,
             "spread_rows_bearing": 0}
    for row in rows:
        stats["rows_read"] += 1
        game_date = _parse_date(_first_present(row, aliases["game_date"]))
        if game_date is None:
            stats["skipped_no_date"] += 1
            stats["rows_skipped"] += 1
            continue
        season = _season_label(game_date)
        if season is None:
            stats["skipped_offseason"] += 1
            stats["rows_skipped"] += 1
            continue
        home = str(_first_present(row, aliases["home_team"]) or "").strip()
        away = str(_first_present(row, aliases["away_team"]) or "").strip()
        if not home or not away:
            stats["skipped_no_teams"] += 1
            stats["rows_skipped"] += 1
            continue

        def get(canonical):
            raw_col = resolved.get(canonical)
            return _num(row.get(raw_col)) if raw_col else None

        spread = get("closing_spread_home")
        if favored_col is not None and spread is not None:
            # Raw spread is an unsigned magnitude; sign it from the
            # documented favorite indicator. Never guess: an
            # unresolvable indicator drops this row's spread leg
            # (counted loudly) instead of inventing a sign.
            if spread == 0:
                pass  # pick'em: sign carries no information
            else:
                stats["spread_rows_bearing"] += 1
                favored = str(row.get(favored_col) or "").strip().lower()
                if favored in ("home", home.lower()):
                    spread = -abs(spread)
                    stats["spread_signed_from_favored"] += 1
                elif favored in ("away", away.lower()):
                    spread = abs(spread)
                    stats["spread_signed_from_favored"] += 1
                else:
                    spread = None
                    stats["spread_dropped_favored_unresolved"] += 1

        out.append({
            "game_date": game_date,
            "season_label": season,
            "home_team": home,
            "away_team": away,
            "home_score": get("home_score"),
            "away_score": get("away_score"),
            "closing_spread_home": spread,
            "spread_home_juice": get("spread_home_juice"),
            "spread_away_juice": get("spread_away_juice"),
            "closing_total": get("closing_total"),
            "over_juice": get("over_juice"),
            "under_juice": get("under_juice"),
            "closing_ml_home": get("closing_ml_home"),
            "closing_ml_away": get("closing_ml_away"),
        })
        stats["rows_accepted"] += 1
    if favored_col is not None and stats["spread_rows_bearing"]:
        signed_rate = (stats["spread_signed_from_favored"]
                       / stats["spread_rows_bearing"])
        if signed_rate < 0.95:
            raise KaggleArchiveError(
                "KAGGLE_NBA_FAVORED_UNRESOLVED: signed %.3f of %d "
                "spread-bearing rows via %r — refusing to archive a "
                "baseline whose spread signs are mostly unresolvable"
                % (signed_rate, stats["spread_rows_bearing"], favored_col))
    return out, stats


def verify_spread_orientation(rows: list[dict],
                              declared: bool | None) -> tuple[bool, dict]:
    """Verify which team the raw spread applies to, empirically.

    On rows carrying both a spread and both moneylines, the spread
    favorite (team laying points) must agree with the moneyline favorite
    (shorter american price) on >=95% of rows. Returns
    (spread_is_home_perspective, audit). Fails closed when neither
    perspective reaches the threshold — never guesses.
    """
    agree_home = disagree_home = agree_away = disagree_away = 0
    checked = 0
    for row in rows:
        spread = row.get("closing_spread_home")
        ml_h, ml_a = row.get("closing_ml_home"), row.get("closing_ml_away")
        if spread is None or ml_h is None or ml_a is None:
            continue
        if spread == 0 or ml_h == ml_a:
            continue  # pick'em: no information
        checked += 1
        ml_home_favored = ml_h < ml_a  # more negative = shorter = favorite
        spread_home_favored = spread < 0
        if ml_home_favored == spread_home_favored:
            agree_home += 1
        else:
            disagree_home += 1
        # Away-perspective mirror: spread applies to away team.
        spread_away_favored = spread < 0
        ml_away_favored = not ml_home_favored
        if ml_away_favored == spread_away_favored:
            agree_away += 1
        else:
            disagree_away += 1
    audit = {"rows_checked": checked, "agree_home": agree_home,
             "disagree_home": disagree_home, "agree_away": agree_away,
             "disagree_away": disagree_away}
    if checked == 0:
        raise KaggleArchiveError(
            "KAGGLE_NBA_SPREAD_ORIENTATION_UNVERIFIABLE:no rows carry "
            "both spread and moneylines")
    home_rate = agree_home / checked
    away_rate = agree_away / checked
    audit["home_agreement_rate"] = home_rate
    audit["away_agreement_rate"] = away_rate
    if declared is True and home_rate < 0.95:
        raise KaggleArchiveError(
            "KAGGLE_NBA_SPREAD_ORIENTATION_MISMATCH:declared=home "
            "agreement=%.3f" % home_rate)
    if declared is False and away_rate < 0.95:
        raise KaggleArchiveError(
            "KAGGLE_NBA_SPREAD_ORIENTATION_MISMATCH:declared=away "
            "agreement=%.3f" % away_rate)
    if declared is not None:
        return declared, audit
    if home_rate >= 0.95 and away_rate < 0.95:
        return True, audit
    if away_rate >= 0.95 and home_rate < 0.95:
        return False, audit
    raise KaggleArchiveError(
        "KAGGLE_NBA_SPREAD_ORIENTATION_UNRESOLVED:home=%.3f away=%.3f "
        "— refusing to guess" % (home_rate, away_rate))


# ---------------------------------------------------------------------------
# Archive writing
# ---------------------------------------------------------------------------

def write_archive(out_dir: Path, subdir: str, rows: list[dict],
                  manifest_extra: dict) -> dict:
    by_season: dict[int, list[dict]] = {}
    for row in rows:
        by_season.setdefault(row["season_label"], []).append(row)
    written = []
    for season, season_rows in sorted(by_season.items()):
        season_rows.sort(key=lambda r: (r["game_date"], r["home_team"],
                                        r["away_team"]))
        path = (out_dir / "archive" / subdir / str(season) / "games.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS)
            writer.writeheader()
            for row in season_rows:
                record = {c: ("" if row.get(c) is None else row[c])
                          for c in CANONICAL_COLUMNS}
                writer.writerow(record)
        payload = json.dumps(season_rows, sort_keys=True, default=str)
        written.append({
            "season": season,
            "games": len(season_rows),
            "file": str(path.relative_to(out_dir)),
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        })
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "archived_at_utc": datetime.now(UTC).isoformat(),
        "seasons": written,
        **manifest_extra,
    }
    manifest_path = out_dir / "archive" / subdir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)
                             + "\n", encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="cviaxmiwnptr/nba-betting-data")
    parser.add_argument("--out-dir", default=".",
                        help="data-branch worktree (archive root)")
    parser.add_argument("--status-out", default=None)
    parser.add_argument("--self-test", action="store_true",
                        help="no network: verify normalization + fail-closed paths")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    config = DATASET_REGISTRY.get(args.dataset)
    if config is None:
        print("failed closed: KAGGLE_DATASET_NOT_REGISTERED:%s — add it to "
              "DATASET_REGISTRY first" % args.dataset, file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    try:
        username, key = read_credentials()
        zip_bytes = download_dataset_zip(args.dataset, username, key)
        member, csv_bytes = extract_csv(zip_bytes)
        text = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        raw_header = reader.fieldnames or []
        raw_rows = list(reader)
        raw_sha = hashlib.sha256(csv_bytes).hexdigest()
        rows, stats = normalize_rows(raw_header, raw_rows, config)
        spread_home, orientation = verify_spread_orientation(
            rows, config.get("spread_home_perspective"))
        if not spread_home:
            # Flip to home perspective for the canonical schema.
            for row in rows:
                if row["closing_spread_home"] is not None:
                    row["closing_spread_home"] = -row["closing_spread_home"]
                row["spread_home_juice"], row["spread_away_juice"] = (
                    row["spread_away_juice"], row["spread_home_juice"])
        manifest = write_archive(out_dir, config["archive_subdir"], rows, {
            "dataset": args.dataset,
            "dataset_member": member,
            "raw_header": raw_header,
            "raw_rows": len(raw_rows),
            "raw_sha256": raw_sha,
            "spread_home_perspective": spread_home,
            "spread_orientation_audit": orientation,
            "normalization_stats": stats,
            "notes": config.get("notes", ""),
        })
        status_doc = {"status": "ARCHIVED", "dataset": args.dataset,
                      "games": stats["rows_accepted"],
                      "seasons": len(manifest["seasons"])}
        print(json.dumps(status_doc, indent=2, sort_keys=True))
        if args.status_out:
            status_path = Path(args.status_out)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                json.dumps(status_doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        return 0
    except (KaggleArchiveError,) as exc:
        print("failed closed: %s" % exc, file=sys.stderr)
        return 2


def self_test() -> int:
    """No network. Verifies normalization, orientation check, schema guard."""
    config = DATASET_REGISTRY["cviaxmiwnptr/nba-betting-data"]
    # 1. Missing credentials fail closed.
    try:
        read_credentials(env={})
    except KaggleCredentialsMissing:
        pass
    else:
        print("SELF_TEST_FAIL: missing credentials not rejected",
              file=sys.stderr)
        return 2
    # 2. Unrecognized schema fails closed (column names safe to echo).
    try:
        normalize_rows(["foo", "bar"], [{"foo": 1}], config)
    except KaggleArchiveError as exc:
        assert "KAGGLE_NBA_RAW_SCHEMA_UNRECOGNIZED" in str(exc)
    else:
        print("SELF_TEST_FAIL: bad schema not rejected", file=sys.stderr)
        return 2
    # 3. Orientation check: consistent home-perspective data passes.
    rows = [
        {"closing_spread_home": -5.5, "closing_ml_home": -220,
         "closing_ml_away": 180},
        {"closing_spread_home": 3.0, "closing_ml_home": 140,
         "closing_ml_away": -160},
    ] * 20
    home_perspective, audit = verify_spread_orientation(rows, None)
    if not home_perspective or audit["home_agreement_rate"] < 0.95:
        print("SELF_TEST_FAIL: orientation check misfired", file=sys.stderr)
        return 2
    # 4. Contradictory data fails closed instead of guessing.
    mixed = (rows[:10] + [
        {"closing_spread_home": -5.5, "closing_ml_home": 180,
         "closing_ml_away": -220},
    ] * 10)
    try:
        verify_spread_orientation(mixed, None)
    except KaggleArchiveError as exc:
        assert "KAGGLE_NBA_SPREAD_ORIENTATION_UNRESOLVED" in str(exc)
    else:
        print("SELF_TEST_FAIL: ambiguous orientation not rejected",
              file=sys.stderr)
        return 2
    print("self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
