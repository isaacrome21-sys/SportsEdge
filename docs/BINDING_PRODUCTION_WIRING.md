# Production wiring

Call binding validation in orchestration immediately after canonical quote normalization/admission and before engine invocation. This guarantees every priced row either reaches a model path or produces an explicit `BLOCKED` record. Do not defer the check to final card assembly.
