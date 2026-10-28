# Current-Form Analytics — Factoring Spec (2026-10-27)

How the sources in `CURRENT_FORM_ANALYTICS_WIRING_RECORD_20261027.md`
enter the SportsEdge card/research pipeline. Implemented surface:
`sportsedge/current_form/` (fetchers + `context.build_context_block`).

## 1. Hard rules (nothing below overrides these)

1. **Research layer only.** Current-form signals inform the research
   card (LEAN rows and their info packs). They are never a model
   input, never a silent model change, and never enter any frozen
   evaluator, preregistered screen, or count gate.
2. **No status changes.** Nothing in this layer changes a verified
   status, a threshold, the +3% EV headline floor, the −165 price
   cap, the +40% EV overconfidence bucket, or PLAY eligibility.
   PLAY remains for validated families only; as of this spec there
   are none, so every card row stays LEAN / unvalidated estimate.
3. **Labeled, always.** Every signal rides inside a
   `current_form_context` block labeled `RESEARCH_CONTEXT_ONLY` with
   its source, window, pull stamp, and sha256 receipt attached
   (see `sportsedge/current_form/context.py`). An unlabeled
   current-form number on a card is a spec violation.
4. **As-of discipline.** The wiring record's point-in-time rules are
   part of this spec: week-cutoff enforcement for nflverse data;
   pre-game archived pulls for season-to-date surfaces; no
   post-tip/post-first-pitch pull may serve that game; impact
   metrics are pull-date stamped and expire after 7 days.
5. **Fail closed.** A MISSING signal renders as "unavailable" in the
   info pack. It never renders as a neutral/zero value, and a
   missing signal never blocks or fabricates a card row.
6. **FAILED stays retired.** No signal here resurrects a retired
   construction (NFL sides/totals incumbents, CFB PM/AM/blend,
   DIST_V1, NBA ratings incumbents, MLB batter incumbents). Signals
   describe current form; they do not rehabilitate failed models.

## 2. Integration point

The card builder attaches, per game, the dict returned by
`build_context_block(signals, adjustments)`:

```
game["current_form_context"] = {
  "label": "RESEARCH_CONTEXT_ONLY",
  "signals": [...fetcher outputs, receipts hoisted...],
  "suggested_adjustments": [...capped, see §4...],
  "receipts": [...],
  "notice": "Public current-form analytics shown as labeled research
             context. Not a model input; does not change any price,
             probability, verified status, or PLAY eligibility."
}
```

Info-pack rendering shows the fields in §3 verbatim with their
source tags (e.g., `via nflverse NGS`, `via ESPN public JSON`).

## 3. Info-pack fields by sport

### NFL (all WIRED via nflverse + PFR)
| Field | Source | Window / as-of rule |
|---|---|---|
| `ngs_qb_cpoe_l4`, `ngs_qb_ttt_l4`, `ngs_qb_airy_l4` | NGS passing | last 4 completed weeks, volume-weighted |
| `ngs_rb_ryoe_l4`, `ngs_rb_box_l4` | NGS rushing | same |
| `ngs_wr_sep_l4`, `ngs_wr_ayshare_l4` | NGS receiving | same |
| `team_epa_pass_off_l4`, `team_epa_rush_off_l4`, `team_epa_pass_def_l4`, `team_epa_rush_def_l4`, `team_success_l4` | nflverse PBP | last 4 completed weeks; defensive = EPA allowed/play |
| `snap_share_season`, `snap_share_l4`, `snap_share_delta` | nflverse snap counts | delta = L4 mean − season mean (role-change flag at \|delta\| ≥ 0.15) |
| `target_share_l4` | nflverse weekly player stats | last 4 completed weeks |
| `pfr_team_context` | PFR team_stats (HTML) | season-to-date, pre-game archived pull |

### NBA (WIRED: BBR + ESPN; browse-fed: impact metrics, StatMuse)
| Field | Source | Window / as-of rule |
|---|---|---|
| `bbr_pergame_line` | BBR per-game table | season-to-date per-game line for each rotation player; pre-game archived pull |
| `espn_form_l10` | ESPN public JSON (computed) | last 10 completed games ≤ as-of: W-L and average margin, dates listed |
| `espn_standings_line` | ESPN standings payload | record/streak exactly as published; receipt-stamped |
| `impact_epm`, `impact_rapm`, `impact_darko`, `impact_lebron` | Dunks & Threes / nbarapm / databallr (browse-fed) | **season-blend, NOT as-of**; pull date stamped; expires 7 days after pull; entered per §5 |
| `statmuse_crosscheck` | StatMuse (browse-fed) | one natural-language cross-check note, human-verified against a second source before use; never a number source of record |

