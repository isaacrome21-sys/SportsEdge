"""One paper-bet ledger for every model and every market: simple/ledger.csv.

Every agent appends picks before the game and grades them after.
Paper only: no real wagers. Never edit or delete a logged row; corrections are new rows with note=CORRECTS:<id>.

  python ledger.py add  --agent claude --model nfl_ratings_v1 --sport NFL --market spread \
      --event "BUF@MIA 2026-11-01" --side BUF --line -3.5 --odds -110 --prob 0.55 \
      --captured_at 2026-11-01T07:00:00-05:00 --source "<capture file path or sha>"
  python ledger.py grade --id <id> --close_line -4.5 --close_odds -110 --result W   (W/L/P)
  python ledger.py summary
"""
import argparse
import csv
import datetime as dt
import hashlib
import os

from odds import american_to_decimal, american_to_prob, ev_per_unit

PATH = os.path.join(os.path.dirname(__file__), "ledger.csv")
COLS = ["id", "logged_at", "agent", "model", "sport", "market", "event", "side", "line", "odds",
        "prob", "ev", "captured_at", "source", "close_line", "close_odds", "clv_prob", "result",
        "profit", "graded_at", "note"]


def _rows():
    if not os.path.exists(PATH):
        return []
    with open(PATH, newline="") as f:
        return list(csv.DictReader(f))


def _write(rows):
    with open(PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def add(a):
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    key = f"{a.agent}|{a.model}|{a.sport}|{a.market}|{a.event}|{a.side}|{a.line}"
    rid = hashlib.sha1(key.encode()).hexdigest()[:10]
    rows = _rows()
    if any(r["id"] == rid for r in rows):
        print(f"skip duplicate {rid}")
        return
    ev = ev_per_unit(a.prob, a.odds) if a.prob is not None else ""
    rows.append(dict(id=rid, logged_at=now, agent=a.agent, model=a.model, sport=a.sport,
                     market=a.market, event=a.event, side=a.side, line=a.line, odds=a.odds,
                     prob=a.prob if a.prob is not None else "", ev=f"{ev:.4f}" if ev != "" else "",
                     captured_at=a.captured_at, source=a.source, note=a.note or ""))
    _write(rows)
    print(f"added {rid}")


def grade(a):
    rows = _rows()
    for r in rows:
        if r["id"] != a.id:
            continue
        if r["result"]:
            print(f"already graded {a.id}")
            return
        r["close_line"], r["close_odds"], r["result"] = a.close_line, a.close_odds, a.result
        if a.close_odds not in (None, ""):
            # CLV in implied-probability points: positive = we got a better price than the close
            # (only meaningful when close_line == line)
            if str(a.close_line) == str(r["line"]):
                r["clv_prob"] = f"{american_to_prob(a.close_odds) - american_to_prob(r['odds']):.4f}"
        r["profit"] = {"W": f"{american_to_decimal(r['odds']) - 1:.4f}", "L": "-1", "P": "0"}[a.result]
        r["graded_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        _write(rows)
        print(f"graded {a.id} {a.result}")
        return
    print(f"no such id {a.id}")


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
    g.add_argument("--close_line", default="")
    g.add_argument("--close_odds", type=float)
    g.add_argument("--result", choices=["W", "L", "P"], required=True)
    sub.add_parser("summary")
    args = p.parse_args()
    {"add": add, "grade": grade, "summary": summary}[args.cmd](args)


if __name__ == "__main__":
    main()
