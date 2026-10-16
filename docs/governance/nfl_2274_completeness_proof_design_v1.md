# #2274 NFL inactive-list completeness PROOF — design v1 (t216u)

Status: DESIGN ONLY. Research-only. No activation, no PLAY authority, no
backfill, no fabricated data. Implementation by the other builder; owner
re-audits. Baseline: main `0f96676f`; reviewed participation repair
`e51c2ba8` (`grok/t208-nfl-2274-completeness-proof-v2-20261015`).

## 0. Problem

A truncated inactive list must never establish participation ("not on the
inactive list ⇒ active"). That negative inference is only valid when the
list is **proven** complete. Today `e51c2ba8` fails closed because the proof
inputs do not exist: every list is `UNKNOWN / INACTIVES_COMPLETENESS_UNVERIFIED`.
This document defines what a proof is, so COMPLETE can become reachable
without becoming assertable.

## 1. Inventory: what data actually exists (verified at 0f96676f / e51c2ba8)

| Source id / name | Exists in repo? | What it is | PIT (before kickoff)? |
|---|---|---|---|
| `NFL_GAMEDAY_INACTIVES` | **Placeholder only.** Appears solely as an allowlisted string in `config/nfl_participation_completeness_v1.json` (e51c2ba8) and the test fixture. No fetcher, no parser, no captured file. | — | — |
| `NFL_GSIS_GAMEDAY_ROSTER` | **Placeholder only**, same as above. No GSIS access code anywhere. | — | — |
| `published_manifest_pins` | Empty (`{"inactives": [], "roster": []}`). | — | — |
| Official NFL gamebook PDFs (`scripts/audit_nfl_2025_gamebook_inactives.py`) | Audit script only; no captured gamebooks or hashes committed. Uses api.nfl.com anonymous web-client token. | Post-game official gamebook, has an explicit INACTIVES section per team. | **No** — published after the game. Retrospective verification only. |
| Pre-kick inactive articles (`scripts/audit_nfl_2025_prekick_inactive_articles.py`) | Audit script only. | Media reports. | Sometimes, but not official and not completeness-bearing. |
| nflverse `weekly_rosters/roster_weekly_<season>.csv` (`scripts/audit_nfl_prop_v1_sources.py`) | Fetched by audit scripts; not archived as evidence. | Weekly roster with `status` (ACT/INA/RES/...). | **No** — release is rebuilt after the week; `status` is not a timestamped gameday snapshot. |
| nflverse `pbp_participation_<season>.csv` | Fetched by validation/live-feature pipelines. | Players on field per play. | **No** — post-game. Shows who played, cannot prove who was inactive. |
| nflverse `injuries_<season>.csv` (`injury_report_source.py`) | Fetched live. | Weekly injury report statuses (OUT/DOUBTFUL/…). | Yes, but not a gameday inactive list and never complete for healthy scratches. |
| nflverse `depth_charts` | Fetched live (`fetch_nflverse_depth_charts`). | Depth snapshot. | Yes, not a roster-of-record. |

**Conclusion:** there is currently **no pre-kickoff official source in the
repository that can prove completeness.** The two official sources the
contract names are placeholders. Every proof attempt pregame must therefore
remain UNKNOWN until a real gameday-inactives capture and an independent
gameday-roster capture exist, are archived, and are externally pinned.
Post-game sources (gamebook, weekly roster, participation) can be used only
for *retrospective audit* of a recorded verdict, never to upgrade a pregame
verdict.

## 2. Proof object

A proof is a per-(game_id, team) record built only from archived bytes:

```
CompletenessProof {
  game_id, team, kickoff_utc, cutoff_utc,
  inactives:  SourceSnapshot   # source_id ∈ allowlist.inactives
  roster:     SourceSnapshot   # source_id ∈ allowlist.roster, ≠ inactives source
  active_ids: [player_id]      # from the roster snapshot's gameday status, or from the inactives source's own active list
}
SourceSnapshot {
  source_id, url, fetched_at_utc, source_published_at_utc,
  raw_sha256,                   # sha256 of exact archived bytes
  completeness_marker,          # source's own field, verbatim (see §3 F5)
  team_rows: [{player_id, status}]
}
```

`raw_sha256` must be listed in an **external pin manifest** (§4). Pins never
come from the proof payload or the caller.

## 3. COMPLETE: exact facts that must ALL hold

For one (game_id, team) the verdict is `COMPLETE` iff every fact F1–F10 holds.
Any failed, missing, unparseable, or unevaluable fact ⇒ `UNKNOWN` (never
`INCOMPLETE`-then-guess, never partial credit, never fallback).

- **F1 Pinned bytes.** Both snapshots' archived bytes exist and their sha256
  equals an entry in the external pin manifest for exactly this
  game_id + team + source_id. The manifest's own sha256 matches the pin held
  outside it (§4).
- **F2 Allowlisted, independent sources.** `inactives.source_id` is in the
  committed inactives allowlist, `roster.source_id` in the roster allowlist,
  the two ids differ, their hosts/publishers differ (declared `publisher`
  field in the allowlist), and their pins differ. A single feed re-served under
  two names is not independent: the allowlist must declare each source's
  publisher, and equal publishers fail F2.
- **F3 Timing.** `source_published_at ≤ cutoff ≤ kickoff` and
  `fetched_at ≤ cutoff` for both; `fetched_at ≥ kickoff − 120 min` for the
  inactives snapshot (NFL inactives are released ~90 min before kickoff; an
  earlier list is a different, pre-release object). Timestamps must be
  timezone-aware. Clock skew allowance ≤ 120 s.
- **F4 Exact identity.** Both snapshots name exactly this game_id and team
  (team code normalized by the existing `_team` map), and the opponent and
  kickoff in the snapshot match the independently frozen schedule within
  15 min. No re-binding of another game's list.
- **F5 Source completeness marker.** The inactives snapshot carries the
  source's own finality marker (e.g. a `final`/`official` flag or status
  string as defined per source in the allowlist), with the expected value,
  verbatim. Absence of a defined marker for that source ⇒ F5 fails. The
  marker is evidence of the publisher's claim, not proof by itself.
