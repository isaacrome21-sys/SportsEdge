from __future__ import annotations

import json
from pathlib import Path


ROOT = Path('.')


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}_ANCHOR_MISSING')
    path.write_text(text.replace(old, new, 1))


# Policy: DraftKings-only, MLB parked, and the existing NFL reserve contract is the single source of truth.
policy_path = ROOT / 'config/closing_line_archive_policy_v1.json'
policy = json.loads(policy_path.read_text())
policy['doctrine'] = (
    'Model-free two-sided price archival for NFL, CFB and UFC/MMA. This lane observes prices only. '
    'It contains no Model_P, no evidence_unit_id, and no decision. It can never be promoted, can never '
    'start or extend a promotion evidence clock, and can never be substituted for FOOTBALL_FORWARD_CAPTURE_V2, '
    'MLB replay evidence, or UFC promotion evidence. MLB is parked and receives zero scheduled paid archive calls. '
    'The t0_prestart window is a final scheduled-start-adjacent observation only and is valid solely while '
    'commence_time is still strictly in the future. DraftKings observations may feed zero-authority diagnostics; '
    'without a configured market-maker observation, price leadership is unavailable rather than inferred from DraftKings.'
)
policy['sports'].pop('MLB', None)
policy['parked_sports'] = {
    'MLB': {
        'sport_key': 'baseball_mlb',
        'scheduled_paid_capture': False,
        'reason': 'MLB_PARKED_ZERO_SCHEDULED_PAID_ARCHIVE_CALLS',
    }
}
policy['books'] = ['draftkings']
policy['market_radar']['soft_books'] = ['draftkings']
policy['provider_budget_guard'] = {
    'enabled': True,
    'budget_path': 'config/nfl_2026_provider_budget_v1.json',
    'paid_request_cost_credits': 3,
    'rule': 'REPROBE_BEFORE_EVERY_PAID_CALL_AND_SKIP_IF_REQUEST_WOULD_BREACH_NFL_CONFIRMATION_RESERVE',
}
policy_path.write_text(json.dumps(policy, indent=2) + '\n')


# V3 transport: re-probe quota before every paid sport call and only hand ready key slots to the paid fetch.
script_path = ROOT / 'scripts/capture_closing_line_archive_v3.py'
replace_once(
    script_path,
    'import scripts.capture_closing_line_archive as v1\nimport scripts.capture_closing_line_archive_v2 as v2\n\nUTC = timezone.utc\nRAW_ARCHIVE_VERSION = "RAW_PAYLOAD_GUARD_V3"\n',
    'import scripts.capture_closing_line_archive as v1\nimport scripts.capture_closing_line_archive_v2 as v2\nimport scripts.odds_api_quota_guard as quota_guard\n\nUTC = timezone.utc\nRAW_ARCHIVE_VERSION = "RAW_PAYLOAD_GUARD_V3"\nDEFAULT_PROVIDER_BUDGET_PATH = "config/nfl_2026_provider_budget_v1.json"\n',
    'V3_IMPORT',
)
helpers = '''\n\ndef _provider_budget_contract(policy: Mapping[str, Any]) -> dict[str, int] | None:\n    guard = policy.get("provider_budget_guard") or {}\n    if guard.get("enabled") is not True:\n        return None\n    budget_path = Path(str(guard.get("budget_path") or DEFAULT_PROVIDER_BUDGET_PATH))\n    try:\n        budget = json.loads(budget_path.read_text(encoding="utf-8"))\n        reserve = budget["lower_priority_paid_work"]["minimum_confirmation_reserve_credits"]\n        request_cost = guard["paid_request_cost_credits"]\n    except Exception as exc:\n        raise v1.ArchiveError("CLOSING_LINE_ARCHIVE_PROVIDER_BUDGET_INVALID") from exc\n    if not isinstance(reserve, int) or reserve < 0:\n        raise v1.ArchiveError("CLOSING_LINE_ARCHIVE_PROVIDER_RESERVE_INVALID")\n    if not isinstance(request_cost, int) or request_cost <= 0:\n        raise v1.ArchiveError("CLOSING_LINE_ARCHIVE_REQUEST_COST_INVALID")\n    return {\n        "confirmation_reserve_credits": reserve,\n        "paid_request_cost_credits": request_cost,\n        "minimum_remaining_before_request": reserve + request_cost,\n    }\n\n\ndef _reserve_ready_keys(\n    keys: list[str],\n    *,\n    policy: Mapping[str, Any],\n    opener,\n) -> tuple[list[str], dict[str, Any] | None]:\n    contract = _provider_budget_contract(policy)\n    if contract is None:\n        return list(keys), None\n    slots = [(f"ARCHIVE_KEY_{idx + 1}", key) for idx, key in enumerate(keys)]\n    report = quota_guard.probe_quota(\n        slots,\n        minimum_remaining=contract["minimum_remaining_before_request"],\n        opener=opener,\n    )\n    ready_slots = set(report.get("ready_key_slots") or [])\n    eligible = [key for slot, key in slots if slot in ready_slots]\n    summary = {\n        "state": report.get("state"),\n        "reason": report.get("reason"),\n        "minimum_remaining": report.get("minimum_remaining"),\n        "max_remaining": report.get("max_remaining"),\n        "ready_key_slots": sorted(ready_slots),\n        "tested_key_slots": list(report.get("tested_key_slots") or []),\n        **contract,\n        "authority": quota_guard.zero_authority(),\n    }\n    return eligible, summary\n'''
replace_once(
    script_path,
    '\ndef run(\n    *,\n    now: datetime,\n',
    helpers + '\ndef run(\n    *,\n    now: datetime,\n',
    'V3_RUN',
)
replace_once(
    script_path,
    '        if due and not dry_run:\n            odds_payload = v1.fetch_odds(sport_key, policy, keys, opener)\n            entry["paid_call_made"] = True\n            raw_path, raw_sha = persist_raw_payload(sport_key, odds_payload, out_dir)\n',
    '        if due and not dry_run:\n            paid_keys, budget_guard = _reserve_ready_keys(keys, policy=policy, opener=opener)\n            if budget_guard is not None:\n                entry["provider_budget_guard"] = budget_guard\n            if not paid_keys:\n                if budget_guard and budget_guard.get("reason") != "INSUFFICIENT_REMAINING_CREDITS":\n                    raise v1.ArchiveError(\n                        f"CLOSING_LINE_ARCHIVE_QUOTA_PREFLIGHT_BLOCKED:{budget_guard.get(\'reason\') or \'UNKNOWN\'}"\n                    )\n                entry["paid_call_skipped"] = True\n                entry["skip_reason"] = "NFL_CONFIRMATION_RESERVE_GUARD"\n                report["sports"][label] = entry\n                continue\n            odds_payload = v1.fetch_odds(sport_key, policy, paid_keys, opener)\n            entry["paid_call_made"] = True\n            raw_path, raw_sha = persist_raw_payload(sport_key, odds_payload, out_dir)\n',
    'V3_PAID_FETCH',
)


