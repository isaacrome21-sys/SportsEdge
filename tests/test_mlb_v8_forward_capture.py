from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).parents[1]/"scripts"/"capture_mlb_v8_forward.py"
spec=importlib.util.spec_from_file_location("capture_mlb_v8_forward",SCRIPT)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class ForwardCaptureTests(unittest.TestCase):
    def test_pre_epoch_raw_is_not_v8_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); raw_root=root/"raw"; out=root/"out"
            day=raw_root/"2026-09-02"/"Tminus90m"; day.mkdir(parents=True)
            raw=day/"game_odds_20260902T200000Z.json"; raw.write_text("[]")
            statusdir=raw_root/"status"/"2026-09-02"; statusdir.mkdir(parents=True)
            (statusdir/"s.json").write_text(json.dumps({"raw_file":str(raw),"run_at_utc":"2026-09-02T20:00:00Z","slate_date_ct":"2026-09-02","capture_window":"T-90"}))
            manifest=mod.canonicalize(raw_root,out)
            self.assertEqual(manifest["rows_written"],0)
            self.assertEqual(manifest["skipped_pre_epoch"],1)

    def test_post_epoch_raw_canonicalizes_with_gamepk(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); raw_root=root/"raw"; out=root/"out"
            day=raw_root/"2026-09-03"/"Tminus90m"; day.mkdir(parents=True)
            payload=[{"id":"provider1","commence_time":"2026-09-03T22:10:00Z","home_team":"Chicago Cubs","away_team":"Milwaukee Brewers","bookmakers":[{"key":"draftkings","last_update":"2026-09-03T20:39:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Chicago Cubs","price":-120},{"name":"Milwaukee Brewers","price":105}]}]}]}]
            raw=day/"game_odds_20260903T204000Z.json"; raw.write_text(json.dumps(payload))
            statusdir=raw_root/"status"/"2026-09-03"; statusdir.mkdir(parents=True)
            (statusdir/"s.json").write_text(json.dumps({"raw_file":str(raw),"run_at_utc":"2026-09-03T20:40:00Z","slate_date_ct":"2026-09-03","capture_window":"T-90"}))
            schedule=[{"game_pk":"777","commence_time_utc":"2026-09-03T22:10:00Z","home_team":"Chicago Cubs","away_team":"Milwaukee Brewers"}]
            with patch.object(mod,"_schedule",return_value=schedule):
                manifest=mod.canonicalize(raw_root,out)
            self.assertEqual(manifest["rows_written"],2)
            rows=[json.loads(x) for x in (out/"2026-09-03"/"market_snapshots.jsonl").read_text().splitlines()]
            self.assertEqual({r["event_id"] for r in rows},{"777"})
            self.assertEqual({r["checkpoint"] for r in rows},{"T-90"})
            self.assertTrue(all(r["decision_eligible"] for r in rows))

if __name__=="__main__": unittest.main()
