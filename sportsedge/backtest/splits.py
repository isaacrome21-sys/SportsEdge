"""Chronological train/test splitting with strict point-in-time discipline.

No future data may ever enter a training window: every fixture in a train
set kicks off strictly before every fixture in its test set. Fixtures that
share a kickoff time are never split across the train/test boundary.

Fixtures are dicts with at least:
    fixture_id : str   unique id
    kickoff    : ISO-8601 timestamp, timezone-aware (the point in time the
                 game starts; outcomes become known only after this)
    as_of      : ISO-8601 timestamp, timezone-aware (when the prediction is
                 made; must be <= kickoff)

Research only.
"""
from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timezone

Split = namedtuple("Split", ["train", "test"])


class SplitError(ValueError):
    pass


def _clock(value, name):
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise SplitError(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise SplitError(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _checked(fixtures):
    """Validate fixture shape; return list of (kickoff, fixture)."""
    if not isinstance(fixtures, list) or not fixtures:
        raise SplitError("BACKTEST_FIXTURES_EMPTY")
    checked = []
    seen = set()
    for i, fx in enumerate(fixtures):
        if not isinstance(fx, dict):
            raise SplitError("BACKTEST_FIXTURE_NOT_OBJECT")
        fid = str(fx.get("fixture_id") or "").strip()
        if not fid:
            raise SplitError("BACKTEST_FIXTURE_ID_REQUIRED")
        if fid in seen:
            raise SplitError("BACKTEST_FIXTURE_ID_DUPLICATE:" + fid)
        seen.add(fid)
        kickoff = _clock(fx.get("kickoff"), "BACKTEST_KICKOFF")
        as_of = _clock(fx.get("as_of"), "BACKTEST_AS_OF")
        if as_of > kickoff:
            raise SplitError("BACKTEST_AS_OF_AFTER_KICKOFF:" + fid)
        checked.append((kickoff, fx))
    for i in range(1, len(checked)):
        if checked[i][0] < checked[i - 1][0]:
            raise SplitError(
                "BACKTEST_CHRONOLOGY_UNSORTED:"
                + str(checked[i - 1][1].get("fixture_id"))
                + ">"
                + str(checked[i][1].get("fixture_id"))
            )
    return checked


def _blocks(checked):
    """Group fixtures sharing a kickoff so boundaries never split them."""
    blocks = []
    for kickoff, fx in checked:
        if blocks and blocks[-1][0] == kickoff:
            blocks[-1][1].append(fx)
        else:
            blocks.append((kickoff, [fx]))
    return blocks


def fixed_split(fixtures, cutoff):
    """Single split: train = kickoff < cutoff, test = kickoff >= cutoff."""
    checked = _checked(fixtures)
    cut = _clock(cutoff, "BACKTEST_CUTOFF")
    train = [fx for k, fx in checked if k < cut]
    test = [fx for k, fx in checked if k >= cut]
    if not train:
        raise SplitError("BACKTEST_SPLIT_TRAIN_EMPTY")
    if not test:
        raise SplitError("BACKTEST_SPLIT_TEST_EMPTY")
    return Split(train=train, test=test)


def walk_forward_splits(fixtures, *, min_train, test_size, step=1,
                        embargo_days=0):
    """Expanding-window walk-forward splits over kickoff-ordered fixtures.

    The train window grows from the oldest fixtures; each test window is the
    next ``test_size`` fixtures. ``step`` advances the window by that many
    kickoff blocks (default 1). ``embargo_days`` drops any split whose test
    window starts less than that many days after the train window ends.

    Yields Split(train, test) with the invariant:
        max(train kickoff) < min(test kickoff)   (minus embargo)
    """
    for name, value in (("min_train", min_train), ("test_size", test_size),
                        ("step", step)):
        if not isinstance(value, int) or value < 1:
            raise SplitError("BACKTEST_SPLIT_PARAM_INVALID:" + name)
    if not isinstance(embargo_days, (int, float)) or embargo_days < 0:
        raise SplitError("BACKTEST_SPLIT_PARAM_INVALID:embargo_days")

    checked = _checked(fixtures)
    blocks = _blocks(checked)
    n_blocks = len(blocks)
    idx = 0
    while True:
        # Expanding train window: everything before the test window, with at
        # least min_train fixtures. Test window: following blocks until
        # test_size fixtures.
        train_blocks = 0
        train_n = 0
        while idx + train_blocks < n_blocks and train_n < min_train:
            train_n += len(blocks[idx + train_blocks][1])
            train_blocks += 1
        if train_n < min_train:
            return
        test_blocks = 0
        test_n = 0
        while (idx + train_blocks + test_blocks < n_blocks
               and test_n < test_size):
            test_n += len(blocks[idx + train_blocks + test_blocks][1])
            test_blocks += 1
        if test_n < test_size:
            return
        train = [fx for _, grp in blocks[:idx + train_blocks] for fx in grp]
        test = [fx for _, grp in
                blocks[idx + train_blocks:idx + train_blocks + test_blocks]
                for fx in grp]
        train_max = max(_clock(fx["kickoff"], "BACKTEST_KICKOFF") for fx in train)
        test_min = min(_clock(fx["kickoff"], "BACKTEST_KICKOFF") for fx in test)
        if (test_min - train_max).total_seconds() >= embargo_days * 86400:
            # Invariant: no train fixture kicks off at/after any test fixture.
            assert train_max < test_min
            yield Split(train=train, test=test)
        idx += step
        if idx + train_blocks >= n_blocks:
            return