# Existing policy tests.
test_path = ROOT / 'tests/test_closing_line_archive.py'
text = test_path.read_text()
text = text.replace(
    'def test_paid_archive_is_us_only_and_excludes_pinnacle(self):',
    'def test_paid_archive_is_draftkings_only_us_and_excludes_pinnacle_fanduel(self):',
)
text = text.replace(
    'self.assertEqual(POLICY["books"], ["draftkings", "fanduel"])',
    'self.assertEqual(POLICY["books"], ["draftkings"])\n        self.assertNotIn("fanduel", POLICY["books"])',
)
text = text.replace(
    'self.assertEqual(set(POLICY["sports"]), {"NFL", "CFB", "MLB", "UFC"})',
    'self.assertEqual(set(POLICY["sports"]), {"NFL", "CFB", "UFC"})\n        self.assertNotIn("MLB", POLICY["sports"])\n        self.assertFalse(POLICY["parked_sports"]["MLB"]["scheduled_paid_capture"])',
)
test_path.write_text(text)


# Radar bridge: DK-only native archive must never invent a market-maker leader.
radar_path = ROOT / 'tests/test_market_maker_radar.py'
text = radar_path.read_text()
text = text.replace(
    'def test_archive_uses_dk_and_fd_only_without_fake_circa(self):',
    'def test_archive_uses_dk_only_without_fake_circa_or_reference_book(self):',
)
text = text.replace(
    'self.assertEqual(set(archive["books"]), {"draftkings", "fanduel"})',
    'self.assertEqual(set(archive["books"]), {"draftkings"})',
)
text = text.replace(
    '        self.assertNotIn("pinnacle", archive["books"])\n',
    '        self.assertNotIn("pinnacle", archive["books"])\n        self.assertNotIn("fanduel", archive["books"])\n',
    1,
)
anchor = '''class LeadLagTests(unittest.TestCase):
    def test_pinnacle_lead_to_dk_and_fd_is_separate_source_family(self):
'''
insert = '''class LeadLagTests(unittest.TestCase):
    def test_draftkings_only_history_cannot_assign_market_maker_leader(self):
        rows = [
            row(capture="c0", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Home", price=-110),
            row(capture="c1", captured_at="2026-09-14T12:05:00Z", book="draftkings", outcome="Home", price=-125),
        ]
        report = analyze(rows, POLICY)
        self.assertEqual(report["lead_lag_signal_count"], 0)
        self.assertEqual(report["synchronous_pair_count"], 0)

    def test_pinnacle_lead_to_dk_and_fd_is_separate_source_family(self):
'''
if anchor not in text:
    raise SystemExit('RADAR_TEST_ANCHOR_MISSING')
