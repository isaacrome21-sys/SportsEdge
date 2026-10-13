# NBA injury-report source assessment (free, timestamped)

Research note for #2147. Checked 2026-10-13 ~10:06 CT. No paid sources. Nothing is wired; availability stays UNKNOWN → props WATCH/BLOCKED until a capture is reviewed.

## 1. Official NBA injury report PDFs — best candidate
- **Index page:** `official.nba.com/nba-injury-report-<season>-season/`. It is JS-rendered; curl returned the page, but no PDF links were in the static HTML.
- **Direct URL pattern:** `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HHAM|PM.pdf`.
  - Spot checks returned HTTP 200 for 2023-11-01 06PM, 2024-03-05 01PM, 2025-01-15 05PM, 2025-04-10 07PM and 2025-12-01 05PM.
  - So **historical snapshots remain retrievable for at least the 2023-24 through 2025-26 seasons**.
  - The variant `..._05_00PM.pdf` returned 403. The minute-level naming is unverified and newer seasons may use it; check before relying on it.
- **Timestamps (reliable):** the PDF header carries its own stamp ("Injury Report: 01/15/25 05:30 PM", ET). The HTTP `Last-Modified` is 2025-01-15 22:30:04 GMT (= 5:30 PM ET). These **agree to the second**.
  - Note that the filename slot (05PM) is earlier than the header time (05:30 PM). Use the header/Last-Modified as `published_at`, never the filename.
- **Content:** game date/time, matchup, team, player, status (Out / Doubtful / Questionable / Probable / Available) and reason (including G League assignments).
- **Caveats:**
  - Snapshots are hourly-ish on game days, so as-of = the latest report with published_at < cutoff.
  - PDF table parsing is fragile: multi-line reasons, and team cells blank on continuation rows.
  - Players not listed are *not* proven available (two-way/inactive rules); treat as UNKNOWN unless listed Available.
  - Historical re-download proves content but not when *we* saw it; Last-Modified is server-asserted. Acceptable for research and needs reviewer sign-off for production.
  - Terms of use for automated bulk download are unverified; keep it low-rate and cached outside the repo.

## 2. ESPN injuries JSON — current-state only
- **Endpoint:** `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries`. It returns 30 teams, with a per-entry `date` (last update, e.g. 2026-10-12T21:36Z), status and comments.
- **No history:** it is a live state only, with no historical snapshots. It is only usable going forward via our own timestamped captures.
- Entry `date` is the last change, not publication of a report. A Wayback check of this endpoint was not completed (interrupted), so it is **unverified, and it should not be assumed archived**.

## Review decision (ChatGPT)
- The official NBA injury report is the **candidate source, forward-only**.
  - Historical PDFs can be re-downloaded, but re-downloading them later does not prove what was visible at the as-of time.
  - Production use requires our own timestamped captures going forward.
- **Listed status ≠ participation.** "Available" or "Probable" does not mean the player played or got minutes; a listed-available player can still be DNP-CD. Status feeds availability *probability*, never a participation oracle.

## Recommendation
1. Capture the official PDFs forward-only (historical PDFs are research context only, not as-of evidence) (`published_at` = header stamp, cross-checked with Last-Modified; reject if they disagree by more than 5 min).
2. Pre-register a parser and an evaluation before use.
3. Going forward, add timestamped ESPN JSON captures as a secondary cross-check.
4. Props remain WATCH/BLOCKED until this is reviewed.
