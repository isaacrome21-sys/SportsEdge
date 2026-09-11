import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tr = _load("ev_tracker_t", "scripts/ev_tracker.py")
ev = tr.ev  # same module instance, so EVError classes match
POLICY = ev.load_policy(ROOT / "config/ev_tracker_policy_v1.json")
NOW = datetime(2026, 9, 13, 16, 0, tzinfo=timezone.utc)
KICK = "2026-09-13T17:00:00Z"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def spread_book(key, home_pt, home_dec, away_dec, age_s=30, fetched=NOW):
    return {"key": key, "markets": [{"key": "spreads", "last_update": iso(fetched - timedelta(seconds=age_s)),
            "outcomes": [{"name": "Kansas City Chiefs", "price": home_dec, "point": home_pt},
                         {"name": "Denver Broncos", "price": away_dec, "point": -home_pt}]}]}


def play(**over):
    p = {"play_id": "issue-1", "source": "Odds Assist Pinnacle +EV", "sport_key": "americanfootball_nfl",
         "event_id": "e1", "commence_time": KICK, "away_team": "Denver Broncos", "home_team": "Kansas City Chiefs",
         "market": "spreads", "pick": "Denver Broncos", "line": 3.5, "book": "fanduel",
         "price_american": 102, "price_decimal": 2.02, "stake_units": 0.25, "logged_at": iso(NOW),
         "slate_date": "2026-09-13", "teams_entered_swapped": False}
    p.update(over)
    return p


class Odds(unittest.TestCase):
    def test_conversions(self):
        self.assertAlmostEqual(ev.american_to_decimal(-110), 1.909091, places=5)
        self.assertEqual(ev.american_to_decimal(150), 2.5)
        self.assertEqual(ev.decimal_to_american(2.5), 150)
        self.assertEqual(ev.decimal_to_american(1.5), -200)
        with self.assertRaises(ev.EVError):
            ev.american_to_decimal(50)

    def test_devig_methods_sum_to_one(self):
        imp = [1 / 2.5, 1 / 1.55]
        for fn in (ev.devig_power, ev.devig_multiplicative, ev.devig_shin):
            self.assertAlmostEqual(sum(fn(imp)), 1.0, places=9)
        self.assertGreater(ev.devig_power(imp)[1], ev.devig_multiplicative(imp)[1])

    def test_longshot_sensitivity_blocks(self):
        with self.assertRaises(ev.EVError) as ctx:
            ev.devig([10.0, 1.05])
        self.assertEqual(ctx.exception.code, "DEVIG_METHOD_SENSITIVITY")
        ev.devig([5.5, 1.21])  # low-vig longshot: methods agree

    def test_clv(self):
        self.assertAlmostEqual(ev.clv_pp(2.02, 0.5), 100 * (0.5 - 1 / 2.02))


class Matching(unittest.TestCase):
    EVENTS = [
        {"id": "e1", "commence_time": KICK, "away_team": "Denver Broncos", "home_team": "Kansas City Chiefs"},
        {"id": "e2", "commence_time": "2026-09-13T20:25:00Z", "away_team": "Los Angeles Rams", "home_team": "Seattle Seahawks"},
        {"id": "e3", "commence_time": "2026-09-13T20:25:00Z", "away_team": "Los Angeles Chargers", "home_team": "Seattle Seahawks"},
        {"id": "e0", "commence_time": "2026-09-13T15:00:00Z", "away_team": "Buffalo Bills", "home_team": "Miami Dolphins"},
    ]

    def test_nickname_and_date(self):
        m = ev.match_event(self.EVENTS, "Broncos", "chiefs", NOW, "2026-09-13")
        self.assertEqual(m["event"]["id"], "e1")
        self.assertFalse(m["swapped"])

    def test_swapped(self):
        self.assertTrue(ev.match_event(self.EVENTS, "Chiefs", "Broncos", NOW)["swapped"])

    def test_started_game_not_matched(self):
        with self.assertRaises(ev.EVError):
            ev.match_event(self.EVENTS, "Bills", "Dolphins", NOW)

    def test_ambiguous(self):
        with self.assertRaises(ev.EVError) as ctx:
            ev.match_event(self.EVENTS, "Los Angeles", "Seahawks", NOW)
        self.assertEqual(ctx.exception.code, "EVENT_AMBIGUOUS")


