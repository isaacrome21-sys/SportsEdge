# Admission record — BartTorvik T-Rank LIVE-season route (CBB ratings)

**Status: SAMPLE-VERIFIED / ADMISSION PROPOSED — DESIGN ONLY — NOT VALIDATION —
NO FORWARD-CLOCK CREDIT — NO PLAY ELIGIBILITY.**
Prepared 2026-10-28 (retrieval 2026-10-28T04:07–04:14Z) for independent review.
This record admits nothing by itself: admission takes effect only if this PR is
merged after independent (Rocky) review. Even then, the data is a **design /
baseline input only** — it can never serve as validation evidence, never earns
forward-clock credit, and never prices a card by itself.

This record is the live-season successor to the historical admission in
PR #2832 (`research/cbb_barttorvik_admission_20261027/`), which admitted Torvik
only as a **historical** design baseline because the `toRvik-data` mirror ends
in the 2022-23 season. #2832's §9 left the live-season route as an open owner /
reviewer item. This record closes that item: a working live route exists and
is pinned below.

Every factual claim below carries an evidence state: **verified-by-pull**
(bytes were downloaded from the SportsEdge runtime and hash-checked) or
**documented-only** (stated by the provider's documentation or package
source; not reproduced here).

## 1. Source, provenance, and the route-by-route probe log

- **Source:** BartTorvik **T-Rank** team ratings (adjusted offensive /
  defensive efficiency, adjusted tempo, *barthag*, projected records),
  published by Bart Torvik at barttorvik.com. **Documented-only** as to
  authorship; the T-Rank methodology is Torvik's.

All five candidate routes were actually executed or inspected on
2026-10-28 from the SportsEdge runtime:

- **Route 1 — `api.cbbstat.com` (`/ratings`, `/ratings/archive`): FAILED**
  (verified-by-pull). The TLS handshake completes (valid certificate,
  TLS 1.3) but the server then closes the connection without any HTTP
  response: `curl: (52) Empty reply from server` on `/`, `/ratings`, and
  `/ratings/archive?date=2025-03-01`, over both HTTP/2 and HTTP/1.1;
  Python `urllib` raises `RemoteDisconnected`; an alternate fetcher could
  not resolve/fetch the URL at all. This reproduces the failure recorded
  in #2832. **NOT ADMITTED.**
- **Route 2 — cbbdata API (`cbbdata.aweatherman.com`): documented-only.**
  The docs site itself answers (HTTP 200). Registration is free:
  `cbd_create_account(username, email, password, confirm_password)`
  creates a CBBData account and an API key is emailed to the registrant.
  A key would unlock cbbdata's dated ratings/archive endpoints — **but the
  API host is `api.cbbstat.com`**, the same host that closes connections
  from this runtime (Route 1). A key therefore does not, by itself,
  establish a working route from here. Recorded as an **owner-decision
  item** (§9), not a dependency.
- **Route 3 — `barttorvik.com/{year}_team_results.csv`: WORKS**
  (verified-by-pull). HTTP 200 for `year=2027`: the current 2026-27 season
  file — 365 teams, full T-Rank table (rank, team, conf, record, adjoe,
  adjde, barthag, projections). At probe time every record is `0-0` and
  `games_played_total = 0`: the season starts Nov 1–2, 2026, so the live
  file currently carries Torvik's preseason projection vintage and is
  being regenerated now (`Last-Modified: Wed, 28 Oct 2026` on both probe
  rounds). `year=2026` also answers HTTP 200 (365 rows, prior-season
  file); `year=2007` returns HTTP 200 with an empty body and is refused
  by the puller (`SCHEMA_INVALID`); hoopR documents coverage from 2008.
  **This is the admitted route.**
