from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sportsedge.evidence import (
    EvidencePacket,
    lineup_status_evidence,
    market_quote_evidence,
    resolve_evidence,
    starter_evidence,
)
from sportsedge.mlb_run_machine import run_mlb_machine

NOW = datetime(2026, 8, 27, 15, 45, tzinfo=timezone.utc)


def result(*, entity_id="301", market="HITS", status="OFFICIAL_BET"):
    return SimpleNamespace(
        source_index=0,
        game_id="823014",
        market=market,
        entity_id=entity_id,
        line=0.5,
        side="OVER",
        american_odds=-110,
        model_p=0.61,
        bet_status=status,
        reason="ok",
        shadow_status="SHADOW_BET",
        implied_probability=0.50,
        edge=0.11,
        ev_per_dollar=0.12,
    )


def auto_report(rows):
    return SimpleNamespace(
        slate_date_ct="2026-08-27",
        generated_at_utc=NOW.isoformat(),
        run_status="PASS",
        results=tuple(rows),
        source_failures=(),
    )


class EvidenceResolutionTests(unittest.TestCase):
    def test_acquisition_mode_is_provenance_not_decision_semantics(self):
        common = dict(
            game_id="823014",
            team_id="STL",
            starter_id="GRACEFFO",
            source_name="MLB.com",
            observed_at_utc=NOW,
            authority="AUTHORITATIVE",
            verified=True,
        )
        manual = starter_evidence(acquisition_mode="MANUAL", **common)
        automatic = starter_evidence(acquisition_mode="AUTOMATIC", **common)
        self.assertEqual(manual.content_sha256, automatic.content_sha256)
        self.assertEqual(
            resolve_evidence([manual], now=NOW).status,
            resolve_evidence([automatic], now=NOW).status,
        )
        self.assertEqual(resolve_evidence([manual], now=NOW).status, "PASS")

    def test_verified_authoritative_starter_overrides_advisory_projection(self):
        projected = starter_evidence(
            game_id="823014",
            team_id="STL",
            starter_id="HJERPE",
            source_name="third-party projection",
            observed_at_utc=NOW - timedelta(minutes=30),
            acquisition_mode="MANUAL",
            authority="ADVISORY",
            verified=True,
        )
        confirmed = starter_evidence(
            game_id="823014",
            team_id="STL",
            starter_id="GRACEFFO",
            source_name="MLB.com",
            observed_at_utc=NOW,
            acquisition_mode="HYBRID",
            authority="AUTHORITATIVE",
            verified=True,
        )
        resolution = resolve_evidence([projected, confirmed], now=NOW)
        self.assertEqual(resolution.status, "PASS")
        self.assertEqual(len(resolution.winners), 1)
        self.assertEqual(resolution.winners[0].value, "GRACEFFO")
        self.assertEqual(resolution.conflicts[0].severity, "INFO")
        self.assertEqual(resolution.conflicts[0].reason, "LOWER_PRIORITY_FACT_OVERRIDDEN")

    def test_simultaneous_verified_authoritative_starter_conflict_fails_closed(self):
        a = starter_evidence(
            game_id="823014",
            team_id="STL",
            starter_id="GRACEFFO",
            source_name="MLB.com",
            observed_at_utc=NOW,
            acquisition_mode="AUTOMATIC",
        )
        b = starter_evidence(
            game_id="823014",
            team_id="STL",
            starter_id="HJERPE",
            source_name="MLB StatsAPI",
            observed_at_utc=NOW,
            acquisition_mode="AUTOMATIC",
        )
        resolution = resolve_evidence([a, b], now=NOW)
        self.assertEqual(resolution.status, "BLOCKED")
        self.assertEqual(resolution.conflicts[0].severity, "BLOCK")
        self.assertEqual(
            resolution.conflicts[0].reason,
            "SIMULTANEOUS_AUTHORITATIVE_FACTS_DISAGREE",
        )
        self.assertEqual(resolution.blocks[0].scope, "GAME")

    def test_newer_verified_authoritative_starter_supersedes_older_official_state(self):
        older = starter_evidence(
            game_id="823014",
            team_id="STL",
            starter_id="HJERPE",
            source_name="MLB.com earlier snapshot",
            observed_at_utc=NOW - timedelta(minutes=20),
            acquisition_mode="MANUAL",
        )
        newer = starter_evidence(
            game_id="823014",
            team_id="STL",
            starter_id="GRACEFFO",
            source_name="MLB.com refreshed",
            observed_at_utc=NOW,
            acquisition_mode="AUTOMATIC",
        )
        resolution = resolve_evidence([older, newer], now=NOW)
        self.assertEqual(resolution.status, "PASS")
        self.assertEqual(resolution.winners[0].value, "GRACEFFO")
        self.assertEqual(resolution.conflicts[0].severity, "INFO")
        self.assertEqual(
            resolution.conflicts[0].reason,
            "NEWER_AUTHORITATIVE_FACT_SUPERSEDES_OLDER",
        )

    def test_equal_priority_weather_disagreement_is_never_averaged(self):
        older = EvidencePacket(
            game_id="ARI-SF",
            fact_type="WEATHER_TEMPERATURE_F",
            subject_id="ORACLE_PARK",
            value=73,
            source_name="feed-a",
            observed_at_utc=(NOW - timedelta(minutes=10)).isoformat(),
            acquisition_mode="MANUAL",
            authority="ADVISORY",
            verified=True,
        )
        newer = EvidencePacket(
            game_id="ARI-SF",
            fact_type="WEATHER_TEMPERATURE_F",
            subject_id="ORACLE_PARK",
            value=65,
            source_name="feed-b",
            observed_at_utc=NOW.isoformat(),
            acquisition_mode="AUTOMATIC",
            authority="ADVISORY",
            verified=True,
        )
        resolution = resolve_evidence([older, newer], now=NOW)
        self.assertEqual(resolution.status, "PASS")
        self.assertEqual(resolution.winners[0].value, 65)
        self.assertEqual(resolution.conflicts[0].severity, "DOWNWEIGHT")
        self.assertEqual(
            resolution.conflicts[0].reason,
            "EQUAL_PRIORITY_FACTS_DISAGREE_NEWEST_SELECTED",
        )

    def test_stale_price_is_rejected_before_resolution(self):
        stale = market_quote_evidence(
            game_id="823014",
            market="HITS",
            entity_id="301",
            side="OVER",
            line=0.5,
            american_odds=195,
            source_name="stale board",
            observed_at_utc=NOW - timedelta(minutes=20),
            expires_at_utc=NOW - timedelta(minutes=10),
            acquisition_mode="MANUAL",
            verified=True,
        )
        live = market_quote_evidence(
            game_id="823014",
            market="HITS",
            entity_id="301",
            side="OVER",
            line=0.5,
            american_odds=-115,
            source_name="sportsbook live",
            observed_at_utc=NOW - timedelta(minutes=1),
            expires_at_utc=NOW + timedelta(minutes=4),
            acquisition_mode="AUTOMATIC",
            verified=True,
        )
        resolution = resolve_evidence([stale, live], now=NOW)
        self.assertEqual(len(resolution.rejected_stale), 1)
        self.assertEqual(len(resolution.winners), 1)
        self.assertEqual(resolution.winners[0].value["american_odds"], -115)

    def test_confirmed_absent_lineup_player_blocks_only_that_entity(self):
        packet = lineup_status_evidence(
            game_id="823014",
            player_id="GOODMAN",
            in_starting_lineup=False,
            source_name="MLB.com",
            observed_at_utc=NOW,
            acquisition_mode="MANUAL",
        )
        resolution = resolve_evidence([packet], now=NOW)
        self.assertIsNotNone(resolution.block_for(
            game_id="823014", market="HOME_RUNS", entity_id="GOODMAN"
        ))
        self.assertIsNone(resolution.block_for(
            game_id="823014", market="TOTALS", entity_id="823014"
        ))
        self.assertIsNone(resolution.block_for(
            game_id="823014", market="HOME_RUNS", entity_id="OTHER"
        ))

    @patch("sportsedge.mlb_run_machine.run_auto_mlb_native_odds")
    def test_same_evidence_gate_is_applied_to_automatic_machine_results(self, runner):
        runner.return_value = auto_report([
            result(entity_id="GOODMAN", market="HOME_RUNS"),
            result(entity_id="OTHER", market="HOME_RUNS"),
        ])
        packet = lineup_status_evidence(
            game_id="823014",
            player_id="GOODMAN",
            in_starting_lineup=False,
            source_name="MLB.com",
            observed_at_utc=NOW,
            acquisition_mode="MANUAL",
        )
        report = run_mlb_machine(
            mode="AUTOMATIC",
            odds_api_key="secret",
            evidence_packets=[packet],
            now=NOW,
        )
        self.assertEqual(report.results[0].bet_status, "BLOCKED")
        self.assertEqual(report.results[0].reason, "EVIDENCE_GATE:STARTING_LINEUP_STATUS:GOODMAN")
        self.assertEqual(report.results[1].bet_status, "OFFICIAL_BET")
        self.assertEqual(report.summary["evidence"]["block_count"], 1)
        self.assertEqual(report.summary["blocked"], 1)


if __name__ == "__main__":
    unittest.main()
