import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ev_tracker_t", ROOT / "scripts/ev_tracker.py")
tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tr)
ev = tr.ev
POLICY = ev.load_active_policy(ROOT)
MAIN = {"GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "abc", "GITHUB_RUN_ID": "1"}
T0 = datetime(2026, 9, 13, 16, 0, tzinfo=timezone.utc)
KICK = "2026-09-13T17:00:00Z"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def spread_book(key, pick_line, pick_dec, other_dec, fetched, age_s=30, pick="Denver Broncos", other="Kansas City Chiefs"):
    return {"key": key, "markets": [{"key": "spreads", "last_update": iso(fetched - timedelta(seconds=age_s)),
            "outcomes": [{"name": pick, "price": pick_dec, "point": pick_line},
                         {"name": other, "price": other_dec, "point": -pick_line}]}]}


def play(**over):
    p = {"play_id": "issue-1", "source": "Odds Assist Pinnacle +EV", "sport_key": "americanfootball_nfl",
         "event_id": "e1", "commence_time": KICK, "away_team": "Denver Broncos", "home_team": "Kansas City Chiefs",
         "market": "spreads", "pick": "Denver Broncos", "line": 3.5, "book": "fanduel",
         "price_american": 102, "price_decimal": 2.02, "stake_units": 0.25, "accepted_at": iso(T0),
         "slate_date": "2026-09-13", "teams_entered_swapped": False, "policy_id": POLICY["policy_id"],
         "git_ref": "refs/heads/main"}
    p.update(over)
    return p


class Policy(unittest.TestCase):
    def test_single_active_policy(self):
        m = json.loads((ROOT / "config/ev_tracker_policy_manifest.json").read_text())
        self.assertEqual(POLICY["policy_id"], m["active"]["policy_id"])
        self.assertNotIn(m["active"]["policy_id"], [s["policy_id"] for s in m["superseded"]])

    def test_workflow_actions_pinned(self):
        import re
        text = (ROOT / ".github/workflows/ev-tracker.yml").read_text()
        uses = re.findall(r"uses:\s*([^\s#]+)", text)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")

    def test_workflow_push_failure_is_not_silent(self):
        text = (ROOT / ".github/workflows/ev-tracker.yml").read_text()
        self.assertNotIn("&& break; sleep 5; done", text)
        self.assertEqual(text.count('if [ "$pushed" != "1" ]; then echo "PUSH_FAILED'), 2)


class Math(unittest.TestCase):
    def test_conversions_and_devig(self):
        self.assertAlmostEqual(ev.american_to_decimal(-110), 1.909091, places=5)
        self.assertEqual(ev.decimal_to_american(2.5), 150)
        imp = [1 / 2.5, 1 / 1.55]
        for fn in (ev.devig_power, ev.devig_multiplicative, ev.devig_shin):
            self.assertAlmostEqual(sum(fn(imp)), 1.0, places=9)
        with self.assertRaises(ev.EVError):
            ev.devig([10.0, 1.05])

    def test_student_t_quantiles(self):
        self.assertAlmostEqual(ev.t_ppf(0.975, 9), 2.2622, places=3)
        self.assertAlmostEqual(ev.t_ppf(0.95, 19), 1.7291, places=3)
        self.assertAlmostEqual(ev.t_ppf(0.975, 1), 12.7062, places=2)

    def test_cr1_lower_bound(self):
        rows = [{"slate_date": f"d{g}", "clv_pp": 1.0 + (0.5 if g % 2 == 0 else -0.5)} for g in range(10) for _ in range(5)]
        st = ev.clv_stats(rows)
        se = ((10 / 9) * 10 * 6.25 / 2500) ** 0.5
        self.assertAlmostEqual(st["se_pp"], se)
        self.assertAlmostEqual(st["lower_bound_pp"], 1.0 - ev.t_ppf(0.975, 9) * se)

    def test_normal_line_conversion(self):
        self.assertAlmostEqual(ev.prob_at_taken_line("spreads", "X", 0.5, 3.0, 3.5, 13.5), 0.51477, places=4)
        self.assertAlmostEqual(ev.prob_at_taken_line("spreads", "X", 0.5, -3.5, -3.0, 13.5), 0.51477, places=4)
        self.assertGreater(ev.prob_at_taken_line("totals", "Over", 0.5, 48.5, 47.5, 13.5), 0.5)
        self.assertGreater(ev.prob_at_taken_line("totals", "Under", 0.5, 46.5, 47.5, 13.5), 0.5)
        self.assertEqual(ev.line_clv_pts("totals", "Over", 47.5, 48.5), 1.0)

    def test_seal(self):
        r = ev.seal({"a": 1})
        self.assertTrue(ev.verify_seal(r))
        self.assertFalse(ev.verify_seal(dict(r, a=2)))


class Staging(unittest.TestCase):
    def rows(self, n, clv, slates=40):
        return [{"slate_date": f"d{i % slates}", "clv_pp": clv + (0.3 if i % 2 else -0.3)} for i in range(n)]

    def test_start_and_demote(self):
        self.assertEqual(ev.source_stage([], 0, POLICY["staging"], "baseball_mlb")["stage"], "PROBATION")
        self.assertEqual(ev.source_stage(self.rows(50, -0.5), 50, POLICY["staging"], "baseball_mlb")["stage"], "PAPER")

    def test_promotion_needs_coverage(self):
        self.assertEqual(ev.source_stage(self.rows(200, 1.0), 200, POLICY["staging"], "baseball_mlb")["stage"], "STANDARD")
        low = ev.source_stage(self.rows(200, 1.0), 300, POLICY["staging"], "baseball_mlb")
        self.assertAlmostEqual(low["coverage"], 2 / 3)
        self.assertEqual(low["stage"], "PROBATION")

    def test_football_capped_at_probation_under_v2(self):
        for sport in ("americanfootball_nfl", "americanfootball_ncaaf"):
            st = ev.source_stage(self.rows(200, 1.0), 200, POLICY["staging"], sport)
            self.assertEqual((st["stage"], st["units"], st["capped_by"]), ("PROBATION", 0.25, "MAX_STAGE_BY_SPORT"))
        self.assertEqual(ev.source_stage(self.rows(50, -0.5), 50, POLICY["staging"], "americanfootball_nfl")["stage"], "PAPER")


class Matching(unittest.TestCase):
    EVENTS = [
        {"id": "e1", "commence_time": KICK, "away_team": "Denver Broncos", "home_team": "Kansas City Chiefs"},
        {"id": "m1", "commence_time": "2026-09-13T23:05:00Z", "away_team": "Chicago Cubs", "home_team": "St. Louis Cardinals"},
        {"id": "m2", "commence_time": "2026-09-14T23:45:00Z", "away_team": "Chicago Cubs", "home_team": "St. Louis Cardinals"},
    ]

    def test_exact_suffix_only(self):
        self.assertEqual(ev.match_event(self.EVENTS, "broncos", "City Chiefs", T0)["event"]["id"], "e1")
        with self.assertRaises(ev.EVError):
            ev.match_event(self.EVENTS, "Bronc", "Kansas", T0)

    def test_series_requires_date(self):
        with self.assertRaises(ev.EVError) as ctx:
            ev.match_event(self.EVENTS, "Cubs", "Cardinals", T0)
        self.assertEqual(ctx.exception.code, "EVENT_AMBIGUOUS")
        self.assertEqual(ev.match_event(self.EVENTS, "Cubs", "Cardinals", T0, "2026-09-14")["event"]["id"], "m2")

    def test_swapped(self):
        self.assertTrue(ev.match_event(self.EVENTS, "Chiefs", "Broncos", T0)["swapped"])


class Grading(unittest.TestCase):
    def grade(self, books, p=None, fetched=at(30)):
        return ev.grade_attempt({"bookmakers": books}, p or play(), POLICY, fetched)

    def test_same_line_consensus(self):
        f = at(30)
        r = self.grade([spread_book("pinnacle", 3.5, 1.95, 1.95, f), spread_book("novig", 3.5, 1.97, 1.97, f)])
        self.assertEqual((r["status"], r["reference_label"], r["prob_clv_method"]), ("GRADED", "CONSENSUS", "SAME_LINE"))
        self.assertAlmostEqual(r["prob_clv_pp"], round(100 * (0.5 - 1 / 2.02), 3))
        self.assertEqual(r["same_line_price_clv_pp"], r["prob_clv_pp"])

    def test_single_book_labeled(self):
        r = self.grade([spread_book("pinnacle", 3.5, 1.95, 1.95, at(30))])
        self.assertEqual(r["reference_label"], "PINNACLE_ONLY")

    def test_moved_line_is_measured_not_dropped(self):
        r = self.grade([spread_book("pinnacle", 3.0, 1.95, 1.95, at(30))])
        self.assertEqual((r["status"], r["prob_clv_method"], r["line_clv_pts"]), ("GRADED", "NORMAL_APPROX_V1", 0.5))
        self.assertAlmostEqual(r["fair_p_at_taken_line"], 0.51477, places=4)
        self.assertIsNone(r["same_line_price_clv_pp"])

    def test_moved_line_without_sigma_is_line_only(self):
        mlb = play(sport_key="baseball_mlb", line=1.5)
        r = self.grade([spread_book("pinnacle", -1.5, 2.3, 1.65, at(30))], mlb)
        self.assertEqual((r["status"], r["line_clv_pts"]), ("LINE_ONLY", 3.0))

    def test_big_move_not_converted(self):
        r = self.grade([spread_book("pinnacle", -1.0, 1.95, 1.95, at(30))])
        self.assertEqual(r["status"], "LINE_ONLY")

    def test_stale_disagreement_leave_one_out(self):
        f = at(30)
        self.assertEqual(self.grade([spread_book("pinnacle", 3.5, 1.95, 1.95, f, age_s=900)])["reason"], "NO_FRESH_SHARP_QUOTE")
        self.assertEqual(self.grade([spread_book("pinnacle", 3.5, 1.95, 1.95, f),
                                     spread_book("novig", 3.5, 2.10, 1.83, f)])["reason"], "SHARP_DISAGREEMENT")
        r = self.grade([spread_book("pinnacle", 3.5, 1.95, 1.95, f), spread_book("novig", 3.5, 1.8, 2.2, f)], play(book="novig"))
        self.assertEqual(r["reference_label"], "PINNACLE_ONLY")


def issue_body(**over):
    f = {"Source": "Odds Assist Pinnacle +EV", "Sport": "NFL", "Away team": "Broncos", "Home team": "Chiefs",
         "Game date": "_No response_", "Market": "Spread", "Pick": "Broncos", "Line": "+3.5",
         "Book": "FanDuel", "Price": "+102", "Stake (units)": "0.25", "Tool EV %": "2.4"}
    f.update(over)
    return "\n\n".join(f"### {k}\n\n{v}" for k, v in f.items())


class FakeClient:
    def __init__(self, odds=None, fail=None):
        self.odds, self.fail, self.calls = odds, fail, []

    def events(self, sport):
        if self.fail:
            raise ev.EVError(self.fail)
        return Matching.EVENTS

    def event_odds(self, sport, event_id, markets, books):
        self.calls.append(event_id)
        if self.fail:
            raise ev.EVError(self.fail)
        return self.odds(event_id) if callable(self.odds) else self.odds


class FakeGH:
    BOT_LOGIN = "github-actions[bot]"

    def __init__(self, issues=None):
        self.comments, self.closed, self.issues = [], [], list(issues or [])
        self.thread = {}

    def comment(self, n, text):
        self.comments.append(text)
        self.thread.setdefault(n, []).append({"user": {"login": self.BOT_LOGIN}, "body": text})
        for i in self.issues:
            if i["number"] == n:
                i["comments"] = len(self.thread[n])

    def close(self, n):
        self.closed.append(n)
        self.issues = [i for i in self.issues if i["number"] != n]

    def list_open_bet_issues(self, owner):
        return [dict(i) for i in self.issues]

    def issue_comments(self, n):
        return self.thread.get(n, [])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        b = Path(self.tmp.name)
        tr.PLAYS_DIR, tr.ATTEMPTS_DIR, tr.CLOSES_DIR = b / "plays", b / "attempts", b / "closes"
        tr.SUMMARY, tr.HEALTH = b / "summary.md", b / "health.md"

    def tearDown(self):
        self.tmp.cleanup()


class Logging(Base):
    def payload(self, number=7, user="isaacrome21-sys", action="opened", created=at(-5), updated=None, **body):
        return {"action": action, "issue": {"number": number, "title": "[BET] x", "user": {"login": user},
                "created_at": iso(created), "updated_at": iso(updated or created), "body": issue_body(**body)}}

    def test_log_sealed_with_provenance(self):
        gh = FakeGH()
        self.assertEqual(tr.run_log(self.payload(), POLICY, FakeClient(), gh, "isaacrome21-sys", MAIN), "LOGGED")
        rec = json.loads((tr.PLAYS_DIR / "issue-7.json").read_text())
        self.assertTrue(ev.verify_seal(rec))
        self.assertEqual((rec["pick"], rec["line"], rec["git_ref"], rec["accepted_action"]),
                         ("Denver Broncos", 3.5, "refs/heads/main", "opened"))
        self.assertEqual(tr.run_log(self.payload(action="edited"), POLICY, FakeClient(), gh, "isaacrome21-sys", MAIN),
                         "SKIP_ALREADY_LOGGED")

    def test_edit_after_start_rejected(self):
        gh = FakeGH()
        out = tr.run_log(self.payload(action="edited", updated=at(65)), POLICY, FakeClient(), gh, "isaacrome21-sys", MAIN)
        self.assertEqual(out, "REJECTED_LOGGED_AFTER_START")

    def test_owner_and_provider_errors(self):
        self.assertEqual(tr.run_log(self.payload(user="x"), POLICY, FakeClient(), FakeGH(), "isaacrome21-sys"), "SKIP_NOT_OWNER")
        out = tr.run_log(self.payload(), POLICY, FakeClient(fail="ODDS_API_TIMEOUT"), FakeGH(), "isaacrome21-sys")
        self.assertEqual(out, "DEGRADED_ODDS_API_TIMEOUT")

    def test_create_only(self):
        tr.write_new(tr.PLAYS_DIR, "issue-1", {"play_id": "issue-1"})
        with self.assertRaises(ev.EVError):
            tr.write_new(tr.PLAYS_DIR, "issue-1", {"play_id": "issue-1", "tampered": True})


class Closing(Base):
    def seed(self, **over):
        p = ev.seal(play(**over))
        tr.PLAYS_DIR.mkdir(parents=True, exist_ok=True)
        (tr.PLAYS_DIR / f"{p['play_id']}.json").write_text(json.dumps(p))

    def tick(self, minute, client):
        return tr.run_close(POLICY, client, now_fn=lambda: at(minute), env=MAIN)

    def test_retry_then_finalize_last_graded(self):
        self.seed()
        disagree = FakeClient(lambda e: {"bookmakers": [spread_book("pinnacle", 3.5, 1.95, 1.95, at(0)),
                                                        spread_book("novig", 3.5, 2.10, 1.83, at(0))]})
        self.tick(0, disagree)
        self.assertEqual(json.loads((tr.ATTEMPTS_DIR / "issue-1-a1.json").read_text())["reason"], "SHARP_DISAGREEMENT")
        good = FakeClient({"bookmakers": [spread_book("pinnacle", 3.0, 1.95, 1.95, at(30))]})
        self.tick(30, good)
        self.assertEqual(len(list(tr.ATTEMPTS_DIR.glob("*.json"))), 2)
        self.tick(61, FakeClient())
        final = json.loads((tr.CLOSES_DIR / "issue-1.json").read_text())
        self.assertEqual((final["status"], final["from_attempt"], final["attempt_count"]), ("GRADED", "issue-1-a2", 2))
        self.assertTrue(ev.verify_seal(final))

    def test_max_attempts_and_errors_do_not_count(self):
        self.seed()
        self.tick(-10, FakeClient(fail="ODDS_API_TIMEOUT"))
        self.tick(-5, FakeClient(fail="ODDS_API_TIMEOUT"))
        empty = FakeClient({"bookmakers": []})
        for m in (0, 10, 20, 30):
            self.tick(m, empty)
        self.assertEqual(len(empty.calls), 3)
        self.tick(61, FakeClient())
        final = json.loads((tr.CLOSES_DIR / "issue-1.json").read_text())
        self.assertEqual((final["status"], final["attempt_count"], final["last_reason"]), ("CLOSE_MISSED", 5, "NO_FRESH_SHARP_QUOTE"))

    def test_fatal_stops_calls(self):
        self.seed()
        self.seed(play_id="issue-2", event_id="e9")
        client = FakeClient(fail="BUDGET_RESERVE_REACHED")
        result = self.tick(0, client)
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(result["degraded"])
        reasons = {json.loads(p.read_text())["reason"] for p in tr.ATTEMPTS_DIR.glob("*.json")}
        self.assertEqual(reasons, {"BUDGET_RESERVE_REACHED"})

    def test_summary_keeps_misses_in_denominator(self):
        self.seed()
        self.seed(play_id="issue-2")
        self.seed(play_id="issue-3", git_ref="refs/heads/feature")
        self.tick(30, FakeClient({"bookmakers": [spread_book("pinnacle", 3.5, 1.95, 1.95, at(30))]}))
        tr.CLOSES_DIR.mkdir(parents=True, exist_ok=True)
        self.tick(61, FakeClient())
        text = tr.render_summary(POLICY, at(61))
        self.assertIn("| Odds Assist Pinnacle +EV | NFL | PROBATION | 0.25u | 2 | 2 | 2 | 100% |", text)
        self.assertIn("1 older or non-main plays", text)
        (tr.CLOSES_DIR / "issue-2.json").unlink()
        text = tr.render_summary(POLICY, at(61))
        self.assertIn("| 2 | 2 | 1 | 50% |", text)

    def test_sports_never_pooled(self):
        for i in range(3):
            self.seed(play_id=f"mlb-{i}", sport_key="baseball_mlb", event_id=f"m{i}")
        self.seed(play_id="nfl-1")
        text = tr.render_summary(POLICY, at(61))
        self.assertIn("| Odds Assist Pinnacle +EV | MLB | PROBATION | 0.25u | 3 |", text)
        self.assertIn("| Odds Assist Pinnacle +EV | NFL | PROBATION | 0.25u | 1 |", text)


class Sweep(Base):
    OWNER = "isaacrome21-sys"

    def issue(self, number=11, created=at(-20), updated=None, user=None, **body):
        return {"number": number, "title": "[BET] x", "user": {"login": user or self.OWNER}, "comments": 0,
                "created_at": iso(created), "updated_at": iso(updated or created), "body": issue_body(**body)}

    def test_logs_dropped_issue_with_original_time(self):
        gh = FakeGH([self.issue()])
        out = tr.run_sweep(POLICY, FakeClient(), gh, self.OWNER, MAIN)
        self.assertEqual(out["logged"], 1)
        rec = json.loads((tr.PLAYS_DIR / "issue-11.json").read_text())
        self.assertEqual((rec["accepted_action"], rec["accepted_at"]), ("sweep", iso(at(-20))))
        self.assertEqual(gh.closed, [11])
        self.assertIn("scheduled sweep", gh.comments[0])

    def test_rejection_not_repeated_until_body_changes(self):
        gh = FakeGH([self.issue(Line="banana")])
        self.assertEqual(tr.run_sweep(POLICY, FakeClient(), gh, self.OWNER, MAIN)["rejected"], 1)
        again = tr.run_sweep(POLICY, FakeClient(), gh, self.OWNER, MAIN)
        self.assertEqual((again["skipped"], len(gh.comments)), (1, 1))
        gh.issues[0]["body"] = issue_body()
        gh.issues[0]["updated_at"] = iso(at(-10))
        fixed = tr.run_sweep(POLICY, FakeClient(), gh, self.OWNER, MAIN)
        self.assertEqual(fixed["logged"], 1)

    def test_degraded_retries_silently(self):
        gh = FakeGH([self.issue()])
        out = tr.run_sweep(POLICY, FakeClient(fail="ODDS_API_TIMEOUT"), gh, self.OWNER, MAIN)
        self.assertEqual((out["degraded"], out["errors"], gh.comments), (1, ["ODDS_API_TIMEOUT"], []))
        self.assertEqual(tr.run_sweep(POLICY, FakeClient(), gh, self.OWNER, MAIN)["logged"], 1)

    def test_marker_from_non_bot_does_not_count(self):
        iss = self.issue()
        gh = FakeGH([iss])
        gh.thread[11] = [{"user": {"login": self.OWNER}, "body": tr.body_marker(iss)}]
        gh.issues[0]["comments"] = 1
        self.assertEqual(tr.run_sweep(POLICY, FakeClient(), gh, self.OWNER, MAIN)["logged"], 1)

    def test_closes_open_issue_already_logged_and_ignores_others(self):
        tr.write_new(tr.PLAYS_DIR, "issue-11", {"play_id": "issue-11"})
        gh = FakeGH([self.issue(), self.issue(number=12, user="stranger")])
        out = tr.run_sweep(POLICY, FakeClient(), gh, self.OWNER, MAIN)
        self.assertEqual((out["closed_existing"], out["logged"], gh.closed), (1, 0, [11]))
        self.assertFalse((tr.PLAYS_DIR / "issue-12.json").exists())

    def test_sweep_uses_last_update_as_decision_time(self):
        gh = FakeGH([self.issue(created=at(-20), updated=at(62))])
        self.assertEqual(tr.run_sweep(POLICY, FakeClient(), gh, self.OWNER, MAIN)["rejected"], 1)
        self.assertIn("LOGGED_AFTER_START", gh.comments[0])

    def test_workflow_lock_and_sweep_permissions(self):
        text = (ROOT / ".github/workflows/ev-tracker.yml").read_text()
        self.assertEqual(text.count("group: sportsedge-paid-odds-api"), 2)
        close_job = text.split("\n  close:")[1]
        self.assertIn("issues: write", close_job)
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", close_job)
        self.assertIn("ledger/ev_plays", close_job)


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

    def test_budget_json_schema_retry(self):
        c = tr.OddsApiClient("SECRETKEY", 40, opener=lambda r, timeout: self.Resp(41), sleep=lambda s: None)
        c.check_credits()
        with self.assertRaises(ev.EVError) as ctx:
            c.event_odds("americanfootball_nfl", "e1", ["spreads", "totals"], ["pinnacle"])
        self.assertEqual(ctx.exception.code, "BUDGET_RESERVE_REACHED")

        bad = tr.OddsApiClient("SECRETKEY", 40, opener=lambda r, timeout: self.Resp(400, b"<html>"), sleep=lambda s: None)
        with self.assertRaises(ev.EVError) as ctx:
            bad.events("americanfootball_nfl")
        self.assertEqual(ctx.exception.code, "ODDS_API_BAD_JSON")

        wrong = tr.OddsApiClient("SECRETKEY", 40, opener=lambda r, timeout: self.Resp(400, b'{"x":1}'), sleep=lambda s: None)
        with self.assertRaises(ev.EVError) as ctx:
            wrong.events("americanfootball_nfl")
        self.assertEqual(ctx.exception.code, "ODDS_API_SCHEMA")

        calls = []

        def flaky(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "slow", {}, io.BytesIO(b""))
            return self.Resp(400, b"[]")
        self.assertEqual(tr.OddsApiClient("SECRETKEY", 40, opener=flaky, sleep=lambda s: None).events("x"), [])

        def unauthorized(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b""))
        with self.assertRaises(ev.EVError) as ctx:
            tr.OddsApiClient("SECRETKEY", 40, opener=unauthorized, sleep=lambda s: None).check_credits()
        self.assertNotIn("SECRETKEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