class SharpFair(unittest.TestCase):
    def fair(self, books, p=None):
        return ev.sharp_fair_for_play({"bookmakers": books}, p or play(), POLICY, NOW)

    def test_spread_graded(self):
        r = self.fair([spread_book("pinnacle", -3.5, 1.95, 1.95), spread_book("novig", -3.5, 1.97, 1.97)])
        self.assertEqual(r["status"], "OK")
        self.assertAlmostEqual(r["fair_p"], 0.5)

    def test_line_moved(self):
        r = self.fair([spread_book("pinnacle", -3.0, 1.95, 1.95)])
        self.assertEqual(r["reason"], "LINE_MOVED_AT_SHARP_BOOKS")

    def test_leave_one_out(self):
        r = self.fair([spread_book("pinnacle", -3.5, 1.95, 1.95), spread_book("novig", -3.5, 1.80, 2.20)],
                      play(book="novig"))
        self.assertEqual(sorted(r["books"]), ["pinnacle"])

    def test_stale_excluded(self):
        r = self.fair([spread_book("pinnacle", -3.5, 1.95, 1.95, age_s=900), spread_book("novig", -3.5, 1.95, 1.95)])
        self.assertEqual(r["reason"], "NO_SHARP_REFERENCE")

    def test_disagreement(self):
        r = self.fair([spread_book("pinnacle", -3.5, 1.95, 1.95), spread_book("novig", -3.5, 2.10, 1.83)])
        self.assertEqual(r["reason"], "SHARP_DISAGREEMENT")

    def test_totals_and_moneyline(self):
        tot = {"key": "pinnacle", "markets": [{"key": "totals", "last_update": iso(NOW),
               "outcomes": [{"name": "Over", "price": 1.9, "point": 47.5}, {"name": "Under", "price": 1.95, "point": 47.5}]}]}
        r = self.fair([tot], play(market="totals", pick="Under", line=47.5))
        self.assertEqual(r["status"], "OK")
        ml = {"key": "pinnacle", "markets": [{"key": "h2h", "last_update": iso(NOW),
              "outcomes": [{"name": "Kansas City Chiefs", "price": 1.6}, {"name": "Denver Broncos", "price": 2.5}]}]}
        r = self.fair([ml], play(market="h2h", line=None))
        self.assertLess(r["fair_p"], 0.4)


class Staging(unittest.TestCase):
    def rows(self, n, clv, slates=40):
        return [{"slate_date": f"d{i % slates}", "clv_pp": clv + (0.3 if i % 2 else -0.3)} for i in range(n)]

    def test_starts_micro(self):
        st = ev.source_stage([], POLICY["staging"])
        self.assertEqual((st["stage"], st["units"]), ("MICRO", 0.25))

    def test_demotes_on_negative_clv(self):
        self.assertEqual(ev.source_stage(self.rows(50, -0.5), POLICY["staging"])["stage"], "PAPER")
        self.assertEqual(ev.source_stage(self.rows(49, -0.5), POLICY["staging"])["stage"], "MICRO")

    def test_promotes_with_evidence(self):
        st = ev.source_stage(self.rows(200, 1.0), POLICY["staging"])
        self.assertEqual((st["stage"], st["units"]), ("STANDARD", 0.5))


def issue_body(**over):
    f = {"Source": "Odds Assist Pinnacle +EV", "Sport": "NFL", "Away team": "Broncos", "Home team": "Chiefs",
         "Game date": "_No response_", "Market": "Spread", "Pick": "Broncos", "Line": "+3.5",
         "Book": "FanDuel", "Price": "+102", "Stake (units)": "0.25", "Tool EV %": "2.4"}
    f.update(over)
    return "\n\n".join(f"### {k}\n\n{v}" for k, v in f.items())


class FakeClient:
    def __init__(self, odds=None, fail=None):
        self.odds, self.fail, self.calls = odds, fail, []
        self.remaining = 400

    def events(self, sport):
        return Matching.EVENTS

    def event_odds(self, sport, event_id, markets, books):
        self.calls.append((event_id, tuple(markets), tuple(books)))
        if self.fail:
            raise ev.EVError(self.fail)
        return self.odds


class FakeGH:
    def __init__(self):
        self.comments, self.closed = [], []

    def comment(self, n, text):
        self.comments.append((n, text))

    def close(self, n):
        self.closed.append(n)


