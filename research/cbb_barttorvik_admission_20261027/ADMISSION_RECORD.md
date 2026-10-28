# Admission record — BartTorvik T-Rank archive (CBB ratings)

**Status: SAMPLE-VERIFIED / ADMISSION PROPOSED — DESIGN ONLY — NOT VALIDATION —
NO FORWARD-CLOCK CREDIT — NO PLAY ELIGIBILITY.**
Prepared 2026-10-27 (retrieval 2026-10-28T03:56:18Z) for independent review.
This record admits nothing by itself: admission takes effect only if this PR is
merged after independent (Rocky) review. Even then, the data is a **design /
baseline input only** — it can never serve as validation evidence, never earns
forward-clock credit, and never prices a card by itself.

Every factual claim below carries an evidence state: **verified-by-pull**
(bytes were downloaded from the SportsEdge runtime and hash-checked) or
**documented-only** (stated by the provider's documentation; not reproduced
here).

## 1. Source and provenance

- **Source:** BartTorvik **T-Rank** team ratings (adjusted offensive /
  defensive efficiency, adjusted tempo, *barthag*, WAB), published by
  Bart Torvik at barttorvik.com. **Documented-only** as to authorship;
  the T-Rank methodology is Torvik's.
- **Access route admitted for design use (verified-by-pull):** the
  `andreweatherman/toRvik-data` GitHub repository — the CSV data mirror that
  backs the R package **toRvik**'s `bart_archive()` function in its
  GitHub-documented source (rdrr.io snapshot of `R/bart_archive.R` reads
  `ratings/archive/by_date/ratings_archive_{YYYYMMDD}.csv` from that repo).
  The mirror is pinned **by commit**, not by branch:
  `46d1036443ca452fdd1c6cf25cf5dff50de68337` (the repository's `main` head,
  last pushed 2023-06-20 — verified-by-pull via the GitHub API).
- **Route NOT admitted (documented-only):** current CRAN toRvik (≥1.1.1)
  reads `https://api.cbbstat.com/ratings/archive`. A probe of that endpoint
  from the SportsEdge runtime on 2026-10-28 **failed** (connection closed
  without response; curl exit 000, Python `RemoteDisconnected`). This route
  is **NOT ADMITTED** until a probe succeeds from the runtime and its bytes
  are hash-pinned in a successor manifest.
- **KenPom is NOT ADMITTED** — it is a paid subscription source, excluded by
  owner ruling. No KenPom data enters CBB design or validation via this
  record, directly or through any mirror.

## 2. The morning-of as-of rule (binding on any use)

toRvik documents `bart_archive` as returning *"T-Rank ratings and efficiency
metrics from the morning of the specified day"* (documented-only — this is
the provider's own description of the archive's semantics, and it is the
strongest point-in-time property any free CBB ratings source offers).

The rule for SportsEdge, fixed here before any use:

1. A rating row for archive date **D** is the rating **as of the morning of
   D**. It is the only Torvik input that may be used for games played on D.
2. **No same-day post-game data may price that day's games.** Results of
   games played on D are first reflected in the archive for D+1 or later.
3. Ratings for a target date must be read from that date's archive file —
   never reconstructed later from current ratings, season-final ratings, or
   a different date's file. Back-filling a morning-of rating after the fact
   from any other vintage is **lookahead** and a refusal (`LOOKAHEAD_RISK`).
4. If the archive file for D does not exist on the admitted route, the
   rating for D is `NO_DATA` — never substituted from D−1 or D+1 silently;
   any carry-forward must be declared in the consuming design, with its own
   review.

## 3. Reproducibility — pinned retrieval, hash-verified samples

Retrieval is by the committed script `pull_bart_archive.py` (stdlib only),
which fetches the by-date CSV at the **pinned commit** URL recorded in
`sample_manifest.json`, computes SHA-256, counts team rows, and verifies
every row's `date` field equals the requested archive date.

| Archive date | Bytes | Team rows | SHA-256 | Evidence |
|---|---|---|---|---|
| 2022-01-13 | 58,716 | 358 | `4de4761caf3f581c56d9587ac9deeb954556ee5a8529948d8ef5206f9dfe14ad` | verified-by-pull |
| 2023-03-12 | 60,010 | 363 | `9524481d69c7b690200299387690654091565ef1d3df774ca858749e5e1cc01c` | verified-by-pull |

Re-pull check performed 2026-10-28: the pinned-commit URL for 2022-01-13
returned bytes with the identical SHA-256 above. Columns observed:
`rank, team, conf, record, barthag, adj_o, adj_o_rk, adj_d, adj_d_rk,
adj_tempo, adj_tempo_rk, proj_record, proj_conf_record, wab, wab_rk, date`.

## 4. Known limitations (read before designing on this)

- **Coverage ends in the 2022-23 season on the admitted route**
  (verified-by-pull): archive probes for 2024-03-01 and 2025-11-03 return
  HTTP 404; the mirror has not been updated since 2023-06-20. This record
  therefore admits Torvik ratings as a **historical design baseline**
  (2014-15 → 2022-23 per toRvik documentation; samples verified for
  2021-22 and 2022-23). It does **not** put 2026-27 morning-of ratings in
  hand. A live-season route (api.cbbstat.com or a successor mirror) needs
  its own successful probe + hash pin before any 2026-27 use.
- **Schema drift** (verified-by-pull): the 2023-03-12 file carries a leading
  unnamed index column the 2022-01-13 file lacks. Parsers must key columns
  by header name and refuse on unrecognised layout (`SCHEMA_INVALID`).
- **Team identity is name-based in this source** (`team`, `conf` strings;
  no ESPN/NCAA IDs). Joins to the hoopR substrate must go through an
  admitted crosswalk — which does not yet exist as an admitted artifact
  (see the hoopR substrate admission record). Name-only joins are refused.

## 5. License and terms

- T-Rank data is Bart Torvik's. The `toRvik-data` mirror carries **no
  license file** (verified-by-pull via the GitHub API: `license: null`), so
  no redistribution right is granted or assumed. barttorvik.com's own terms
  govern the underlying data.
- Accordingly: this repository stores **hashes, manifests and retrieval code
  only — no sample data files are committed** — and any Torvik-derived
  artifact stays internal research material. No republication of T-Rank
  tables on cards, posts, or public artifacts.

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

`SOURCE_UNAVAILABLE` (route probe fails), `ARCHIVE_DATE_MISSING` (404 for
the requested date), `SCHEMA_INVALID`, `DATE_MISMATCH` (row dates ≠ archive
date), `LOOKAHEAD_RISK` (any non-archive vintage offered for a date),
`SOURCE_CHANGED_AFTER_SNAPSHOT` (re-pull hash ≠ manifest hash),
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
2. Separately: whether to pursue the live-season Torvik route
   (api.cbbstat.com probe from an environment where it answers, then a
   successor hash-pinned manifest) before relying on any 2026-27 ratings.
3. Separately: the identity-crosswalk admission (ESPN ↔ Torvik ↔ NCAA),
   without which Torvik rows cannot join fixtures at all.
