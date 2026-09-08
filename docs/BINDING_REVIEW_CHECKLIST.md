# Binding production review checklist

- [x] threshold domain explicit; contradictions fail
- [x] unknown markets cannot inherit a domain
- [x] quote normalization preserves source identity and does not synthesize it
- [x] validator executes before engine execution
- [x] failure is per-row BLOCKED
- [x] executable odds/book/retrieval time validated
- [x] event-instance identity required
- [x] team identity required on team-bound markets
- [x] probability market/entity/period/source-market mandatory
- [x] threshold mandatory on thresholded markets
- [x] multi-pitcher structural guard
- [ ] upstream adapters populate trusted event/game-number identity
- [ ] upstream adapters populate canonical team/player identities everywhere required
- [ ] all readouts emit explicit probability threshold/team identity where applicable
- [ ] F5 moneyline semantics split into unambiguous 2-way tie-push or 3-way market IDs
- [ ] FIRST_HOME_RUN N-way + NO_HOME_RUN devig approved
- [ ] full 38-market end-to-end evidence collected

No unchecked item may be converted to PASS by a model-layer default.