- **F6 Roster reconciliation (count).** Let R = gameday roster ids for the
  team (roster snapshot), A = active ids, I = inactive ids.
  `A ∩ I = ∅`, `A ∪ I = R`, ids are distinct non-empty strings, and
  `|A| ≤ 48` (46 + the 47th/48th practice-squad elevation / emergency-QB
  allowances, both configurable and declared in the allowlist, not inferred),
  `|I| ≥ 1`, and `|R| = |A| + |I|` equals the roster snapshot's own declared
  count field when the source provides one.
- **F7 Cross-source agreement.** The set of inactive ids in the inactives
  snapshot equals the set of roster ids carrying the roster source's
  inactive status, exactly. Any disagreement (missing or extra id) ⇒ UNKNOWN.
- **F8 Single latest snapshot.** Among all pinned snapshots for this
  game/team/source at or before cutoff, exactly one is latest; ties with
  different content ⇒ UNKNOWN. A later conflicting snapshot (still ≤ cutoff)
  supersedes; there is no "any complete snapshot wins".
- **F9 Candidate membership.** The candidate player id is in R. A candidate
  not on the gameday roster at all is UNKNOWN for participation (not ACTIVE).
- **F10 Freshness of trust config.** The allowlist and pin manifest loaded are
  the committed versions verified by their external pin (§4); a missing or
  edited config ⇒ UNKNOWN for every game.

Only when F1–F10 all hold may the negative inference "candidate ∉ I ⇒
GAMEDAY_ACTIVE" be drawn. If the candidate ∈ I, the verdict is OUT /
OFFICIAL_INACTIVE regardless of completeness (an explicit official inactive
listing is positive evidence; F1–F4 still required for it to count as
official).

Row count alone, a caller `complete=True` flag, an in-process token, a
self-hashed manifest, or a "≥ N rows" floor are **never** proof
(`MIN_OFFICIAL_INACTIVE_SNAPSHOT_ROWS` stays a sanity floor only).

## 4. External pinning