class TrackerFlows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        tr.PLAYS_DIR, tr.CLOSES_DIR = base / "plays", base / "closes"
        tr.SUMMARY = base / "summary.md"
        tr.utcnow = lambda: NOW

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, number=7, user="isaacrome21-sys", created=NOW - timedelta(minutes=5), **body):
        return {"issue": {"number": number, "title": "[BET] Broncos +3.5", "user": {"login": user},
                          "created_at": iso(created), "body": issue_body(**body)}}

    def test_parse_issue_body(self):
        f = tr.parse_issue_body(issue_body())
        self.assertEqual(f["Line"], "+3.5")
        self.assertEqual(f["Game date"], "")

    def test_log_success_and_duplicate(self):
        gh = FakeGH()
        self.assertEqual(tr.run_log(self.payload(), POLICY, FakeClient(), gh, "isaacrome21-sys"), "LOGGED")
        rec = json.loads((tr.PLAYS_DIR / "issue-7.json").read_text())
        self.assertEqual((rec["pick"], rec["line"], rec["book"], rec["price_american"]), ("Denver Broncos", 3.5, "fanduel", 102))
        self.assertEqual(gh.closed, [7])
        self.assertEqual(tr.run_log(self.payload(), POLICY, FakeClient(), gh, "isaacrome21-sys"), "SKIP_ALREADY_LOGGED")

    def test_only_owner(self):
        self.assertEqual(tr.run_log(self.payload(user="someone"), POLICY, FakeClient(), FakeGH(), "isaacrome21-sys"),
                         "SKIP_NOT_OWNER")

    def test_rejects_after_start_and_bad_fields(self):
        gh = FakeGH()
        out = tr.run_log(self.payload(created=datetime(2026, 9, 13, 17, 5, tzinfo=timezone.utc)),
                         POLICY, FakeClient(), gh, "isaacrome21-sys")
        self.assertEqual(out, "REJECTED_LOGGED_AFTER_START")
        out = tr.run_log(self.payload(number=8, Market="Moneyline", Line="+3.5"), POLICY, FakeClient(), gh, "isaacrome21-sys")
        self.assertEqual(out, "REJECTED_LINE_INVALID")
        self.assertFalse((tr.PLAYS_DIR / "issue-8.json").exists())
        self.assertEqual(len(gh.comments), 2)

    def test_totals_pick_normalized(self):
        gh = FakeGH()
        tr.run_log(self.payload(number=9, Market="Total", Pick="u", Line="47.5"), POLICY, FakeClient(), gh, "isaacrome21-sys")
        rec = json.loads((tr.PLAYS_DIR / "issue-9.json").read_text())
        self.assertEqual((rec["pick"], rec["line"]), ("Under", 47.5))

    def test_close_flow(self):
        tr.write_record(tr.PLAYS_DIR, play())
        tr.write_record(tr.PLAYS_DIR, play(play_id="issue-2", commence_time="2026-09-13T15:30:00Z", event_id="e0"))
        tr.write_record(tr.PLAYS_DIR, play(play_id="issue-3", commence_time="2026-09-13T20:25:00Z", event_id="e2"))
        t = datetime(2026, 9, 13, 16, 30, tzinfo=timezone.utc)
        odds = {"bookmakers": [spread_book("pinnacle", -3.5, 1.95, 1.95, fetched=t),
                               spread_book("novig", -3.5, 1.97, 1.97, fetched=t)]}
        client = FakeClient(odds)
        tr.utcnow = lambda: datetime(2026, 9, 13, 16, 30, tzinfo=timezone.utc)
        result = tr.run_close(POLICY, client, now_fn=lambda: datetime(2026, 9, 13, 16, 30, tzinfo=timezone.utc))
        self.assertEqual((result["captured"], result["missed"]), (1, 1))
        self.assertEqual(client.calls, [("e1", ("spreads",), ("novig", "pinnacle", "prophetx"))])
        c = json.loads((tr.CLOSES_DIR / "issue-1.json").read_text())
        self.assertEqual(c["status"], "GRADED")
        self.assertAlmostEqual(c["clv_pp"], round(100 * (0.5 - 1 / 2.02), 3))
        self.assertFalse((tr.CLOSES_DIR / "issue-3.json").exists())

    def test_close_budget_stop_leaves_play_pending(self):
        tr.write_record(tr.PLAYS_DIR, play())
        result = tr.run_close(POLICY, FakeClient(fail="BUDGET_RESERVE_REACHED"),
                              now_fn=lambda: datetime(2026, 9, 13, 16, 30, tzinfo=timezone.utc))
        self.assertEqual(result["errors"], ["BUDGET_RESERVE_REACHED"])
        self.assertFalse((tr.CLOSES_DIR / "issue-1.json").exists())

    def test_summary(self):
        tr.write_record(tr.PLAYS_DIR, play())
        tr.write_record(tr.CLOSES_DIR, {"play_id": "issue-1", "status": "GRADED", "clv_pp": 0.495})
        text = tr.render_summary(POLICY, NOW, 321)
        self.assertIn("| Odds Assist Pinnacle +EV | MICRO | 0.25u | 1 | 1 | +0.49pp | — |", text)
        self.assertIn("NOT Model_P", text)
        self.assertIn("Denver Broncos +3.5", text)
        self.assertTrue(tr.write_summary(text))
        later = tr.render_summary(POLICY, NOW + timedelta(minutes=30), 320)
        self.assertFalse(tr.write_summary(later))


class Client(unittest.TestCase):
    class Resp:
        def __init__(self, remaining, body=b"[]"):
            self.headers, self._body = {"x-requests-remaining": str(remaining)}, body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_budget_guard_and_errors(self):
        c = tr.OddsApiClient("SECRETKEY", reserve=40, opener=lambda req, timeout: self.Resp(41))
        c.check_credits()
        with self.assertRaises(ev.EVError) as ctx:
            c.event_odds("americanfootball_nfl", "e1", ["spreads", "totals"], ["pinnacle"])
        self.assertEqual(ctx.exception.code, "BUDGET_RESERVE_REACHED")

        def unauthorized(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))
        c = tr.OddsApiClient("SECRETKEY", reserve=40, opener=unauthorized)
        with self.assertRaises(ev.EVError) as ctx:
            c.check_credits()
        self.assertEqual(ctx.exception.code, "ODDS_API_UNAUTHORIZED")
        self.assertNotIn("SECRETKEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
