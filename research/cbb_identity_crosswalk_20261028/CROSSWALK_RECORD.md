# CBB Team Identity Crosswalk — Record

**Artifact:** `CBB_TEAM_IDENTITY_CROSSWALK_V1` (`crosswalk.json`, this packet)
**Status:** IDENTITY ARTIFACT. This is **NOT a source admission**, not a
freeze, and not a screen. It edits no design text and no criterion, and
confers no validation credit, no forward-clock credit, and no play
eligibility (`design_only: true`, all credit flags false in the
artifact).

## Why this exists

The CBR successor manifest (PR #2871) recorded, in its own words, that
"the ESPN/Torvik/NCAA identity crosswalk is OPEN and NOT admitted," and
that the screens' three-way name-join was a design-evidence expedient.
Both CBB constructions that passed their design screens —
CBB_TORVIK_EFFICIENCY_V1 (PR #2891) and the CBB team-totals
construction (PR #2892) — carry a section 5 gate: an identity crosswalk
must exist before either can be considered for a freeze. This packet
builds that crosswalk as a governed artifact. The Nov 1 capture
pre-check (07:00 CT) matches ESPN/DK slates against model teams through
it.

## What the crosswalk is

- **Canonical spine:** the 365 teams of the admitted Torvik live route
  (PR #2841) — the 2026-10-28 morning-pull vintage of
  `2027_team_results.csv`, sha256
  `54bf01840c98782c404a5f97ca07b5f9454da98f361d80d1ea6f2a92b77ab44f`,
  verified against its pull manifest before use.
- **Canonical id:** the school's CBR slug where the school appears in
  the pinned CBR bytes (continuity with the screens' audited join,
  whose canonical keys are CBR slugs); otherwise a minted slug from
  the Torvik name (lowercase, spaces → hyphens, `[a-z0-9-]` only).
  Registry size: **369** = 365 spine members + 4 historical-only
  schools present in the 2015–2023 sources but not in the 2026-27
  Torvik universe: `hartford`, `saint-francis-pa`, `savannah-state`,
  `st-francis-ny`.
- **Minted canonical ids (exactly 5):** `mercyhurst`, `west-georgia`,
  `le-moyne`, `new-haven`, `west-florida` — schools that entered (or
  are entering) Division I after the pinned CBR scope ends (2022-23)
  and therefore have no CBR slug in the admitted bytes. Each is flagged
  `MINTED_NO_CBR_SLUG_IN_PINNED_SCOPE` in the artifact.
- **Sources mapped:** Torvik (spine names + archive-route names from
  the PR #2832 pinned commit `46d10364…`, 27 date files — the same
  dates the PR #2871 proof used), CBR (Team / TeamFull / Opponent
  surfaces from the six pinned mirror files, PR #2871 pins), hoopR
  (location + display-name surfaces and the ESPN team ids its schedule
  rows carry natively, nine pinned CSVs, PR #2867 pins), ESPN (a
  build-time reference pull of the public site API: the 362-team list
  plus four event summaries, hash-pinned in the artifact — a reference
  pull for identity binding, **not** an admission of any ESPN route).

## Matching discipline

Exact matches and table-driven overrides ONLY. **No fuzzy matching, no
string similarity, no transformation rules at resolve time.**
Resolution order, published in the builder:

1. `OVERRIDE` — the table below.
2. `CBR_URL_NATIVE` — a CBR Team/TeamFull surface binds to the slug in
   its own row's `/cbb/schools/<slug>/` URL.
3. `CBR_SURFACE` — the surface exactly equals a harvested CBR Team or
   TeamFull surface. (The harvest was verified unambiguous: every such
   surface binds exactly one slug across all six pinned files.)
4. `TORVIK_SPINE_NAME` — the surface exactly equals a spine name.

Team **ids** (the ESPN id space hoopR carries) bind only where every
location surface co-occurring with the id resolves to one canonical
id. An id shared with an unresolved school stays unbound: e.g. ESPN id
2419 appears for both Cincinnati and Mount St. Joseph in the pinned
schedules and is published unbound rather than bound to Cincinnati.

## The override table — relationship to PR #2871

Artifact total: **211 entries = 41 + 170.**

- **PR #2871's 41 entries: carried VERBATIM. Zero changed, zero
  dropped.** The builder refuses (exit 2) if any assembled layer would
  change a #2871 target or contradict the CBR harvest, and
  `tests/test_cbb_identity_crosswalk.py` pins all 41 pairs.
- **170 CROSSWALK_EXTENSION entries**, each with a justification string
  in the artifact:
  - 60 Torvik "St."-class forms (`Iowa St.` → `iowa-state`, …): the
    builder asserts each entry's expanded form (`Iowa State`) is a
    harvested CBR Team surface for the same slug before accepting it.
  - 55 general extensions: renamed schools (IU Indy → `iupui`,
    East Texas A&M → `texas-am-commerce`, UT Rio Grande Valley →
    `texas-pan-american` — CBR kept the legacy slugs), Torvik archive
    era forms (IPFW, Dixie St., LIU Brooklyn, Louisiana Lafayette,
    Savannah St., …), hoopR forms (Hawai'i, San José State, Seattle U,
    McNeese, St. Thomas-Minnesota, St. Francis Brooklyn, …), and the
    ESPN location forms (App State, IU Indianapolis, LSU New Orleans
    — ESPN id 2443 is the University of New Orleans under its
    historical LSUNO name).
  - 55 display-name (school + mascot) forms used by hoopR/ESPN, each
    verified against the ESPN team-id co-occurrence in the pinned
    schedules (the surface's rows bind to exactly one canonical) or,
    for the minted schools, the ESPN teams pull.
- One deliberate non-entry: the surface **`Miami` never resolves by
  name.** Two D1 schools share the string; it is published UNRESOLVED
  with reason `AMBIGUOUS_SURFACE_NAME_ONLY_JOIN_FORBIDDEN` in both
  `espn_location` (1 occurrence) and `hoopr_location` (302 team-games,
  all carrying ESPN id 2390). Miami (FL) is fully bound by id 2390 and
  by its display name `Miami Hurricanes` → `miami-fl`.

Verified traps, all bound distinctly in the artifact: Torvik
`San Diego` = University of San Diego (`san-diego`) — **not** San
Diego State (`san-diego-state`, Torvik `San Diego St.`) and **not**
UC San Diego (`california-san-diego`); Utah Tech's canonical is the
legacy slug `dixie-state`; Loyola Chicago is `loyola-il`, Loyola (MD)
is `loyola-md`, Loyola Marymount is `loyola-marymount`.

## Coverage (builder output; independently re-derived by the verifier)

| Source surface set | Total | Resolved | UNRESOLVED |
|---|---|---|---|
| Torvik spine names (2026-27) | 365 | **365** | 0 |
| Torvik archive names (27 pinned files) | 368 | **368** | 0 |
| CBR Team | 388 | **388** | 0 |
| CBR TeamFull | 379 | **379** | 0 |
| CBR Opponent | 1,199 | 379 | 820 |
| hoopR location | 1,266 | 370 | 896 |
| hoopR display name | 1,286 | 373 | 913 |
| ESPN location | 362 | 361 | 1 (`Miami`, ambiguous) |
| ESPN display name | 362 | **362** | 0 |

ESPN team ids: hoopR schedules carry 1,163 distinct ids; 366 bind by
the co-occurrence rule; with the ESPN teams pull, **369 distinct ids
are bound in total, all 362 pulled ESPN teams are bound, and all 365
spine teams carry an ESPN id.** 796 ids stay unbound — they belong to
non-D1 schools (and partial cases like id 2419). Zero ids resolved to
two different canonicals.

## The UNRESOLVED lists are a deliverable

Every unresolved surface is published in `crosswalk.json` under
`unresolved.<source>` with its occurrence count and reason. Their
composition is the expected one for a Division I identity artifact:
the CBR Opponent, hoopR location, and hoopR display-name sets include
every non-D1 opponent those schedules contain (D2/D3/NAIA schools —
Bethesda University, Carver College, Chaminade, Alaska Anchorage,
hundreds more), and **no unresolved surface in any set is a current
Division I school name**, with the single deliberate exception of the
ambiguous string `Miami` above (verified by cross-checking the
unresolved sets against the 362-team ESPN list and the spine). A
surface that cannot be resolved is listed, never guessed: that list is
what a future pull is checked against (see "Staying current").

## Fixture proofs (re-derived end-to-end by the verifier)

Three NCAA championship games agree across **all four** sources —
same canonical pair, same scores wherever the source carries scores
(Torvik archive files carry team presence, not scores):

| Game | CBR | hoopR (ESPN id) | Torvik archive | ESPN event |
|---|---|---|---|---|
| 2015 final: Duke 68, Wisconsin 63 | ✓ | 400788981 ✓ | 20150406 file, both present | ids 150/275, 68/63 ✓ |
| 2022 final: Kansas 72, North Carolina 69 | ✓ | 401408636 ✓ | 20220404 file, both present | ids 2305/153, 72/69 ✓ |
| 2023 final: Connecticut 76, San Diego State 59 | ✓ | 401522202 ✓ | 20230403 file, both present | ids 41/21, 76/59 ✓ |

Forward proof — the Nov 1 pre-check path: ESPN event **401920982**
(Eternal City Tip-Off, Rome, 2026-11-01T14:30Z) resolves Notre Dame
(ESPN id 87 → `notre-dame`) and Villanova (id 222 → `villanova`),
both spine members. CBR/hoopR legs cannot exist for an unplayed game;
the DK leg joins at capture time through the same ESPN event id.

## Illinois exclusion

Illinois college teams remain **excluded from capture scope** by
standing law. Identity is not capture: the 13 Illinois schools stay in
the crosswalk (the screens' historical evidence includes their games),
flagged `capture_excluded_illinois: true`, and the
exclusion applies downstream, unchanged. The flag is driven by the same ESPN id
denylist the downstream capture scope enforces
(`sportsedge/cbb_capture_scope.py`, `_ILLINOIS_ESPN_MBB_2027_DENYLIST`,
13 ids reconciled there against the NCAA 2026-27 D1 Illinois
directory): bradley, chicago-state, depaul, eastern-illinois, illinois,
illinois-chicago, illinois-state, loyola-il, northern-illinois,
northwestern, southern-illinois, southern-illinois-edwardsville,
western-illinois. The verifier fails if the flagged set and the
denylist ever disagree.

## Scope limits (honest)

- Mapped surfaces are the name/id forms present in the pinned pulls.
  Abbreviations are deliberately **not** mapped (collision-prone —
  e.g. `MSU`), nor are ESPN `shortDisplayName` strings (truncated
  forms like `Abilene Chrstn` are not exact names).
- DraftKings team names are not a mapped source in this packet; the
  Nov 1 pre-check joins DK slates to this crosswalk through the ESPN
  event id and the ESPN/Torvik surfaces at capture time.
- The Torvik archive and ESPN pulls are pinned by sha256 recorded in
  the artifact; the archive route is pinned by git commit as in
  PR #2832. The ESPN teams/event pulls were taken 2026-10-28 from the
  public site API for identity binding only.

## Staying current — the tripwire

`verify_crosswalk.py` re-derives every surface set from the pinned
pulls, re-runs the published chain with the artifact's own tables,
and diffs. **If a future pull introduces a team surface the artifact
neither resolves nor lists as UNRESOLVED, verification exits 3 and
names the new surfaces** (`unmapped_surfaces()`), forcing a governed
crosswalk update instead of a silent downstream name-join miss. The
builder (`build_crosswalk.py`) regenerates `crosswalk.json`
deterministically from the same pulls; both are stdlib-only.

Commands (from this packet's directory):

```
python3 build_crosswalk.py     # regenerate crosswalk.json
python3 verify_crosswalk.py    # independent verification (exit 0 = verified)
python3 -m pytest tests/test_cbb_identity_crosswalk.py   # from repo root
```
