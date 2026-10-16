"""Promotion-language screen shared by the composite guard and the status
allowlist builder (#2359). Research only.

A string "promotes" when, after splitting on non-alphanumerics, it carries a
promotion token that is not negated by the token IMMEDIATELY before it
(NO_PLAY is fine; NO_X_PLAY and NOT_A_PLAY are not). PASS counts only in a
gate context (GATE/CHECK/THRESHOLD/HARNESS/CRITERIA); EV counts when it is
POSITIVE/PLUS EV. Text is NFKC-normalised (full-width letters fold to ASCII)
and runs of two or more single-character tokens are joined (p.l.a.y -> PLAY).

The vocabulary below is OWNER-CURATABLE and pending owner review.
"""
from __future__ import annotations

import re
import unicodedata

VOCABULARY_STATE = "OWNER_CURATABLE_PENDING_REVIEW"

PROMOTION_TOKENS = frozenset({
    "PLAY", "PLAYS", "PLAYABLE", "BET", "BETS", "WAGER", "WAGERS", "PICK", "PICKS",
    "LOCK", "LOCKS", "BUY", "OFFICIAL", "OFFICIALPICK", "STAKE", "STAKED",
    "PROMOTED", "ACTIVATED", "ACTIONABLE", "LEAN", "LEANS", "LEANING", "ELIGIBLE",
    "ALLOWED", "EDGE", "EDGES", "RECOMMEND", "RECOMMENDED", "RECOMMENDATION",
    "APPROVED", "GREENLIGHT", "GREENLIT",
    # betting verbs
    "TAKE", "HAMMER", "SMASH", "FADE", "TAIL"})
NEGATORS = frozenset({"NO", "NOT", "NON"})
GATE_CONTEXT = frozenset({"GATE", "GATES", "CHECK", "CHECKS", "THRESHOLD", "HARNESS",
                          "CRITERIA", "CRITERION"})


def tokens(value: str) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)  # camelCase -> camel Case
    text = text.upper().replace("+", " PLUS ")
    raw = [t for t in re.split(r"[^A-Z0-9]+", text) if t]
    out: list[str] = []
    run: list[str] = []
    for t in raw + [""]:
        if len(t) == 1:
            run.append(t)
            continue
        if len(run) >= 2:
            out.append("".join(run))
        else:
            out.extend(run)
        run = []
        if t:
            out.append(t)
    return out


def promotes(value: str) -> bool:
    toks = tokens(value)
    gate = any(t in GATE_CONTEXT for t in toks)
    for i, t in enumerate(toks):
        prev = toks[i - 1] if i > 0 else None
        if t in PROMOTION_TOKENS and prev not in NEGATORS:
            return True
        if t == "PASS" and gate and prev not in NEGATORS:
            return True
        if t == "EV" and prev in {"POSITIVE", "PLUS"}:
            before = toks[i - 2] if i > 1 else None
            if before not in NEGATORS:
                return True
    return False
