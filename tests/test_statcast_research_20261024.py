"""Offline regression coverage for the Statcast research archive collector.

The sample rows are REAL recorded pitches from 2026 World Series Game 1
(game_pk 849805, Tampa Bay @ Milwaukee, 2026-10-23), trimmed to the key
columns. They were chosen to pin the two cross-check semantics verified
against the MLB StatsAPI box score for that game: the pitch-clock
``automatic_ball`` row (recorded by Savant, not a thrown pitch) in Jacob
Misiorowski's line, and Abner Uribe's ``strikeout_double_play`` event
(a box-score strikeout). Hand-verified sample aggregates:
Misiorowski 9 rows / 8 thrown / 1 K; Uribe 10 rows / 10 thrown / 2 K.
"""
import hashlib
import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import collect_statcast_research as m

SAMPLE_CSV = r"""pitch_type,game_date,release_speed,player_name,batter,pitcher,events,description,zone,des,game_type,stand,p_throws,home_team,away_team,type,balls,strikes,game_year,pfx_x,pfx_z,plate_x,plate_z,outs_when_up,inning,inning_topbot,release_spin_rate,launch_speed,launch_angle,estimated_woba_using_speedangle,at_bat_number,pitch_number,game_pk
FF,2026-10-23,99,"Misiorowski, Jacob",683748,694819,,called_strike,5,,W,L,R,MIL,TB,S,0,0,2026,-1.05,1.27,-0.0834437063549518,2.3780780245638913,2,2,Top,2627,,,,13,1,849805
FF,2026-10-23,100.7,"Misiorowski, Jacob",683748,694819,,called_strike,3,,W,L,R,MIL,TB,S,0,1,2026,-1.23,1.06,0.6177113292191505,3.1575908562236794,2,2,Top,2611,,,,13,2,849805
FC,2026-10-23,97.5,"Misiorowski, Jacob",683748,694819,strikeout,swinging_strike,12,Victor Mesa Jr. strikes out swinging.,W,L,R,MIL,TB,S,0,2,2026,0.04,0.78,1.27889768820439,3.109880167401175,2,2,Top,2713,,,0,13,3,849805
FF,2026-10-23,99.2,"Misiorowski, Jacob",670764,694819,,foul,5,,W,L,R,MIL,TB,S,0,0,2026,-0.89,1.2,0.2465432901248088,2.365111272084033,1,5,Top,2456,80.1,60,,34,1,849805
FC,2026-10-23,93.5,"Misiorowski, Jacob",670764,694819,,ball,14,,W,L,R,MIL,TB,B,0,1,2026,0.38,0.56,1.373755655504694,1.4081736995682317,1,5,Top,2616,,,,34,2,849805
FF,2026-10-23,99.3,"Misiorowski, Jacob",670764,694819,,called_strike,7,,W,L,R,MIL,TB,S,1,1,2026,-1.06,1.16,-0.46296640604226447,1.683800395961264,1,5,Top,2622,,,,34,3,849805
FF,2026-10-23,99.7,"Misiorowski, Jacob",670764,694819,,foul,1,,W,L,R,MIL,TB,S,1,2,2026,-1.01,1.2,-0.3327365841570189,3.084330624636605,1,5,Top,2596,84.6,10,,34,4,849805
,2026-10-23,85.4,"Misiorowski, Jacob",670764,694819,,automatic_ball,,,W,L,R,MIL,TB,B,1,2,2026,0.29,-0.36,,,1,5,Top,1819,,,,34,5,849805
CU,2026-10-23,86.5,"Misiorowski, Jacob",670764,694819,field_out,hit_into_play,6,Taylor Walls pops out to third baseman David Hamilton in foul territory.,W,L,R,MIL,TB,X,2,2,2026,0.46,-0.59,0.6817095876372963,2.242082904868671,1,5,Top,2131,59.8,64,0.003,34,6,849805
SI,2026-10-23,99.4,"Uribe, Abner",802415,682842,,ball,11,,W,L,R,MIL,TB,B,0,0,2026,-1.14,0.17,-1.2851602518418226,3.353005868746794,1,6,Top,2325,,,,41,1,849805
SI,2026-10-23,99,"Uribe, Abner",802415,682842,,called_strike,9,,W,L,R,MIL,TB,S,1,0,2026,-1.17,0.14,0.6857699045677548,1.6620320669246378,1,6,Top,2322,,,,41,2,849805
SI,2026-10-23,100.1,"Uribe, Abner",802415,682842,,ball,14,,W,L,R,MIL,TB,B,1,1,2026,-1.22,0.18,0.934140795150828,2.2282857211056517,1,6,Top,2329,,,,41,3,849805
SI,2026-10-23,99,"Uribe, Abner",802415,682842,,foul,14,,W,L,R,MIL,TB,S,2,1,2026,-1.31,0.13,0.20403417309746352,0.9719671604186295,1,6,Top,2356,52.4,-49,,41,4,849805
SI,2026-10-23,100.3,"Uribe, Abner",802415,682842,,foul,7,,W,L,R,MIL,TB,S,2,2,2026,-1.15,0.15,-0.38426088183006524,1.6810011987892182,1,6,Top,2326,70.6,-63,,41,5,849805
SL,2026-10-23,88.7,"Uribe, Abner",802415,682842,,ball,11,,W,L,R,MIL,TB,B,2,2,2026,0.88,0.3,-0.8900856306299574,3.022090131717869,1,6,Top,2565,,,,41,6,849805
SL,2026-10-23,89.9,"Uribe, Abner",802415,682842,strikeout_double_play,swinging_strike,14,"Chandler Simpson strikes out swinging and Jonathan Aranda caught stealing 2nd, catcher William Contreras to shortstop Cooper Pratt to catcher William Contreras.",W,L,R,MIL,TB,S,3,2,2026,0.42,0.26,0.9507172275783031,0.7707018086319422,1,6,Top,2585,,,0,41,7,849805
SI,2026-10-23,99.6,"Uribe, Abner",691406,682842,,called_strike,3,,W,R,R,MIL,TB,S,0,0,2026,-1.53,0.18,0.7085068407141859,3.148383431892336,0,7,Top,2557,,,,47,1,849805
SI,2026-10-23,98.9,"Uribe, Abner",691406,682842,,foul,13,,W,R,R,MIL,TB,S,0,1,2026,-1.45,0.07,-1.0610246721647012,2.1900494890218,0,7,Top,2526,,,,47,2,849805
SL,2026-10-23,90.4,"Uribe, Abner",691406,682842,strikeout,swinging_strike,2,Junior Caminero strikes out swinging.,W,R,R,MIL,TB,S,0,2,2026,0.46,0.48,0.17450865692164252,3.056552623167486,0,7,Top,2657,,,0,47,3,849805
"""
SAMPLE_BYTES = SAMPLE_CSV.encode("utf-8")
FETCHED = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class WindowAndUrlTests(unittest.TestCase):
    def test_url_targets_inclusive_window(self):
        url = m.build_search_url(date(2026, 10, 23), date(2026, 10, 23))
        self.assertIn("game_date_gt=2026-10-23", url)
        self.assertIn("game_date_lt=2026-10-23", url)
        self.assertIn("type=details", url)
        self.assertTrue(url.startswith(m.SAVANT_CSV))

    def test_window_end_before_start_refused(self):
        with self.assertRaises(m.IntakeRefusal):
            m.build_search_url(date(2026, 10, 24), date(2026, 10, 23))

    def test_window_over_cap_refused(self):
        with self.assertRaises(m.IntakeRefusal):
            m.build_search_url(
                date(2026, 10, 20),
                date(2026, 10, 20 + m.MAX_WINDOW_DAYS),
            )


