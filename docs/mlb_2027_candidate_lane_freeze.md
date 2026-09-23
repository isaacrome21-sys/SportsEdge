# MLB 2027 candidate lane freeze

Status: FROZEN SPECIFICATION — implementation/validation pending

**NOT Model_P · NOT Truth Gate · NOT OFFICIAL**

## Scope

SportsEdge will pursue one MLB candidate lane for 2027:

**One coherent full-game run distribution → Moneyline, Run Line, Full-Game Total.**

These are not three separately fitted prediction models. A single pregame distribution over final away/home runs must generate probabilities for all three markets.

Props, NRFI/YRFI, inning markets, first-five markets, and other period markets are outside this lane and remain blocked until this lane passes its governed validation path.

## Market definitions

### Moneyline

Event: team wins the completed game under the sportsbook's applicable full-game settlement rules.

The model probability must be derived from the joint final-run distribution. Regulation ties must be resolved only by simulation/settlement semantics frozen separately; they may not be silently assigned to either team.

### Run line

Event: selected team covers the observed sportsbook run-line handicap.

For team run differential `D` and observed handicap `h`, settlement is derived from `D + h`:

- greater than 0 → win
- equal to 0 → push
- less than 0 → loss

Push probability must remain explicit whenever the observed line permits a push. It may not be discarded or redistributed.

### Full-game total

Event: combined final runs settle against the observed sportsbook total `T`.

For combined runs `R`:

- `R > T` → Over win
- `R = T` → push
- `R < T` → Under win

Push mass must remain explicit for integer totals and must not be redistributed between Over and Under.

## Binding rules

Market probabilities exist independently of sportsbook prices.

Prices are used only after model probabilities have been produced, for same-book comparison, fair-price/EV calculations, and prospective validation.

A market comparison is admissible only when the required same-book outcomes were actually observed and captured. Missing opposite-side prices remain **MISSING** and are never inferred.

## 2027 validation path

The audited historical candidate failed the frozen replay provenance requirements. Therefore this lane defaults to **prospective 2027 forward capture** unless another historical source independently passes the frozen audit.

No historical replay result may be manufactured from the failed source.

## Freeze boundary

This document freezes only:

1. the single candidate-lane architecture;
2. the three eligible market families;
3. their outcome definitions; and
4. the requirement that all probabilities originate from one coherent full-game run distribution.

PIT feature eligibility, leakage rules, RNG/simulation semantics, sportsbook quote binding, model fitting, calibration, and promotion criteria remain separate queue items and are not frozen by this step.
