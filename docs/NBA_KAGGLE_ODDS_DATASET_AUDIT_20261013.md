# Audit: Kaggle NBA odds dataset `cviaxmiwnptr/nba-betting-data` (the only dataset in scope)

Checked 2026-10-13 ~11:50 CT. **Result: UNVERIFIED. Market baseline stays MISSING.** No blanket acceptance.

## Download access — stopped at login
- `GET https://www.kaggle.com/api/v1/datasets/download/cviaxmiwnptr/nba-betting-data` returned **HTTP 403** without credentials.
- The dataset metadata endpoint `.../datasets/view/...` returned **403** ("Permission 'datasets.get' was denied").
- The public dataset page returned 404 to the fetch tool.
- **Download needs a Kaggle account/API token.** Per the instruction I stopped and did **not** use the repo's `SPORTSEDGE_KAGGLE_*` secrets or any account.
- No archived copy exists on this sandbox's view of the repo's `data` branch (`archive/nba-kaggle-odds/` not found).

So **no row of this dataset was inspected**. Everything below is either unverifiable or comes from claims already in the repo.

## What the repo claims (`scripts/archive_kaggle_nba_odds.py` registry note; `docs/keyed-archival-setup.md`)
| criterion | claim in repo | verified? | needed to verify |
|---|---|---|---|
| Provenance | "CC0. NBA Oct 2007-Jun 2026. SportsbookReviewsOnline consensus close" | **No.** Licence and upstream are second-hand. Kaggle page not readable. | Dataset card + file list. Upstream SBR archive terms. |
| Paired / two-sided prices | ML home+away, spread line, total line. Juice columns are optional ("may be empty → MISSING") | **No.** If spread/total juice is absent, those legs are one-sided lines with no price, so they are not usable for no-vig probability. | Inspect columns for both sides' prices per market. |
| Timestamps / open vs close | "consensus close", one row per game, no capture timestamp | **No.** No time-of-quote field is known; "close" is a label, not a timestamp. | A per-quote timestamp, or documented close-time definition. |
| Book identity | "consensus" (multi-book blend), not DraftKings | **No.** Not a single-book price; not DK. | A book column. As described, it can never stand in for a DK baseline. |
| Settlement | scores included; push handling unknown | **No** | Final-score source; whole-number line convention. |
| Coverage | 2007-08 → 2025-26 claimed | **No** | Row counts per season; missing games; playoffs flag. |

## Ruling for use
- **Not accepted.** At best, after a login-backed download is approved and the checks above pass, this dataset could be a **soft "consensus close" research comparator**, with the verdict CONDITIONAL, as the repo's own note says.
- It cannot serve as a paired, timestamped, single-book (DK) market baseline. `market_baseline` stays **MISSING** in all NBA results.
- **Next step needs an owner decision:** approve using the existing Kaggle secret in Actions for a one-time download plus schema/coverage report (still an audit, not acceptance), or drop the dataset.

## Run 2 (owner-approved, final) — renamed slug

- Root cause of run 1: the dataset was **renamed**. The old slug `cviaxmiwnptr/nba-betting-data` 404s (Muse, #2147 comment 6150793524).
- Run 2: Actions run 38435472653, job 115428180154, single-use branch head `1f3e551`, conclusion **success**. Slug `cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024`. Credentials stayed masked (`***`). Only the schema report went to stdout and the artifact. No raw data was committed. No retry, no scheduler.
- Neutralized: the workflow was deleted on the branch in `3921947`. A deleted workflow can't be triggered by its own deletion push; see the run list check in the #2090 checkpoint.

### Findings (schema/coverage/provenance only)
- Title: "NBA Betting Data | October 2007 to June 2026". License CC0. Version 4, last updated 2026-06-15T05:27Z, 2,493,308 bytes.
- One file, `nba_2008-2026.csv`: **24,440 rows**, 27 columns (season, date, regular, playoffs, away, home, scores, q1–q4/ot per side, whos_favored, spread, total, moneyline_away/home, h2_spread, h2_total, id_spread, id_total).
- Seasons 2008–2026, about 1,310–1,323 games per season. Lower counts in 2012 (1,074, lockout), 2020 (1,143) and 2021 (1,171). Regular season 22,808 rows / non-regular 1,632.
- Null rates: spread 0.01%, total 0%, **moneylines 18.94%**, h2_spread/h2_total about 18.9%.
- Provenance, per the dataset description:
  - Oct 2007–Jan 16 2023 comes from SportsbookReviewsOnline (scraped, "fixed a few errors").
  - Jan 17 2023–Jun 22 2025 comes from ESPN, with **no moneyline or 2H odds** and non-integer lines.
  - Since Oct 21 2025 the lines are the **median odds** across books on SportsbookReview.
- There is no timestamp column: no capture time and no open/close label. There is no book identifier.
- `spread` is always positive, with direction carried in `whos_favored`.

### Verdict
- **Not a verified market baseline.** There is no DraftKings pairing: the sources are a mixed or unknown book and, since 2025, a cross-book median. There is no snapshot timing either.
- The NBA verified market baseline stays **MISSING**.
- Usable at most as RESEARCH-only context (scores and settlement cross-check, an approximate line reference), and only under a separate pre-registration flagged for ChatGPT.
- The Kaggle dataset audit is now **complete (schema verified, baseline-ineligible)**. No further runs are approved.
