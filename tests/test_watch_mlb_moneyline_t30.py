"""Regression for cron jitter starving frozen MLB T30 prospective decisions."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts.watch_mlb_moneyline_t30 import watch_t30


START = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, at):
        self.at = at
        self.sleeps = []

    def now(self):
        return self.at

    def sleep(self, seconds):
        assert 0 < seconds <= 60 * 25
        self.sleeps.append(seconds)
        self.at += timedelta(seconds=seconds)


def _roots(tmp_path, *, minutes_before=51, previous_decision=None):
    prediction = tmp_path / "predictions"
    decision = tmp_path / "decisions"
    quotes = tmp_path / "quotes"
    prediction.mkdir()
    decision.mkdir()
    quotes.mkdir()
    (prediction / "game_1.json").write_text(json.dumps({
        "game_pk": 1,
        "market": "MONEYLINE",
        "market_blind": True,
        "event_start_ts": START.isoformat(),
    }), encoding="utf-8")
    if previous_decision is not None:
        (decision / "game_1.json").write_text(json.dumps({
            "game_pk": 1, "status": previous_decision,
        }), encoding="utf-8")
    return prediction, quotes, decision, Clock(START - timedelta(minutes=minutes_before))


def _invoke(roots, *, quote_capture, decision_capture):
    predictions, quotes, decisions, fake_clock = roots
    return watch_t30(
        prediction_root=predictions,
        quote_root=quotes,
        decision_root=decisions,
        clock=fake_clock.now,
        sleeper=fake_clock.sleep,
        quote_capture=quote_capture,
        decision_capture=decision_capture,
    )


def test_t60_predict_then_t35_quote_freezes_within_window(tmp_path):
    roots = _roots(tmp_path)
    predictions, quotes, decisions, fake_clock = roots
    observations = []

    def capture_quote(**kwargs):
        observations.append(fake_clock.now())
        return {"status": "RETAINED"}

    def freeze(**kwargs):
        (decisions / "game_1.json").write_text(json.dumps({
            "game_pk": 1, "status": "PAPER_BET_FROZEN",
        }), encoding="utf-8")

    result = _invoke(roots, quote_capture=capture_quote, decision_capture=freeze)
    assert result["status"] == "T30_WATCH_COMPLETE"
    assert result["valid_frozen"] == [1]
    assert result["promotion_authority"] is False
    assert len(observations) == 1
    assert START - timedelta(minutes=36) <= observations[0] <= START - timedelta(minutes=30)


def test_transient_quote_failure_retries_before_deadline(tmp_path):
    roots = _roots(tmp_path, minutes_before=38)
    decisions = roots[2]
    fake_clock = roots[3]
    times = []

    def quote(**kwargs):
        times.append(fake_clock.now())
        if len(times) == 1:
            raise RuntimeError("temporary DraftKings timeout")

    def freeze(**kwargs):
        (decisions / "game_1.json").write_text(json.dumps({
            "game_pk": 1, "status": "PAPER_PASS_FROZEN",
        }), encoding="utf-8")

    result = _invoke(roots, quote_capture=quote, decision_capture=freeze)
    assert result["status"] == "T30_WATCH_COMPLETE"
    assert result["attempts"] == {1: 2}
    assert "timeout" in result["last_errors"][1]
    assert times[0] < times[1] < START - timedelta(minutes=30)


def test_no_quote_reaches_deadline_without_forced_bet(tmp_path):
    roots = _roots(tmp_path, minutes_before=32)

    def never_quote(**kwargs):
        raise RuntimeError("no book transport")

    result = _invoke(roots, quote_capture=never_quote, decision_capture=lambda **kwargs: None)
    assert result["status"] == "T30_WATCH_MISSED"
    assert result["valid_frozen"] == []
    assert result["missed"] == [1]
    assert not list(roots[2].glob("*.json"))


@pytest.mark.parametrize("previous", ["BLOCKED_MISSED_DECISION_FREEZE", "PAPER_BET_FROZEN"])
def test_never_rewrites_immutable_previous_decisions(tmp_path, previous):
    roots = _roots(tmp_path, previous_decision=previous)
    source = (roots[2] / "game_1.json").read_bytes()
    result = _invoke(
        roots,
        quote_capture=lambda **kwargs: pytest.fail("should not capture"),
        decision_capture=lambda **kwargs: pytest.fail("should not mutate"),
    )
    assert result["status"] == "NO_T30_WATCH_DUE"
    assert (roots[2] / "game_1.json").read_bytes() == source


def test_no_watch_when_prediction_already_past_target(tmp_path):
    roots = _roots(tmp_path, minutes_before=20)
    result = _invoke(
        roots,
        quote_capture=lambda **kwargs: pytest.fail("cannot backfill"),
        decision_capture=lambda **kwargs: pytest.fail("cannot backfill"),
    )
    assert result["status"] == "NO_T30_WATCH_DUE"