### CBB (WIRED: Torvik player CSV; SIBLING: Torvik team ratings; browse-fed: KenPom free table)
| Field | Source | Window / as-of rule |
|---|---|---|
| `torvik_trank_line` | BartTorvik T-Rank via sibling PR #2832 | **morning-of rule from the sibling admission**: the ratings as of the morning of the game; no same-day post-game update may price that day |
| `torvik_player_form` | Torvik getadvstats (this layer) | minutes %, ORtg, usage, PORPAG per player; season label + GP read from the rows, never assumed |
| `kenpom_free_line` | KenPom homepage free table (browse-fed) | NetRtg/ORtg/DRtg/AdjT as displayed on the pull date; pull-date stamped; owner-manual until/unless the owner subscribes |
| Illinois college exclusion | standing owner rule | CBB fields are never produced for Illinois college teams; the exclusion is applied by the consumer, and fetcher outputs are never silently pre-filtered |

### MLB (WIRED: Savant leaderboards; ALREADY WIRED: Statcast)
| Field | Source | Window / as-of rule |
|---|---|---|
| `savant_xwoba_gap_batter`, `savant_xba_gap`, `savant_xslg_gap` | Savant expected-statistics leaderboard | season-to-date est − actual gaps; pull archived pre-game; post-first-pitch pull barred for that game |
| `savant_xwoba_gap_pitcher` | same, pitcher table | same |
| `statcast_quality` | `sportsedge/mlb_savant_features.py` (pre-existing) | per that module's own rules (4-day windows, truncation fail-close) |

### Cross-sport (browse-fed only)
| Field | Source | Rule |
|---|---|---|
| `contract_context` | Spotrac (owner-browsed) | contract-year / option status as a narrative note with source + pull date; never a numeric input; automation is 403-blocked and stays that way |
| `bbm_note` | Basketball Monster (owner-browsed) | narrative only; its category-value ranks are never used as performance lines |

## 4. Research-layer adjustments (advisory, capped, displayed)

Adjustments are computed ONLY by `context.capped_adjustment` /
`cap_total`, are displayed next to the LEAN they annotate with raw
value, applied value, and capped flag, and are never folded into a
model probability, price, or EV figure by this layer. Caps (spec
constants; changing them requires amending this spec in the same PR
as any code change):

- single signal: ≤ **0.5 points** (spread/total scale) or
  ≤ **0.02 probability**;
- total across signals for one row: ≤ **1.0 point**.

Declared adjustment formulas (v1 — exhaustive; no others exist):

1. **NFL team-form EPA tilt (totals/spreads research annotation).**
   `raw = 2.0 × ((off_epa_l4 − def_epa_allowed_l4) − league_mean_diff_l4)`
   points, from `team_epa_form` last-4 windows for both teams,
   differenced. Displayed as "EPA form tilt", capped per above.
2. **NFL role-change flag (props research annotation).** If
   `snap_share_delta ≥ +0.15` over the last 2 weeks AND the player's
   `target_share_l4` (receiving) or snap trend (rushing) confirms,
   `raw = +0.02` probability on the player's over research lean;
   mirror −0.02 for a confirmed role loss. Informational flag text
   is always shown with it.
3. **MLB contact-luck flag (totals/props research annotation).**
   If a lineup's aggregate `savant_xwoba_gap_batter ≥ +0.020`
   (min 5 qualified batters), flag "results below contact quality";
   no numeric adjustment in v1 — flag only.
4. **NBA/CBB impact-availability flag.** If a top-2 rotation player's
   browse-fed impact field (§5) is present and the player is a
   confirmed scratch in the injury layer (handled outside this
   spec), flag the game "impact player out — form fields stale for
   this team". No numeric adjustment in v1 — the injury layer owns
   availability; this layer only marks its own fields stale.

## 5. Browse-fed field protocol (DOCUMENTED-ONLY sources)

Impact metrics, KenPom's free table, StatMuse notes, Sharp Football
tendencies, NFL Savant views, Spotrac contract context, and
Basketball Monster notes enter ONLY through a human (owner or lane)
who: (1) reads the value on the source's own page, (2) records value,
source URL, and pull timestamp in the card's working notes,
(3) pastes it into the info pack with the field's §3 name and a
`BROWSE_FED` tag. No screen-scraping, no payload parsing, no
scheduled pulls for these sources. Staleness: impact metrics expire
7 days after pull; KenPom/Sharp/NFL Savant reads expire at the next
game for either team; StatMuse notes are single-game only.

## 6. What would change this spec

- Owner buys a KenPom subscription → KenPom moves from browse-fed to
  an admission review (its own battery, like Candidate A/B), not a
  silent fetcher.
- A DOCUMENTED-ONLY source publishes a real documented endpoint →
  admission note + fetcher PR referencing this spec.
- Any proposal to let a signal touch a model or a price → that is a
  new construction under preregistration + chronological OOS
  validation (the `free_factors.py` bar), entirely outside this spec.