class ParseAndSummaryTests(unittest.TestCase):
    def setUp(self):
        self.rows = m.parse_pitches(SAMPLE_BYTES)

    def test_parse_keeps_all_sample_rows(self):
        self.assertEqual(len(self.rows), 19)
        self.assertTrue(all(r["game_pk"] == "849805" for r in self.rows))

    def test_automatic_ball_is_not_a_thrown_pitch(self):
        auto = [r for r in self.rows if r["description"] == "automatic_ball"]
        self.assertEqual(len(auto), 1)
        self.assertFalse(m.is_thrown_pitch(auto[0]))

    def test_strikeout_double_play_counts_as_strikeout(self):
        dp = [r for r in self.rows if r["events"] == "strikeout_double_play"]
        self.assertEqual(len(dp), 1)
        self.assertTrue(m.is_strikeout_event(dp[0]))

    def test_summary_matches_hand_verified_box_score_lines(self):
        summary = {s["pitcher"]: s for s in m.pitcher_game_summary(self.rows)}
        miz = summary[694819]
        self.assertEqual(
            (miz["pitch_rows"], miz["thrown_pitches"], miz["strikeouts"]),
            (9, 8, 1),
        )
        uribe = summary[682842]
        self.assertEqual(
            (uribe["pitch_rows"], uribe["thrown_pitches"], uribe["strikeouts"]),
            (10, 10, 2),
        )

    def test_missing_columns_refused(self):
        with self.assertRaises(m.IntakeRefusal):
            m.parse_pitches(b"game_pk,game_date\n849805,2026-10-23\n")

    def test_header_only_payload_refused(self):
        header = SAMPLE_CSV.splitlines()[0] + "\n"
        with self.assertRaises(m.IntakeRefusal):
            m.parse_pitches(header.encode("utf-8"))

    def test_row_cap_spill_refused(self):
        header = SAMPLE_CSV.splitlines()[0]
        one = SAMPLE_CSV.splitlines()[1]
        at_cap = "\n".join([header] + [one] * m.PROVIDER_ROW_CAP) + "\n"
        with self.assertRaises(m.IntakeRefusal):
            m.parse_pitches(at_cap.encode("utf-8"))
        under_cap = "\n".join([header] + [one] * (m.PROVIDER_ROW_CAP - 1)) + "\n"
        self.assertEqual(
            len(m.parse_pitches(under_cap.encode("utf-8"))),
            m.PROVIDER_ROW_CAP - 1,
        )

    def test_non_utf8_payload_refused(self):
        with self.assertRaises(m.IntakeRefusal):
            m.parse_pitches(b"\xff\xfe\x00bad")


