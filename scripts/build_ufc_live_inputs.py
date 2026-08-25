#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.ufc_history import load_history_from_urls
from sportsedge.ufc_source import (
    bout_rounds_from_detail,
    fighter_urls_from_bout,
    parse_event,
    parse_fighter_profile,
    upcoming_event_urls,
)


def _event_dt(text):
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text), fmt)
        except ValueError:
            pass
    raise ValueError("UFC_EVENT_DATE_INVALID")


def _age_from_dob(dob, event_date):
    if not dob:
        return None
    birth = None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            birth = datetime.strptime(str(dob), fmt)
            break
        except ValueError:
            pass
    if birth is None:
        return None
    event = _event_dt(event_date)
    return max(18.0, (event - birth).days / 365.2425)


def _override_is_current(path):
    if not path or not Path(path).exists():
        return False
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    event_day = _event_dt(cfg["event_date"]).date()
    today = datetime.now(timezone.utc).date()
    return abs((today - event_day).days) <= 1


def _from_override(path, history):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    event_day = _event_dt(cfg["event_date"]).date()
    today = datetime.now(timezone.utc).date()
    if abs((today - event_day).days) > 1:
        raise SystemExit(
            f"UFC_OVERRIDE_DATE_MISMATCH event_date={event_day.isoformat()} "
            f"utc_today={today.isoformat()}"
        )

    fighters = {}
    contexts = []
    for bout in cfg["bouts"]:
        late = str(bout.get("late_replacement") or "")
        for name in (bout["fighter_a"], bout["fighter_b"]):
            fighters[name] = history.snapshot_dict(
                name,
                cfg["event_date"],
                bout.get("weight_class", ""),
                late_replacement=(name == late),
            )
        contexts.append(
            {
                "fighter_a": bout["fighter_a"],
                "fighter_b": bout["fighter_b"],
                "rounds": int(bout.get("rounds", 3)),
                "title_fight": bool(bout.get("title_fight", False)),
                "short_notice_days": bout.get("short_notice_days"),
                "altitude_ft": 0.0,
            }
        )
    return cfg["event"], cfg["event_date"], fighters, contexts, "override"


def _from_ufcstats(history):
    urls = upcoming_event_urls()
    if not urls:
        return None
    bouts = parse_event(urls[0])
    if not bouts:
        return None

    fighters = {}
    contexts = []
    for bout in bouts:
        try:
            url_a, url_b = fighter_urls_from_bout(bout.bout_url)
            rounds = bout_rounds_from_detail(bout.bout_url)
            profile_a = parse_fighter_profile(url_a)
            profile_b = parse_fighter_profile(url_b)
        except Exception:
            continue

        for profile in (profile_a, profile_b):
            profile_override = {
                "age": _age_from_dob(profile.dob, bout.event_date),
                "height_in": profile.height_in,
                "reach_in": profile.reach_in,
                "stance": profile.stance,
            }
            fighters[profile.name] = history.snapshot_dict(
                profile.name,
                bout.event_date,
                bout.weight_class,
                profile_override=profile_override,
            )

        contexts.append(
            {
                "fighter_a": bout.fighter_a,
                "fighter_b": bout.fighter_b,
                "rounds": int(rounds),
                "title_fight": "title" in bout.weight_class.lower(),
                "short_notice_days": None,
                "altitude_ft": 0.0,
            }
        )

    if not contexts:
        return None
    return (
        bouts[0].event,
        bouts[0].event_date,
        fighters,
        contexts,
        "ufcstats_upcoming",
    )


def _validate_card(fighters, contexts):
    bouts = len(contexts)
    count = len(fighters)
    if bouts < 1:
        raise SystemExit("UFC_LIVE_INPUTS_INCOMPLETE fighters=0 bouts=0")
    expected = 2 * bouts
    if count != expected:
        raise SystemExit(
            f"UFC_LIVE_INPUTS_INCOMPLETE fighters={count} bouts={bouts} "
            f"expected_fighters={expected}"
        )
    for context in contexts:
        if int(context.get("rounds", 0)) not in {3, 5}:
            raise SystemExit(
                f"UFC_LIVE_INPUTS_INVALID_ROUNDS rounds={context.get('rounds')}"
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fighters", default="data/ufc/fighters_today.json")
    ap.add_argument("--contexts", default="data/ufc/contexts_today.json")
    ap.add_argument("--override", default="")
    ap.add_argument("--min-history-date", default="2010-01-01")
    args = ap.parse_args()

    history = load_history_from_urls(min_date=args.min_history_date)

    # A date-bounded explicit DWCS card must win over UFCStats' next ordinary UFC
    # event; otherwise Tuesday DWCS can accidentally be replaced by Saturday's card.
    if _override_is_current(args.override):
        result = _from_override(args.override, history)
    else:
        result = _from_ufcstats(history)

    if result is None:
        raise SystemExit("UFC_LIVE_INPUTS_UNAVAILABLE")

    event, event_date, fighters, contexts, card_source = result
    _validate_card(fighters, contexts)

    Path(args.fighters).parent.mkdir(parents=True, exist_ok=True)
    Path(args.contexts).parent.mkdir(parents=True, exist_ok=True)
    Path(args.fighters).write_text(
        json.dumps(
            {
                "event": event,
                "event_date": event_date,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "card_source": card_source,
                "history_source": "Greco1899/scrape_ufc_stats UFCStats mirror",
                "history_last_fight_date": history.last_fight_date,
                "fighters": list(fighters.values()),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    Path(args.contexts).write_text(
        json.dumps(contexts, indent=2, sort_keys=True), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "event": event,
                "event_date": event_date,
                "card_source": card_source,
                "history_last_fight_date": history.last_fight_date,
                "fighters": len(fighters),
                "bouts": len(contexts),
                "max_missingness": max(x["missingness"] for x in fighters.values()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
