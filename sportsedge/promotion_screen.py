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
    # betting verbs (TAKE/FADE/TAIL dropped: common in legitimate codes/text)
    "HAMMER", "SMASH"})
NEGATORS = frozenset({"NO", "NOT", "NON"})
GATE_CONTEXT = frozenset({"GATE", "GATES", "CHECK", "CHECKS", "THRESHOLD", "HARNESS",
                          "CRITERIA", "CRITERION", "CLEARANCE", "METRICS"})


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


# Refusal-shaped codes never mean promotion (EDGE_BELOW_FROZEN_FLOOR, NO_EDGE).
REFUSAL_MARKERS = frozenset({
    "BLOCKED", "BLOCK", "NO", "NOT", "NON", "MISSING", "BELOW", "DUPLICATE", "ERROR",
    "ERRORS", "FAIL", "FAILED", "FAILS", "FAILURE", "DISABLED", "REFUSE", "REFUSED",
    "REFUSAL", "INSUFFICIENT", "UNVERIFIED", "WATCH", "STALE", "INVALID", "UNAVAILABLE",
    "MISMATCH", "REQUIRED", "NEEDS", "WITHOUT", "UNKNOWN", "REJECTED", "VOID", "ABSENT",
    "EXCEEDED", "FORBIDDEN", "CANNOT", "INCOMPLETE", "PARTIAL", "UNRESOLVED", "BROKEN",
    "UNBUILT", "NONFINITE", "EMPTY", "NONZERO", "WAITING", "PENDING"})
# Domain phrases whose words are not promotion (baseball/football vocabulary).
DOMAIN_PAIRS = frozenset({
    ("HITS", "ALLOWED"), ("RUNS", "ALLOWED"), ("WALKS", "ALLOWED"), ("HR", "ALLOWED"),
    ("HOMERS", "ALLOWED"), ("YARDS", "ALLOWED"), ("POINTS", "ALLOWED"), ("SACKS", "ALLOWED"),
    ("GOALS", "ALLOWED"), ("SCORING", "PLAY"), ("SCORING", "PLAYS"), ("PLAY", "ID"),
    ("PLAY", "BY"), ("BY", "PLAY"), ("PLAY", "TYPE"), ("PLAYS", "ID"), ("LONGEST", "PLAY"),
    ("PLAY", "CLOCK"), ("OFFICIAL", "DATE"), ("OFFICIAL", "SCORER"), ("OFFICIAL", "STATS"),
    ("EDGE", "RUSHER"), ("EDGE", "FLOOR"), ("EDGE", "FROM"),
    # play-by-play nouns
    ("DRIVE", "PLAY"), ("PLAY", "EVENT"), ("PLAY", "PATH"), ("PLAY", "SCORE"),
    ("PLAY", "SCORING"), ("LAST", "PLAY"), ("LONGEST", "PLAYS"), ("TEAM", "PLAY"),
    ("PLAY", "RUNNER"),
    # OFFICIAL as a data source, not authority
    ("OFFICIAL", "NFL"), ("OFFICIAL", "FACTS"), ("OFFICIAL", "FACT"), ("OFFICIAL", "WEB"),
    ("OFFICIAL", "API"), ("NGS", "OFFICIAL"), ("OFFICIAL", "GAME"), ("OFFICIAL", "MARKET"),
    ("OFFICIAL", "COUNT"), ("OFFICIAL", "F5"), ("OFFICIAL", "TWO"), ("OFFICIAL", "PRE"),
    ("NEAR", "OFFICIAL"), ("OFFICIAL", "WARNING"), ("OFFICIAL", "INJURY"),
    # ALLOWED / ELIGIBLE / BET as data or accounting vocabulary
    ("PBP", "ALLOWED"), ("EVENT", "ALLOWED"), ("ALLOWED", "FIELDS"),
    ("ELIGIBLE", "DECISION"), ("SETTLEMENT", "ELIGIBLE"), ("GRADED", "BET"),
    ("CLV", "OFFICIAL"), ("BINDING", "ALLOWED"), ("REVIEW", "ALLOWED"),
    # t211e: football PASS (the play type) and play-by-play PLAY nouns
    *((("PASS", w) for w in ("ATTEMPTS", "TDS", "TD", "YARDS", "YDS", "RUSH", "COMPLETION",
                               "COMPLETIONS", "INTERCEPTIONS", "PLUS", "ATTRIBUTION",
                               "CANNOT", "DEFENSIVE"))),
    *(((w, "PASS") for w in ("PLAYER", "TEAM", "QB", "RECEIVING", "HAVE", "OT"))),
    *((("PLAY", w) for w in ("DISTANCE", "DOWN", "IDS", "INDEX", "MULTIPLE", "POINTS",
                               "POSSESSION", "QUARTER", "YARDLINE", "COUNT", "DEFENSIVE",
                               "RAW", "SPECIAL", "TEAM", "OPPORTUNITY", "HAS"))),
    *(((w, "PLAY") for w in ("BASE", "OT", "OFFENSIVE", "TACKLE", "V2K", "SOURCE"))),
    ("PITCH", "PASSED"),
    # freeze/preregistration locks; edge-floor refusals and the CFB edge model name
    ("TUNING", "LOCK"), ("PREREGISTRATION", "LOCK"), ("OPENER", "LOCK"),
    ("EDGE", "BELOW"), ("EDGE", "FLOORS"), ("EDGE", "NONFINITE"), ("CFB", "EDGE"),
    ("EVALUATION", "ALLOWED"),  # t211e owner: FIRST_EVALUATION_ALLOWED is a scheduling gate
    })


def norm_code(value) -> str:
    """Canonical code form for exact set membership (NFKC, joined letters)."""
    return "_".join(tokens(value))


# Promotion RESULTS (t211e): promotion unless the immediately preceding token negates.
PROMOTION_RESULTS = frozenset({"PASS", "PASSED", "QUALIFIED", "OK", "PROMOTION"})
_RESULT_SEQUENCES = (("READY", "FOR", "AUTHORITY"),)


def promotion_meaning(code) -> bool:
    """True only when a code's MEANING is promotion (builder exclusion rule).

    A promotion token/result counts unless the token IMMEDIATELY before it is
    a negation/refusal-type word (NO, NOT, MISSING, BELOW, ...). Refusal words
    elsewhere grant no immunity. Domain phrases (HITS_ALLOWED, SCORING_PLAY,
    EDGE_FLOOR ...) are neutral."""
    toks = tokens(code)
    drop = set()
    for i in range(len(toks) - 1):
        if (toks[i], toks[i + 1]) in DOMAIN_PAIRS:
            drop.update({i, i + 1})
    for i, t in enumerate(toks):
        if i in drop:
            continue
        prev = toks[i - 1] if i > 0 else None
        if prev in REFUSAL_MARKERS:
            continue
        if t in PROMOTION_TOKENS or t in PROMOTION_RESULTS:
            return True
        if t == "EV" and prev in {"POSITIVE", "PLUS"}:
            before = toks[i - 2] if i > 1 else None
            if before not in REFUSAL_MARKERS:
                return True
    for seq in _RESULT_SEQUENCES:
        n = len(seq)
        for i in range(len(toks) - n + 1):
            if tuple(toks[i:i + n]) == seq and (i == 0 or toks[i - 1] not in REFUSAL_MARKERS):
                return True
    return False
