"""Daily CBB card: [CBB LINES] issue -> priced NON_COUNTED rows -> phone card.

  python scripts/run_cbb_daily_card.py --date 2026-11-02 \
      [--issue N | --lines-file FILE] [--torvik-store DIR] [--post]

* Lines: the newest open "[CBB LINES]" issue for the date (or --issue /
  --lines-file), parsed strictly by sportsedge.cbb_lines_intake.
* Identity: ESPN's free public scoreboard (D1 group 50) + the admitted
  crosswalk inside the runner; Illinois colleges excluded by the runner.
* Ratings: the morning-of Torvik vintage from --torvik-store
  (<date>.csv + <date>.json). If absent, the live season file is pulled
  now and stored with a manifest; the card says when it was pulled.
* Pricing: CbbEfficiencyForwardRunner.price_slate (NON_COUNTED; the
  family is NOT FROZEN, so nothing counts).
Outputs artifacts/cbb_card/<date>/{priced.json, card.json, card.md};
--post comments card.md on the lines issue. Never writes to the repo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sportsedge.cbb_daily_card import (  # noqa: E402
    CT, card_rows, fixtures_from_espn, render_card_markdown,
)
from sportsedge.cbb_efficiency_forward import (  # noqa: E402
    CbbEfficiencyForwardRunner, games_from_board, load_vintage,
)
from sportsedge.cbb_lines_intake import parse_cbb_lines  # noqa: E402

UA = "Mozilla/5.0 (SportsEdge CBB card)"
TORVIK_URL = "https://barttorvik.com/{year}_team_results.csv"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def espn_events(date: str) -> list[dict]:
    d = date.replace("-", "")
    url = ("https://site.api.espn.com/apis/site/v2/sports/basketball/"
           f"mens-college-basketball/scoreboard?dates={d}&groups=50&limit=500")
    return json.loads(_get(url)).get("events", [])


def season_year(date: str) -> int:
    y, m = int(date[:4]), int(date[5:7])
    return y + 1 if m >= 8 else y


def ensure_vintage(date: str, store: Path) -> str:
    """Use the stored morning vintage; else pull the live file now."""
    csv_p, js_p = store / f"{date}.csv", store / f"{date}.json"
    if csv_p.is_file() and js_p.is_file():
        return "Ratings: morning Torvik pull."
    store.mkdir(parents=True, exist_ok=True)
    raw = _get(TORVIK_URL.format(year=season_year(date)))
    now = datetime.now(timezone.utc)
    rows = raw.decode("utf-8").strip().count("\n")
    csv_p.write_bytes(raw)
    js_p.write_text(json.dumps({
        "url": TORVIK_URL.format(year=season_year(date)),
        "pulled_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of_local_date": date, "bytes": len(raw), "team_rows": rows,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_state": "verified-by-pull",
        "note": "card-time pull (not the scheduled morning vintage)",
    }))
    return f"Ratings: Torvik pulled {now.astimezone(CT):%-I:%M %p} CT (card-time pull)."


def lines_issue(date: str, number: int | None) -> tuple[int | None, str, str]:
    if number is None:
        found = json.loads(subprocess.run(
            ["gh", "issue", "list", "--state", "all", "--limit", "30",
             "--search", "[CBB LINES] in:title sort:created-desc",
             "--json", "number,title,createdAt"],
            check=True, capture_output=True, text=True).stdout)
        found = [i for i in found if i["title"].startswith("[CBB LINES]")
                 and datetime.fromisoformat(i["createdAt"].replace("Z", "+00:00"))
                 .astimezone(CT).strftime("%Y-%m-%d") == date]
        if not found:
            raise SystemExit(f"NO_CBB_LINES_ISSUE for {date}")
        number = found[0]["number"]
    issue = json.loads(subprocess.run(
        ["gh", "issue", "view", str(number), "--json", "title,body"],
        check=True, capture_output=True, text=True).stdout)
    return number, issue["title"], issue["body"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(CT).strftime("%Y-%m-%d"))
    ap.add_argument("--issue", type=int)
    ap.add_argument("--lines-file")
    ap.add_argument("--torvik-store", default="artifacts/torvik_store")
    ap.add_argument("--post", action="store_true")
    a = ap.parse_args()

    if a.lines_file:
        number, title, body = None, "[CBB LINES]", Path(a.lines_file).read_text()
    else:
        number, title, body = lines_issue(a.date, a.issue)
    board = parse_cbb_lines(body, title=title).to_board_dict()
    fixtures, notes = fixtures_from_espn(board, espn_events(a.date), a.date)
    vintage_note = ensure_vintage(a.date, Path(a.torvik_store))
    vintage = load_vintage(a.date, a.torvik_store)
    runner = CbbEfficiencyForwardRunner()
    priced = runner.price_slate(a.date, games_from_board(board, fixtures),
                                vintage=vintage, now=datetime.now(timezone.utc))
    rows = card_rows(priced, fixtures)
    md = render_card_markdown(rows, a.date, priced, notes, vintage_note)

    out = Path("artifacts/cbb_card") / a.date
    out.mkdir(parents=True, exist_ok=True)
    (out / "priced.json").write_text(json.dumps(priced, indent=2, default=str))
    (out / "card.json").write_text(json.dumps(rows, indent=2))
    (out / "card.md").write_text(md)
    print(md)
    if a.post and number is not None:
        subprocess.run(["gh", "issue", "comment", str(number), "--body-file",
                        str(out / "card.md")], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