- Pin manifest: `config/trusted/nfl_participation_source_pins_v1.json`
  listing `{game_id, team, source_id, raw_sha256, archived_path}`.
- The manifest's sha256 is pinned in code (`PINNED_PARTICIPATION_MANIFEST_SHA256`
  in the verifier module) — the same pattern as the t214 NFL V1 live pin — so
  neither the manifest nor the evidence carries the value that protects it.
- New pins are added only by a reviewed commit after capture; the capture job
  may write archived bytes but never the manifest or the code pin.
- Residual risk (state in audit): a single change editing manifest + code
  constant together defeats the pin; mitigation is CODEOWNERS/branch protection
  on `config/trusted/**` and the verifier module (owner setting).

## 5. What must be built before COMPLETE is ever reachable

1. A real pregame **official inactives** capture (source to be chosen and
   allowlisted by the owner; must be official NFL/club publication), archived
   byte-exact with fetched_at, published_at and the per-source finality marker.
2. A real, **independent** pregame **gameday roster** capture (different
   publisher) giving R with per-player gameday status.
3. Per-source parsers and the per-source marker definition in the allowlist.
4. The pin manifest + code pin (§4).
Until 1–4 exist, the correct and only output is UNKNOWN. Post-game gamebook /
nflverse weekly roster / participation may be used in a separate
retrospective audit that reports agreement rates, and never feeds back into a
recorded pregame verdict (no backfill).

## 6. RED test plan (write first; each must fail on current code or on a naive implementation)

Fixtures are synthetic, labelled "synthetic, not evidence", and generated
in-test; no real player data is fabricated as if captured.

| # | Test | Expect |
|---|---|---|
| R1 | Valid two-source proof, all F1–F10 hold | COMPLETE; candidate not in I ⇒ GAMEDAY_ACTIVE |
| R2 | Truncated inactives list (drop 1 of I) with internally consistent row count ≥ floor | UNKNOWN (F6/F7) |
| R3 | Inactives bytes edited, internal hash recomputed | UNKNOWN (F1) |
| R4 | Pin manifest missing / edited / whitespace change | UNKNOWN for all games (F1/F10) |
| R5 | Both snapshots from the same publisher under two source ids | UNKNOWN (F2) |
| R6 | Same pin used for both snapshots | UNKNOWN (F2) |
| R7 | Inactives published after cutoff; fetched after cutoff; published > kickoff; naive timestamps | UNKNOWN (F3) |
| R8 | Inactives fetched > 120 min before kickoff | UNKNOWN (F3) |
| R9 | Snapshot for the other team / other game / rescheduled kickoff > 15 min off | UNKNOWN (F4) |
| R10 | Finality marker absent or wrong value | UNKNOWN (F5) |
| R11 | A ∩ I ≠ ∅; A ∪ I ≠ R; duplicate ids; empty id; \|A\| = 49 | UNKNOWN (F6) |
| R12 | Roster declared count ≠ \|A\| + \|I\| | UNKNOWN (F6) |
| R13 | Roster's inactive-status set differs from inactives list by one id (extra or missing) | UNKNOWN (F7) |
| R14 | Two latest snapshots same timestamp different content; later conflicting snapshot ≤ cutoff | UNKNOWN (F8) |
| R15 | Candidate absent from R | UNKNOWN (F9) |
| R16 | Candidate in I with F1–F4 holding but F6 failing | OUT / OFFICIAL_INACTIVE |
| R17 | Caller passes `complete=True`, pins in evidence payload, or operator pins for a source not on allowlist | ignored ⇒ UNKNOWN |
| R18 | Real committed config today (placeholders, empty pins) | every game/team UNKNOWN |
| R19 | Post-game sources (gamebook/weekly roster/participation) supplied as roster source | UNKNOWN (not allowlisted, F3) |
| R20 | #2363's five adversarial completeness tests | still pass |
| R21 | Property test: randomly drop/add one id in any component of a valid proof | never COMPLETE |

Acceptance: all R1–R21 green on one exact head, full suite zero failures,
exact-head hosted CI, independent owner re-audit. Completeness proof grants
no Model_P, PLAY, staking, promotion or OFFICIAL authority.
