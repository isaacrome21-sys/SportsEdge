# AMENDMENT 2 — NBA Team Totals Forward Test V1 (2026-10-22)

**Amends by reference** the FROZEN prereg
`PREREG_NBA_TEAM_TOTALS_FORWARD_V1_DRAFT.md`
(sha256 `0274e8cd248ed56a43c445c3d23e96e04eb218f4abcafb2ebe4041448ef55504`)
and `AMENDMENT_1.md`
(sha256 `7f5e55ef946d699069502b5ec3448e0cb66cb373733202bb437589e23f56e8d6`).
Neither text is edited.

**Ruling:** Grok, under the owner's delegation (t234u), 2026-10-22.
**Effective:** before the first counted slate (none has counted; the
evaluator is not pinned). **Adds no codes.**

## Narrowing of AMENDMENT_1's post-tip clarification

AMENDMENT_1 said a capture holding any quote at or after tipoff, if last,
gives `CLOSE_NOT_PRETIP`. That is narrowed to **straddling** captures only,
consistent with frozen §7 ("the last capture before tipoff"):

- The close is the last capture with **at least one pre-tip quote**.
- If that capture also holds a quote at or after tipoff (it straddles tip),
  the result is `CLOSE_NOT_PRETIP`; an earlier capture never rescues it.
- Captures whose quotes are **all** at or after tipoff are ignored.
- No capture with a pre-tip quote gives `CLOSE_NOT_PRETIP`.
