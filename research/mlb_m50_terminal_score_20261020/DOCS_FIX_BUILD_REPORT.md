# Build report — docs-only tie-state companion to PR #2432

**Starting main:** `d722da64cc984c4466bfb83457cc99d36f66c6e5`  
**Branch:** `docs/mlb-m50-tie-state-disclosure-20261020`  
**Scope:** REVIEW-ONLY DOC; NO CODE, TEST, REGISTRY, GATE, RUNNER, FROZEN DOCUMENT, OR DEPLOYMENT CHANGE.

One new note: `research/mlb_m50_terminal_score_20261020/REGULATION_TIE_DISCREPANCY_REVIEW.md`, Git blob `0a1b504ea9409a55383929636b86721e0c2007eb`. The note documents the mathematical gap between a product of independent away/home terminal-score count marginals (with nonzero a=h mass) and a legal MLB completed **final score** (decided in extras after nine-inning tie), why naive renormalization/deletion is invalid, and what separate regulation→extras score-path evidence is required. It explicitly refuses to issue Rocky's verification verdict for PR #2432 or alter that branch's head.

**Tests/historical screen:** NOT APPLICABLE TO DOCS-ONLY BUILD. No code or historical evaluation was performed. All new mathematical claims still require independent code and score-path review; actual DK market identity/settlement, starting evidence, extra-inning state and historical market test remain unproven. This note alone cannot lift an engine hold.

**Rocky handoff:** Independently verify that the candidate PMF can contain tie mass, that a tied regulation score is not a valid ordinary terminal MLB result, and that correct score, margin, BTTS and team-parity events are not fully identified without a tie→extra-innings process. Confirm one-file docs-only diff, no code changes. Review after (or alongside) #2432's own independent verdict. Do not conflate this proposed disclosure with approval of its underlying construction.
