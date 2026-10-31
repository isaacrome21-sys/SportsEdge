"""One paper-bet ledger for every model and every market: simple/ledger.csv.

Every agent appends picks before the game and grades them after.
Paper only: no real wagers. Never edit or delete a logged row; corrections are new rows with note=CORRECTS:<id>.

  python ledger.py add  --agent claude --model nfl_ratings_v1 --sport NFL --market spread \
      --event "BUF@MIA 2026-11-01" --side BUF --line -3.5 --odds -110 --prob 0.55 \
      --captured_at 2026-11-01T07:00:00-05:00 --source "<capture file path or sha>"
  python ledger.py grade --id <id> --result W --final_source "<box score URL or file sha>" \
      [--close_line -4.5 --close_odds -110 --close_source "<closing capture path or sha>"]
  python ledger.py summary

Fail-closed checks (from ChatGPT's 2026-10-31 14:57Z review on #2447):
- add: odds must be American (|odds| >= 100), prob strictly in (0, 1), captured_at an ISO time with a
  UTC offset that is not in the future, source non-blank. Any failure -> no row (exit code 2).
- add only appends a line to the file; existing lines are never rewritten.
- grade: --final_source is required. A close needs --close_odds AND --close_source; without them the
  close stays blank (no CLV). Only the blank grade fields of that one ungraded row are filled; the
  write is refused if any other byte of the ledger would change.

Concurrency (#2987): add and grade each hold an exclusive flock on ledger.csv.lock for the whole
read/check/write, writes go via temp file + fsync + os.replace, and grade reads the result back.
POSIX only (fcntl).

WRITER CONTRACT: every write to ledger.csv MUST go through this module (add/grade CLI or functions),
which takes the lock. Writes that bypass ledger.py (hand edits, `>>`, other scripts) are NOT supported
and can be lost: grade's final re-read narrows but does not close the window before os.replace
(ChatGPT review 6548764884). test_ledger_contract.py pins that limit.
"""
import argparse
import contextlib
import csv
import datetime as dt
import fcntl
import hashlib
import io
import math
import os
import sys

from odds import american_to_decimal, american_to_prob, ev_per_unit

PATH = os.path.join(os.path.dirname(__file__), "ledger.csv")
COLS = ["id", "logged_at", "agent", "model", "sport", "market", "event", "side", "line", "odds",
        "prob", "ev", "captured_at", "source", "close_line", "close_odds", "clv_prob", "result",
        "profit", "graded_at", "note", "close_source", "final_source"]
GRADE_COLS = ["close_line", "close_odds", "clv_prob", "result", "profit", "graded_at",
              "close_source", "final_source"]
FUTURE_SLACK = dt.timedelta(minutes=5)


class LedgerError(ValueError):
    pass


@contextlib.contextmanager
def _locked():
    """Exclusive advisory lock shared by every add/grade (blocks until free)."""
    with open(PATH + ".lock", "a") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _read_text():
    if not os.path.exists(PATH):
        return ""
    with open(PATH, newline="") as f:
        return f.read()


def _rows(text=None):
    text = _read_text() if text is None else text
    return list(csv.DictReader(io.StringIO(text))) if text else []


def _atomic_write(text):
    d = os.path.dirname(os.path.abspath(PATH))
    tmp = os.path.join(d, f".ledger.{os.getpid()}.tmp")
    with open(tmp, "w", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PATH)


