# MLB V8 RUN IT schema syntax repair V2

Status: DRAFT replacement proposal; adoption requires independent review through the normal governed change process.

The JSON scan found that `docs/MLB_V8_RUN_IT_SCHEMA_2026-09-03.json` cannot be decoded: each of the `PAIRED` and `MISSED_OR_BLOCKED` conditionals is missing the closing brace for its `if` object. The first parse error is at line 174.

The dated replacement `MLB_V8_RUN_IT_SCHEMA_SYNTAX_V2_2026-10-20.json` adds those two braces, assigns a distinct schema identifier, and marks itself as a draft in schema metadata. All record fields, required fields, enums, numeric bounds, conditional requirements, and the September 3 blueprint and technical-spec version constants are preserved. It is not wired into a runtime reader or writer.

The original document is unchanged. Source SHA-256: `96850fb754b1a074676d5c8a9db7c671d7b8777d7c24267803835447f1824941`. Proposal SHA-256: `ccbb09fabe4c43587d5f6399cf26e7a57e8a47c9ef326469c7d1f0792b2303ac`. Coverage registration accounts for these proposed files under the same existing bundle as the original schema; it does not adopt the replacement or grant any authority.

Review must check Draft 2020-12 schema validity and both repaired conditionals, including rejection of paired evidence without its four required quote fields and missed evidence without a blocked reason. Syntax repair does not validate a model or a quoted market.
