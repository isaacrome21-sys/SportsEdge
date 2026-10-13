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

## Owner-approved one-time Actions audit run (2026-10-13 11:49 CT)
- **Setup.** Workflow `.github/workflows/audit-kaggle-nba-odds-once.yml` (c91d47f). It is triggered only by a push to the single-use branch `audit/kaggle-nba-odds-once-20261013`; there is no schedule. Report-only script: `scripts/audit_kaggle_nba_odds_schema.py`.
- **Run.** Run 38433667421, job 115422029561, ran **once**: **FAILED with `KAGGLE_HTTP_403`** on the dataset download.
  - The secrets were present and masked (`***` in the log). Nothing was printed or exposed.
  - No data was downloaded, no report artifact was produced, and nothing was committed.
- **Interpretation (unconfirmed).** A 403 with credentials, plus a 404 on the public dataset page, suggests one of:
  - the dataset was removed, renamed or made private;
  - the Kaggle token is invalid or expired;
  - the account lacks access.

  I can't tell which from here. The metadata call also failed, and the script records that error without detail.
- **Not retried.** The approval was for a single run.
- **Findings on schema, seasons, books, two-sided prices, timestamps, settlement fields, row counts and null rates: NONE OBTAINED.**

**Status unchanged: UNVERIFIED, not accepted, market baseline MISSING.**

**Owner options:**
1. Confirm the dataset still exists (browser, logged in) and its current slug.
2. Check or rotate the `SPORTSEDGE_KAGGLE_*` secret.
3. Then approve exactly one more run, or drop the dataset.

The single-use branch is still in place. Deleting it needs owner approval.
