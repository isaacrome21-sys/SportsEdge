# NFL G2 handoff package for Muse (prep only, 2026-10-13)

Status: HANDOFF ARTIFACT. Not a freeze, not an amendment, not an evaluation. Attempt 2 was NOT executed. No sealed holdout, real development fold, or source download was touched. Nothing is validated.
Author: Grok, cross-lane prep under owner directive t113u. Muse owns the NFL files. This doc does not edit any Muse file or branch.
Pinned main: `655715907d101052bfc7cb3357f1442db82d8d8b`

## 1. Precise blocker: Amendment 2 is not in the repo
- No "G2 Amendment 2" document, config, or branch exists on origin. Checked with `git grep -i "amendment 2"`, by listing branches/refs for g2/amend, and by searching open PRs.
- The only G2 governance object is the Attempt-1 prereg, which is on branch `records/g2-attempt1-preregistration-20261013` @ `c0ecac14b1f23cff78830570fd637e537047898a` and is **NOT on main**:
  - `config/research/nfl_score_counts_g2_prereg_v1.json`, blob `07e140290e8807cd5580ab90da6b08ded1aaf55a`, sha256 `a20a32ee4a8b6b71fef32cd59c001bc277d386f21d5964df93fa01967c7aeaeb`
- The prereg points to `config/research/nfl_score_counts_g2_source_contract_v1.json`. **That file doesn't exist anywhere on origin.**
- **There is no G2 implementation on main.** The banded-FG opportunity × allocation × conversion leg, the per-quarter period components, and the G2 projection allowlist are all absent. So the G2 pipeline itself can't be verified on synthetic data yet. Only the heritage components that G2 carries verbatim can be checked (section 3).
- **Muse needs to supply:** the Amendment 2 text, the G2 source contract, and the G2 code. Then this package can be re-hashed and the synthetic battery extended.

## 2. Hashes of the carried-verbatim heritage code/config (main 65571590)
| File | sha256 |
|---|---|
| sportsedge/sports/nfl/score_counts_features.py | 501df074687d80286e4692064042f7367a8e389e240d3e6c6f535aa8182f8c9d |
| sportsedge/sports/nfl/score_counts_g1.py | 1aeade9eba14a3eec2aad08bc5441c958c12ae982679082dc76a7fe4fab191e8 |
| sportsedge/sports/nfl/score_counts_source_projection.py | b9176c35eb8cd53f48331d1a5d2530e11196937bac35f8e17ddcb68bbeb3f8fe |
| sportsedge/sports/nfl/score_counts_source_manifest.py | 0c0ff278439c5cac432f9d1534e8da46aa099a25f908accabbc06f0bfec54502 |
| sportsedge/sports/nfl/score_counts_artifact.py | 011cc750c123304d6332678a4d127f994960576ae6ae145e16bd4530df5b8684 |
| scripts/run_nfl_score_counts_attempt.py (hashed only, NOT run) | 6de194daedbe04fd016920b295add3efbff582ec904266366ccb20f637b6bee6 |
| scripts/preflight_nfl_score_counts_sources.py (hashed only, NOT run) | a958da861fa5dfbb005e1e5358ddcf06c1c9a4c33a3de015445314c56e5e39dc |
| config/research/nfl_score_counts_g1_source_contract_v1.json | 0ed8d0c0f2658cf3d1fecc875badd35826b307031ad748d74011876d9b72339f |

## 3. Synthetic-only verification
- Ran `pytest tests/test_nfl_score_counts_g1.py tests/test_nfl_score_counts_features.py tests/test_nfl_score_counts_artifact.py` on main 65571590.
- Result: **48 passed**. These tests use in-memory synthetic fixtures and make no network calls; no source objects were downloaded.
- What this shows: the heritage code is intact. It is NOT evidence about G2, and it is NOT validation.

## 4. Checklist before any Attempt 2 (owner/Muse)
- [ ] Amendment 2 doc committed and registered in `config/reconciliation_coverage_v1.json` (ChatGPT).
- [ ] G2 prereg + source contract on main.
- [ ] G2 code frozen. Re-hash it here, then run a synthetic battery for the FG bands, period components, and allowlist token screen.
- [ ] Owner authorizes Attempt 2 explicitly. **Not authorized now.** Attempt budget is max 3, and renaming does not reset it.

## 5. Other Muse-lane handoff checklists (status only)
- **Participation/QB identity (CFB):** #2140/#2145/#2146 taxonomy (TEAM_NOT_IN_INJURY_FEED) is still a draft. #2192 Form2 is a draft (see integration packet). Still blocked on the owner decision about alternative QB-identity evidence (§8/§10).
- **NBA:** quarter calibration is PASS_RESEARCH, labeled as a refit on an already-examined holdout. The OT fix FAILED (simulated 3.23% vs 4.46% actual). The 2026-27 preregs (margin-dispersion 685f0512; pregame player layer a55c0084) wait for forward data. **a55c0084 needs registration.**
- **CBB:** 2025-26 is PASS_RESEARCH on an examined window. The shrunk-HCA prereg is registered (40fa4f4) and waits for the 2026-27 forward season.
- **CFB model:** directory and currency fixes are on main (#2182/#2184). The scope-amendment and §8/§10 owner decisions are still open.

New file: flag for ChatGPT registration.
