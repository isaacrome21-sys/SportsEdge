"""Paired-quote timestamp enforcement for the no-vig comparison.

A same-book no-vig pair is only contemporaneous evidence when BOTH quotes
carry parseable capture timestamps within 120 seconds of each other. A
counterpart quote with a missing/unparseable timestamp must refuse the
pair (never "assumed same screenshot"), and captures more than 120
seconds apart are mismatched even when both timestamps are present.
"""
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
engine_spec = importlib.util.spec_from_file_location(
    "free_paired_ts", ROOT / "artifacts" / "free_models.py")
engine = importlib.util.module_from_spec(engine_spec)
engine_spec.loader.exec_module(engine)
NOW = datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T01:15:00Z"
T0 = "2026-10-11T12:59:30Z"


_OMIT = object()


def row(side="UNDER", odds=-105, captured=T0, **extra):
    base = {"away": "Buffalo Bills", "home": "Los Angeles Rams",
            "market": "TOTAL", "side": side, "odds": odds,
            "kickoff": KICKOFF, "line": 54.5}
    if captured is not _OMIT:
        base["quote_captured_at"] = captured
    base.update(extra)
    return base


def card(rows):
    return engine.run({"sport": "NFL", "lines": rows}, now=NOW,
                      auto_context=False)


def statuses(c):
    return [r["independent_projection"]["paired_market_status"]
            for r in c["evaluated_rows"]]


def test_missing_counterpart_timestamp_refuses_pair():
    c = card([row(), row(side="OVER", odds=-115, captured=None)])
    s = statuses(c)
    # The row whose counterpart lacks a timestamp is refused by name;
    # neither side may emit a no-vig pair.
    assert s[0] == "COUNTERPART_QUOTE_TIMESTAMP_MISSING"
    assert "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH" not in s
    assert all("market_no_vig_p" not in r["independent_projection"]
               for r in c["evaluated_rows"])


def test_absent_counterpart_timestamp_key_refuses_pair():
    c = card([row(), row(side="OVER", odds=-115, captured=_OMIT)])
    assert statuses(c)[0] == "COUNTERPART_QUOTE_TIMESTAMP_MISSING"


def test_unparseable_counterpart_timestamp_refuses_pair():
    c = card([row(), row(side="OVER", odds=-115, captured="not-a-time")])
    assert statuses(c)[0] == "COUNTERPART_QUOTE_TIMESTAMP_MISSING"


def test_pair_119_seconds_apart_is_accepted():
    # 12:59:30 vs 12:57:31 -> 119s apart, both fresh at NOW.
    c = card([row(), row(side="OVER", odds=-115,
                         captured="2026-10-11T12:57:31Z")])
    assert statuses(c) == ["EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"] * 2


def test_pair_121_seconds_apart_is_refused():
    # 12:59:30 vs 12:57:29 -> 121s apart.
    c = card([row(), row(side="OVER", odds=-115,
                         captured="2026-10-11T12:57:29Z")])
    assert statuses(c) == ["MISMATCHED_QUOTE_TIMESTAMPS"] * 2
    assert all("market_no_vig_p" not in r["independent_projection"]
               for r in c["evaluated_rows"])


def test_pair_with_equal_timestamps_is_accepted():
    c = card([row(), row(side="OVER", odds=-115, captured=T0)])
    assert statuses(c) == ["EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"] * 2