def _render(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _ensure_header():
    """Create the file, or widen an old header to COLS (old rows get blank new columns)."""
    if not os.path.exists(PATH):
        with open(PATH, "w", newline="") as f:
            f.write(_render([]))
        return
    with open(PATH, newline="") as f:
        header = next(csv.reader(f), [])
    if header != COLS:
        if header != COLS[:len(header)]:
            raise LedgerError(f"unexpected ledger header {header}")
        _atomic_write(_render(_rows()))


def check_odds(odds):
    o = float(odds)
    if not math.isfinite(o) or abs(o) < 100:
        raise LedgerError(f"odds {odds!r} is not American (|odds| >= 100)")
    return o


def check_time(ts, name):
    try:
        t = dt.datetime.fromisoformat(str(ts))
    except ValueError:
        raise LedgerError(f"{name} {ts!r} is not an ISO time")
    if t.tzinfo is None:
        raise LedgerError(f"{name} {ts!r} has no UTC offset")
    if t > dt.datetime.now(dt.timezone.utc) + FUTURE_SLACK:
        raise LedgerError(f"{name} {ts!r} is in the future")
    return t


def check_text(v, name):
    if v is None or not str(v).strip():
        raise LedgerError(f"{name} is blank")
    return str(v).strip()


def add(a):
    """Append one pick. Raises LedgerError (no row written) on any failed check."""
    odds = check_odds(a.odds)
    prob = a.prob
    if prob is not None:
        prob = float(prob)
        if not (0.0 < prob < 1.0):
            raise LedgerError(f"prob {a.prob!r} not in (0, 1)")
    check_time(a.captured_at, "captured_at")
    for k in ("agent", "model", "sport", "market", "event", "side", "source"):
        check_text(getattr(a, k), k)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    key = f"{a.agent}|{a.model}|{a.sport}|{a.market}|{a.event}|{a.side}|{a.line}"
    rid = hashlib.sha1(key.encode()).hexdigest()[:10]
    with _locked():
        return _add_locked(a, odds, prob, now, rid)


def _add_locked(a, odds, prob, now, rid):
    _ensure_header()
    if any(r["id"] == rid for r in _rows()):
        print(f"skip duplicate {rid}")
        return None
    ev = f"{ev_per_unit(prob, odds):.4f}" if prob is not None else ""
    row = dict(id=rid, logged_at=now, agent=a.agent, model=a.model, sport=a.sport,
               market=a.market, event=a.event, side=a.side, line=a.line, odds=a.odds,
               prob=prob if prob is not None else "", ev=ev, captured_at=a.captured_at,
               source=a.source, note=getattr(a, "note", "") or "")
    line = _render([row]).split("\n", 1)[1]
    with open(PATH, "a", newline="") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    print(f"added {rid}")
    return rid


def grade(a):
    """Fill the grade fields of one ungraded row. Raises LedgerError on any failed check."""
    final_source = check_text(getattr(a, "final_source", None), "final_source")
    close_odds = getattr(a, "close_odds", None)
    close_source = getattr(a, "close_source", None) or ""
    if close_odds not in (None, ""):
        check_odds(close_odds)
        close_source = check_text(close_source, "close_source (required with close_odds)")
    elif str(getattr(a, "close_line", "") or "").strip() or close_source.strip():
        raise LedgerError("a close needs --close_odds (and --close_source); leave all close fields blank otherwise")
    if a.result not in ("W", "L", "P"):
        raise LedgerError(f"result {a.result!r} not W/L/P")
    with _locked():
        return _grade_locked(a, final_source, close_odds, close_source)


def _grade_locked(a, final_source, close_odds, close_source):
    _ensure_header()
    before = _read_text()
    rows = _rows(before)
    hits = [r for r in rows if r["id"] == a.id]
    if not hits:
        raise LedgerError(f"no such id {a.id}")
    if len(hits) > 1:
        raise LedgerError(f"id {a.id} appears {len(hits)} times")
    r = hits[0]
    if any((r.get(k) or "") for k in GRADE_COLS):
        print(f"already graded {a.id}")
        return None
    check_odds(r["odds"])
    old = dict(r)
    r["result"], r["final_source"] = a.result, final_source
    if close_odds not in (None, ""):
        r["close_line"], r["close_odds"], r["close_source"] = a.close_line or "", close_odds, close_source
        # CLV in implied-probability points: positive = we got a better price than the close
        # (only computed when the close is on the same line)
        if str(a.close_line or "") == str(r["line"]):
            r["clv_prob"] = f"{american_to_prob(close_odds) - american_to_prob(r['odds']):.4f}"
    r["profit"] = {"W": f"{american_to_decimal(r['odds']) - 1:.4f}", "L": "-1", "P": "0"}[a.result]
    r["graded_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    changed = {k for k in COLS if (old.get(k) or "") != (r.get(k) or "")}
    if not changed <= set(GRADE_COLS):
        raise LedgerError(f"refused: grade would change {sorted(changed - set(GRADE_COLS))}")
    after = _render(rows)
    # every other line must be byte-identical
    b_lines, a_lines = before.split("\n"), after.split("\n")
    diff = [i for i, (x, y) in enumerate(zip(b_lines, a_lines)) if x != y]
    if len(b_lines) != len(a_lines) or len(diff) != 1:
        raise LedgerError("refused: grade would rewrite more than the one graded row")
    # best-effort re-read: refuses if the file moved since our snapshot. NOT a guarantee against
    # writers that bypass the lock (a write between here and os.replace is lost) -- see WRITER CONTRACT.
    if _read_text() != before:
        raise LedgerError("refused: ledger changed during grade; nothing written, re-run grade")
    _atomic_write(after)
    if _read_text() != after:
        raise LedgerError("readback mismatch after grade write")
    print(f"graded {a.id} {a.result}")
    return a.id


def summary(_):
    rows = _rows()
    by = {}
    for r in rows:
        k = (r["model"], r["sport"], r["market"])
        s = by.setdefault(k, dict(n=0, graded=0, profit=0.0, clv=[], open=0))
        s["n"] += 1
        if r["result"]:
            s["graded"] += 1
            s["profit"] += float(r["profit"])
            if r["clv_prob"]:
                s["clv"].append(float(r["clv_prob"]))
        else:
            s["open"] += 1
    print("model | sport | market | logged | graded | open | ROI | avg CLV (prob pts) | CLV n")
    for (m, sp, mk), s in sorted(by.items()):
        roi = s["profit"] / s["graded"] if s["graded"] else float("nan")
        clv = sum(s["clv"]) / len(s["clv"]) if s["clv"] else float("nan")
        print(f"{m} | {sp} | {mk} | {s['n']} | {s['graded']} | {s['open']} | {roi:+.3f} | {clv:+.4f} | {len(s['clv'])}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    for k in ("agent", "model", "sport", "market", "event", "side", "captured_at", "source"):
        a.add_argument(f"--{k}", required=True)
    a.add_argument("--line", default="")
    a.add_argument("--odds", type=float, required=True)
    a.add_argument("--prob", type=float)
    a.add_argument("--note")
    g = sub.add_parser("grade")
    g.add_argument("--id", required=True)
    g.add_argument("--result", choices=["W", "L", "P"], required=True)
    g.add_argument("--final_source", required=True)
    g.add_argument("--close_line", default="")
    g.add_argument("--close_odds", type=float)
    g.add_argument("--close_source", default="")
    sub.add_parser("summary")
    args = p.parse_args()
    try:
        {"add": add, "grade": grade, "summary": summary}[args.cmd](args)
    except LedgerError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