class FilterAndArchiveTests(unittest.TestCase):
    def setUp(self):
        self.rows = m.parse_pitches(SAMPLE_BYTES)
        self.url = m.build_search_url(date(2026, 10, 23), date(2026, 10, 23))

    def test_client_side_pitcher_filter(self):
        kept = m.apply_filters(self.rows, pitcher_id=694819)
        self.assertEqual(len(kept), 9)
        self.assertTrue(all(r["pitcher"] == "694819" for r in kept))

    def test_filter_removing_everything_refused(self):
        with self.assertRaises(m.IntakeRefusal):
            m.archive_pull(
                SAMPLE_BYTES, self.rows,
                start=date(2026, 10, 23), end=date(2026, 10, 23),
                source_url=self.url, out_dir=Path("/nonexistent-irrelevant"),
                fetched_at=FETCHED, game_pk=1,
            )

    def test_archive_writes_manifest_with_matching_sha_and_labels(self):
        with TemporaryDirectory() as tmp:
            manifest = m.archive_pull(
                SAMPLE_BYTES, self.rows,
                start=date(2026, 10, 23), end=date(2026, 10, 23),
                source_url=self.url, out_dir=Path(tmp), fetched_at=FETCHED,
            )
            self.assertEqual(manifest["raw"]["rows"], 19)
            self.assertEqual(manifest["normalized"]["rows"], 19)
            self.assertEqual(
                manifest["raw"]["sha256"],
                hashlib.sha256(SAMPLE_BYTES).hexdigest(),
            )
            labels = manifest["labels"]
            self.assertTrue(labels["research_archive_only"])
            for key in ("pricing_input", "model_probability", "play_authorized",
                        "staking_authorized", "forward_clock_authority"):
                self.assertFalse(labels[key], key)
            on_disk = json.loads(
                (Path(tmp) / "statcast_manifest_2026-10-23.json").read_text()
            )
            self.assertEqual(on_disk["raw"]["sha256"], manifest["raw"]["sha256"])
            normalized_text = (
                Path(tmp) / "statcast_pitches_2026-10-23.csv"
            ).read_text()
            self.assertIn("is_thrown_pitch", normalized_text)
            self.assertIn("is_strikeout_event", normalized_text)

    def test_archive_with_pitcher_filter_summarizes_only_kept(self):
        with TemporaryDirectory() as tmp:
            manifest = m.archive_pull(
                SAMPLE_BYTES, self.rows,
                start=date(2026, 10, 23), end=date(2026, 10, 23),
                source_url=self.url, out_dir=Path(tmp), fetched_at=FETCHED,
                pitcher_id=682842,
            )
            self.assertEqual(manifest["normalized"]["rows"], 10)
            self.assertEqual(len(manifest["pitcher_game_summary"]), 1)
            self.assertEqual(
                manifest["pitcher_game_summary"][0]["strikeouts"], 2
            )


class TransportTests(unittest.TestCase):
    def test_injected_opener_round_trip(self):
        raw = m.fetch_csv("https://example.invalid/x", opener=lambda req: SAMPLE_BYTES)
        self.assertEqual(len(m.parse_pitches(raw)), 19)

    def test_dry_run_makes_no_network_call(self):
        def forbidden(request):  # pragma: no cover - must never run
            raise AssertionError("network call during dry run")

        original = m.fetch_csv
        m.fetch_csv = forbidden
        try:
            self.assertEqual(m.main(["--date", "2026-10-23"]), 0)
        finally:
            m.fetch_csv = original


if __name__ == "__main__":
    unittest.main()