- **Route 4 — hoopR / toRvik from R: mechanism source-verified,
  not executed** (documented-only). No R runtime exists in the SportsEdge
  environment. Source inspection settles what the route would add:
  hoopR's `torvik_ratings()` fetches `/{year}_team_results.csv` from
  barttorvik.com (its source calls `.torvik_text(paste0("/", year,
  "_team_results.csv"))`) — byte-for-byte the Route 3 file, so the R
  wrapper offers no additional data path. toRvik's `bart_archive()` reads
  the `toRvik-data` GitHub mirror (historical only — #2832).
- **Route 5 — GitHub mirrors of current Torvik data: none exists**
  (verified-by-pull). GitHub repository search (`barttorvik`, `torvik`,
  `trank`; sorted by most recently updated) returns applications and
  projects, not a maintained data mirror. The one repository holding
  dated Torvik snapshots (`tdub29/Bart`) stores irregular Bart-vs-Kalshi
  extracts (Feb 2025 / Feb 2026), not a pinnable ratings feed. The
  `toRvik-data` mirror was last pushed 2023-06-20 (GitHub API). A mirror
  would only add a middleman to Route 3 in any case.

- **KenPom is NOT ADMITTED** — it is a paid subscription source, excluded by
  owner ruling. No KenPom data enters CBB design or validation via this
  record, directly or through any mirror. (Note: the owner has said he may
  subscribe to KenPom next week; that changes nothing here until a separate
  admission record is written and reviewed.)

## 2. The morning-of as-of rule for a living file (binding on any use)

The historical archive (#2832) had provider-issued dated files. This route
is a **living file**: barttorvik.com regenerates it as the season
progresses, and §3 shows its bytes drift slightly between regenerations.
The morning-of property is therefore created by SportsEdge's own pull
discipline, fixed here before any use:

1. The puller (`pull_bart_live.py`) is run **once each morning
   (America/Chicago), before that day's first tip**, and the exact bytes
   received are hash-pinned into a dated snapshot. That snapshot — and
   only that snapshot — is the Torvik input for games played on that
   Chicago date **D**.
2. **No same-day post-game data may price that day's games.** A pull taken
   after any of D's games have started is not a morning-of snapshot for D;
   results of games played on D are first reflected in snapshots for
   D+1 or later.
3. Never re-fetch intraday to "refresh" a rating for D, and never
   substitute a later vintage for D's pinned snapshot. Offering any other
   vintage for D is **lookahead** and a refusal (`LOOKAHEAD_RISK`); a
   re-pull whose hash differs from the pinned snapshot is refused as a
   substitute (`SOURCE_CHANGED_AFTER_SNAPSHOT`).
4. If no morning pull exists for D, the rating for D is `NO_DATA` — never
   silently carried from D−1 or D+1; any carry-forward must be declared in
   the consuming design, with its own review.
5. Each snapshot records the pull timestamp (UTC), the America/Chicago
   as-of date, and the site's `Last-Modified` / `ETag` response headers,
   so the vintage is auditable after the fact.

## 3. Reproducibility — pinned retrieval, hash-verified samples

Retrieval is by the committed script `pull_bart_live.py` (stdlib only),
which fetches the season file, verifies the schema (required header names,
365±team-row sanity, `barthag ∈ (0,1)`, `W-L` record format), and prints
a JSON manifest entry with the SHA-256 of the exact bytes received. It
supports `--expect-sha256` to refuse a changed vintage.

| Pull (UTC) | Season | Bytes | Team rows | SHA-256 | Evidence |
|---|---|---|---|---|---|
| 2026-10-28T04:07:31Z (probe) | 2027 | 146,564 | 365 | `eb0711df82e82e88933ae1e6efc38aad883c31b006847467c6727da70ade4cdc` | verified-by-pull |
| 2026-10-28T04:14:03Z (scripted) | 2027 | 146,616 | 365 | `2d7c3b61431f4a7be7cd85a768a3f51bc90624541d70545b6b53e668f5e9b8a4` | verified-by-pull |
| 2026-10-28T04:14:05Z (re-pull) | 2027 | 146,616 | 365 | `2d7c3b61431f4a7be7cd85a768a3f51bc90624541d70545b6b53e668f5e9b8a4` | verified-by-pull |

**Drift finding (verified-by-pull, read before relying on this route):**
pulls 2 seconds apart are byte-identical (same SHA-256 and ETag), but the
04:07 and 04:14 vintages differ: comparing team-by-team, *barthag* changed
for all 365 teams (max |Δ| 0.01074), adjoe max |Δ| 0.37927, adjde max
|Δ| 0.02942, and 19 teams changed rank. The provider promises no
intra-day byte stability — unsurprising for a file regenerated on a live
site — which is precisely why §2 makes the pinned morning pull the only
admitted vintage. The drift is small (ranks nearly stable: 346 of 365
unchanged) and does not affect the file's fitness as a design input under
that discipline.

Columns observed (45): `rank, team, conf, record, adjoe, oe Rank, adjde,
de Rank, barthag, rank, proj. W, Proj. L, Pro Con W, Pro Con L, Con Rec.,
sos, ncsos, consos, Proj. SOS, Proj. Noncon SOS, Proj. Con SOS, elite SOS,
elite noncon SOS, Opp OE, Opp DE, Opp Proj. OE, Opp Proj DE, Con Adj OE,
Con Adj DE, Qual O, Qual D, Qual Barthag, Qual Games, FUN, ConPF, ConPA,
ConPoss, ConOE, ConDE, ConSOSRemain, Conf Win%, WAB, WAB Rk, Fun Rk,
adjt` — the header literally contains `rank` twice, so parsers must key
columns by name with position awareness and refuse on unrecognised layout
(`SCHEMA_INVALID`).

## 4. Known limitations (read before designing on this)

- **Preseason vintage.** Until the season starts (Nov 1–2, 2026) the live
  file is Torvik's projection, not results-based ratings. Designs must
  label early-season snapshots accordingly; the ratings become
  results-informed as games are played, under the same pull discipline.
- **Living-file drift** (§3). Consumers read pinned snapshots only.
- **Site availability is a single point of failure.** If barttorvik.com is
  unreachable on a given morning, that date is `NO_DATA` on this route
  (rule §2.4) — the failure is recorded, never papered over with another
  vintage.
- **Team identity is name-based in this source** (`team`, `conf` strings;
  no ESPN/NCAA IDs). Joins to the hoopR substrate must go through an
  admitted crosswalk — which does not yet exist as an admitted artifact
  (see the hoopR substrate admission record). Name-only joins are refused.
- **No dated archive on this route.** Back-filling a past date's
  morning-of rating from this route is impossible by construction (the
  file only ever shows the current vintage) — which is a feature for
  lookahead discipline, but it means a missed morning pull is permanently
  missed. Historical dates come only from the #2832 mirror (through
  2022-23) or a future admitted archive route.

## 5. License and terms

- T-Rank data is Bart Torvik's; barttorvik.com's own terms govern the
  underlying data, and no machine-readable license grant accompanies the
  CSV. No redistribution right is granted or assumed.
- Accordingly — identical to #2832's precedent: this repository stores
  **hashes, manifests and retrieval code only — no sample data files are
  committed** — and any Torvik-derived artifact stays internal research
  material. No republication of T-Rank tables on cards, posts, or public
  artifacts.

## 6. Illinois college exclusion (requirement, recorded here)

CBB modeling scope **excludes Illinois college teams** (the exclusion is for
college teams only; Illinois professional teams in other sports are in
scope). Any consumer of this source must, before any research pricing or
model output, map both teams of a fixture to school identities through an
admitted ID-based registry and **block the fixture if either school is an
Illinois college** — fail-closed: missing, ambiguous, or name-only identity
is `BLOCKED`, never "outside Illinois by default". Torvik's name strings
alone can never satisfy this check (see §4).

## 7. Refusals

`SOURCE_UNAVAILABLE` (route probe fails), `SEASON_NOT_PUBLISHED` (404 for
the requested season file), `SCHEMA_INVALID` (including the empty-body
response observed for pre-2008 seasons), `LOOKAHEAD_RISK` (any
non-morning-snapshot vintage offered for a date),
`SOURCE_CHANGED_AFTER_SNAPSHOT` (re-pull hash ≠ pinned snapshot hash),
`IDENTITY_UNVERIFIED` (name-only join attempted), `ILLINOIS_COLLEGE_BLOCKED`.

## 8. What this admission does NOT do

- It does not create a CBB engine, preregistration, freeze, or forward
  clock, and it changes no threshold anywhere.
- Backtests run on this data are **design evidence only**. Because any
  future construction will be designed with knowledge of these seasons,
  these seasons can never later be presented as untouched validation.
- Verification for any CBB family accrues **forward only**, from admitted
  pregame captures, under its own preregistration.
- PAPER / research only: 0u, no staking, no wager execution.

## 9. Owner / reviewer decisions still required

1. Accept this DESIGN-only admission (merge of this PR after Rocky review).
   On acceptance, the daily morning pull for the 2026-27 season should be
   wired into the CBB capture routine before the season's first slate so
   no morning-of snapshot is missed (a missed date is permanently
   `NO_DATA` — §4).
2. **Owner-decision (optional, not a dependency):** create a free cbbdata
   account (`cbd_create_account` — username, email, password; API key is
   emailed) to obtain an API key for `api.cbbstat.com`. This would only
   become a usable archive route if that host starts answering from the
   SportsEdge runtime; it is belt-and-braces, and no account was created
   in preparing this record.
3. Separately: the identity-crosswalk admission (ESPN ↔ Torvik ↔ NCAA),
   without which Torvik rows cannot join fixtures at all.
