# NFL inactive-list completeness — proof specification (V1)

Status: mechanism specification for the PR #2274 re-audit evidence package.
Owner ruling it implements: a row count is not completeness. PR #2363's
RED battery (`tests/test_nfl_participation_completeness_proof_red_20261015.py`)
is the contract this specification satisfies; the battery is not edited
by this work. The #2274 HOLD itself lifts only on the owner's re-audit;
this document and its implementation make that re-audit possible.

## The defect

The participation bridge (`sportsedge/nfl_participation_bridge.py`)
originally treated an inactive snapshot as "source-complete" when its
player-id list had at least `MIN_OFFICIAL_INACTIVE_SNAPSHOT_ROWS` (5)
distinct entries. That is a count heuristic: a truncated five-, six-,
seven- or ten-row list — or a seven-row list whose payload sets
`complete=true` — satisfies it while omitting a player, and every
unlisted player is then read as dressed (the negative inference
"not listed => active"). A pinned content digest does not repair this:
a digest proves byte integrity, never publisher authenticity or
exhaustive enumeration.

## Definition — "provably complete"

For one (game, team), the official inactive list is **provably
complete** if and only if a completeness claim supplied with the
evidence verifies under ALL of the following. The verifier is
`sportsedge/nfl_participation_completeness.py`
(`verify_inactives_completeness`); it derives completeness, it never
accepts an assertion of it (a `complete` field anywhere in any payload
is ignored by construction — the claim schema has no such field).

A claim carries three independently sourced parts, each with a source
identity (`source_id`), a source kind, a publication timestamp, and a
player-id list:

1. **Official inactives** — the game-day inactive report. Its source
   kind must be an official kind (`LEAGUE_OFFICIAL` or
   `TEAM_OFFICIAL`). Published on game day: at or before the
   evaluation cutoff, and within 24 hours before kickoff (a prior
   game's list re-bound to this fixture fails the lead window).
2. **Roster enumeration** — the team's full game-day-eligible roster
   from a second source, current within 8 days before kickoff and
   published at or before the cutoff.
3. **Actives publication** — the game-day actives from a third source,
   published on game day under the same window rule as the official
   inactives.

Verification rules (any failure ⇒ status `UNPROVEN` with the named
reason recorded; the consumer fails closed):

- **Presence and form.** All three parts present; every id list is a
  list of distinct, non-empty player ids (`MISSING_*`,
  `ID_LIST_INVALID:*`, `TIMESTAMP_INVALID:*`, `SOURCE_ID_MISSING:*`).
- **Source independence** (Isaac's Oct 13 source-verification rule:
  no single source is ever the only source). The three `source_id`s
  are pairwise distinct (`SOURCE_NOT_INDEPENDENT:*`). The official
  part's kind must be an official kind
  (`OFFICIAL_SOURCE_KIND_UNRECOGNIZED`).
- **Point-in-time discipline.** Every part is published at or before
  the cutoff. A claim with any part after the cutoff is *invisible*
  at that cutoff (counted as excluded evidence), not merely unproven.
  Game-day parts published after kickoff, or outside the 24-hour
  game-day window, are not this game's publication
  (`OFFICIAL_PUBLICATION_STALE`, `ACTIVES_PUBLICATION_STALE`,
  `*_PUBLISHED_AFTER_KICKOFF`, `ROSTER_ENUMERATION_STALE`,
  `ROSTER_ENUMERATION_AFTER_KICKOFF`).
- **Sanity floors.** The official list names at least 5 inactives, the
  roster enumeration at least 40 players, the actives at least 40.
  These are plausibility bounds inside a proof
  (`*_BELOW_SANITY_FLOOR`); they are never sufficient by themselves —
  the rejected count shortcut was a floor used as a proof.
- **Roster arithmetic (the reconciliation).** With I = official
  inactives, A = actives, R = roster enumeration:
  `I ∩ A = ∅` (`ACTIVES_INACTIVES_OVERLAP`) and
  `I ∪ A = R` exactly (`ROSTER_RECONCILIATION_MISMATCH`).
  The inactive list is complete precisely because the independent
  enumeration leaves no rostered player unaccounted for: every
  rostered player is either published inactive or published active.

On success the verifier emits a **proof record**
(`NFL_INACTIVES_COMPLETENESS_PROOF_V1`): the verified inactive id
set, the three counts, the three sources with timestamps, and a
SHA-256 over the record's canonical evidence fields. The hash binds
the record for audit; it authenticates nothing by itself — the proof
is the reconciliation across independent sources, exactly as the
owner's ruling requires.

## Consumption rules (bridge)

- The negative inference ("not listed => dressed", the CONFIRMED
  tier) is available only when a claim for exactly this game/team
  verifies PROVEN **and** no presented evidence contradicts it: any
  player positively named inactive for this game/team (loose
  designation row or snapshot) who is outside the proven inactive set
  contradicts the proof and completeness fails
  (`NAMED_EVIDENCE_CONTRADICTS_PROOF`). Two proven claims for the same
  game/team with different inactive sets also fail
  (`CONFLICTING_PROOF_CLAIMS`).
- Positive evidence is unchanged: a candidate named inactive on any
  loose row or snapshot is OUT regardless of completeness.
- Bare snapshots and loose rows, of any size and with any payload
  flags, are positive evidence only. Without a verified claim the
  verdict is `UNKNOWN / INACTIVES_COMPLETENESS_UNVERIFIED` whenever
  inactive evidence exists for the game/team, exactly as the RED
  battery requires.
- The verdict records the proof (or the first unproven record) under
  `inactives_completeness_proof` so a re-audit can inspect sources,
  timestamps, arithmetic, and the refusal reasons without re-running
  anything.
- Production trust boundary is unchanged (audit B2): the phone
  pricer assembles claims only from a bundle loaded through the
  anchored archive loader with an external manifest pin. Claims in an
  inline payload bundle are never consumed. Until a forward capture
  channel supplies the three parts through that archive, production
  verdicts remain UNVERIFIED — the mechanism defines the evidence
  contract; it does not manufacture the evidence.

## What this does not do

- It does not lift the #2274 HOLD; only the owner's re-audit does.
- It does not authenticate publishers cryptographically; source
  identity plus independent reconciliation is the standard the owner
  set, and the proof record states its sources so the standard is
  auditable.
- It does not change any state vocabulary, gate name, or refusal name
  the existing batteries pin.