radar_path.write_text(text.replace(anchor, insert, 1))


# Dedicated reserve tests.
reserve_test = ROOT / 'tests/test_closing_line_archive_credit_guard.py'
reserve_test.write_text('''import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import capture_closing_line_archive_v3 as v3

UTC = timezone.utc
NOW = datetime(2026, 9, 18, 23, 0, tzinfo=UTC)


def policy(sports=None):
    return {
        "policy_id": "CLOSING_LINE_ARCHIVE_V1",
        "sports": sports or {"CFB": "americanfootball_ncaaf"},
        "books": ["draftkings"],
        "markets": ["h2h", "spreads", "totals"],
        "regions": "us",
        "odds_format": "american",
        "windows": {"decision": {"min_minutes_before_start": 45, "max_minutes_before_start": 120}},
        "persistence": {"path_template": "archive/closing-lines/{sport_key}/{date}.ndjson"},
        "provider_budget_guard": {
            "enabled": True,
            "budget_path": "config/nfl_2026_provider_budget_v1.json",
            "paid_request_cost_credits": 3,
        },
    }


def event(event_id="g1"):
    return {
        "id": event_id,
        "commence_time": "2026-09-19T00:00:00Z",
        "home_team": "Home",
        "away_team": "Away",
    }


def odds(event_id="g1"):
    return [{
        **event(event_id),
        "bookmakers": [{
            "key": "draftkings",
            "last_update": "2026-09-18T22:59:55Z",
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "Home", "price": -110},
                    {"name": "Away", "price": -110},
                ],
            }],
        }],
    }]


class ArchiveCreditGuardTests(unittest.TestCase):
    def test_below_79_skips_without_paid_fetch(self):
        blocked = {
            "state": "BLOCKED",
            "reason": "INSUFFICIENT_REMAINING_CREDITS",
            "minimum_remaining": 79,
            "max_remaining": 78,
            "ready_key_slots": [],
            "tested_key_slots": ["ARCHIVE_KEY_1"],
        }
        with tempfile.TemporaryDirectory() as td, \\
             patch.object(v3.v1, "fetch_event_index", return_value=[event()]), \\
             patch.object(v3.quota_guard, "probe_quota", return_value=blocked) as probe, \\
             patch.object(v3.v1, "fetch_odds") as paid:
            report = v3.run(now=NOW, policy=policy(), out_dir=Path(td), keys=["k1"], opener=None)
        paid.assert_not_called()
        self.assertEqual(probe.call_args.kwargs["minimum_remaining"], 79)
        entry = report["sports"]["CFB"]
        self.assertFalse(entry["paid_call_made"])
        self.assertTrue(entry["paid_call_skipped"])
        self.assertEqual(entry["skip_reason"], "NFL_CONFIRMATION_RESERVE_GUARD")
        self.assertEqual(entry["provider_budget_guard"]["confirmation_reserve_credits"], 76)
        self.assertEqual(entry["provider_budget_guard"]["paid_request_cost_credits"], 3)

    def test_unknown_quota_fails_closed(self):
        blocked = {
            "state": "BLOCKED",
            "reason": "QUOTA_STATE_UNKNOWN",
            "minimum_remaining": 79,
            "max_remaining": None,
            "ready_key_slots": [],
            "tested_key_slots": ["ARCHIVE_KEY_1"],
        }
        with tempfile.TemporaryDirectory() as td, \\
             patch.object(v3.v1, "fetch_event_index", return_value=[event()]), \\
             patch.object(v3.quota_guard, "probe_quota", return_value=blocked), \\
             patch.object(v3.v1, "fetch_odds") as paid:
            with self.assertRaisesRegex(Exception, "QUOTA_PREFLIGHT_BLOCKED:QUOTA_STATE_UNKNOWN"):
                v3.run(now=NOW, policy=policy(), out_dir=Path(td), keys=["k1"], opener=None)
        paid.assert_not_called()

    def test_only_ready_key_slot_can_reach_paid_fetch(self):
        ready = {
            "state": "READY",
            "reason": "RESERVE_SATISFIED",
            "minimum_remaining": 79,
            "max_remaining": 120,
            "ready_key_slots": ["ARCHIVE_KEY_2"],
            "tested_key_slots": ["ARCHIVE_KEY_1", "ARCHIVE_KEY_2"],
        }
        with tempfile.TemporaryDirectory() as td, \\
             patch.object(v3.v1, "fetch_event_index", return_value=[event()]), \\
             patch.object(v3.quota_guard, "probe_quota", return_value=ready), \\
             patch.object(v3.v1, "fetch_odds", return_value=odds()) as paid:
            report = v3.run(now=NOW, policy=policy(), out_dir=Path(td), keys=["k1", "k2"], opener=None)
        self.assertEqual(paid.call_args.args[2], ["k2"])
        self.assertTrue(report["sports"]["CFB"]["paid_call_made"])

    def test_each_due_sport_reprobes_before_its_paid_call(self):
        ready = {
            "state": "READY",
            "reason": "RESERVE_SATISFIED",
            "minimum_remaining": 79,
            "max_remaining": 120,
            "ready_key_slots": ["ARCHIVE_KEY_1"],
            "tested_key_slots": ["ARCHIVE_KEY_1"],
        }
        sports = {"NFL": "americanfootball_nfl", "CFB": "americanfootball_ncaaf"}
        with tempfile.TemporaryDirectory() as td, \\
             patch.object(v3.v1, "fetch_event_index", return_value=[event()]), \\
             patch.object(v3.quota_guard, "probe_quota", return_value=ready) as probe, \\
             patch.object(v3.v1, "fetch_odds", return_value=[]) as paid:
            v3.run(now=NOW, policy=policy(sports), out_dir=Path(td), keys=["k1"], opener=None)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(paid.call_count, 2)


if __name__ == "__main__":
    unittest.main()
''')


# Workflow wording reflects the actual paid lane.
workflow_path = ROOT / '.github/workflows/closing-line-archive.yml'
text = workflow_path.read_text()
text = text.replace(
    '# archival for NFL, CFB and MLB. Rows remain NOT_EVIDENCE. V3 additionally',
    '# archival for NFL, CFB and UFC/MMA. MLB is parked. Rows remain NOT_EVIDENCE. V3 additionally',
)
text = text.replace(
    '# MLB remains guarded by StatsAPI status/first-play before a paid capture is\n# admitted. Overlapping windows use explicit priority: close > t0_prestart >\n# decision. No promotion or evidence-clock authority is granted here.',
    '# Every paid request re-probes the zero-credit provider quota endpoint and must preserve\n# the frozen NFL confirmation reserve. Overlapping windows use explicit priority:\n# close > t0_prestart > decision. No promotion or evidence-clock authority is granted here.',
)
text = text.replace('Capture paid multi-book archive', 'Capture paid DraftKings-only archive')
workflow_path.write_text(text)


# Reconcile protected main through PR #842 before this new governed-surface change.
registry_path = ROOT / 'config/freeze_reconciliation_registry_v1.json'
registry = json.loads(registry_path.read_text())
expected_old = '6b842b17ca0bb1eec7370daaf3a981189ecf4e00'
target = '0ea693e36f0832ac0427cd9d278b3b0312d0350e'
row842 = {
    'delta_id': 'PR_842_CLV_REMOVE_PINNACLE_EU',
    'merge_sha': target,
    'note': 'Reduces the zero-authority closing-line archive to US DraftKings/FanDuel without Pinnacle/EU. Rows remain NOT_EVIDENCE; no Model_P, Truth Gate, promotion, eligibility, staking, evidence-clock, backfill, or OFFICIAL authority is granted.',
    'pr': 842,
}
current = registry.get('reconciled_through_sha')
if current not in {expected_old, target}:
    raise SystemExit(f'UNEXPECTED_RECONCILIATION_BOUNDARY:{current}')
existing = {item['delta_id']: item for item in registry['deltas']}
prior = existing.get(row842['delta_id'])
if prior is None:
    registry['deltas'].append(row842)
elif prior != row842:
    raise SystemExit('PR842_DELTA_IDENTITY_DRIFT')
registry['reconciled_through_sha'] = target
registry_path.write_text(json.dumps(registry, separators=(',', ':')) + '\n')

hist_path = ROOT / 'tests/test_reconciliation_catchup_pr815.py'
text = hist_path.read_text()
anchor = "    (840, '6b842b17ca0bb1eec7370daaf3a981189ecf4e00'),\n]"
replacement = "    (840, '6b842b17ca0bb1eec7370daaf3a981189ecf4e00'),\n    (842, '0ea693e36f0832ac0427cd9d278b3b0312d0350e'),\n]"
if "(842, '0ea693e36f0832ac0427cd9d278b3b0312d0350e')" not in text:
    if anchor not in text:
        raise SystemExit('PR842_HISTORY_ANCHOR_MISSING')
    text = text.replace(anchor, replacement, 1)
text = text.replace(
    'test_reconciliation_advances_through_pr840_in_first_parent_order',
    'test_reconciliation_advances_through_pr842_in_first_parent_order',
)
hist_path.write_text(text)
