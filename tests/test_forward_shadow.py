from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.forward_shadow import ForwardShadowError, ShadowPrediction, build_manifest, write_prediction_ledger


class ForwardShadowTests(unittest.TestCase):
    def row(self, **kw):
        base=dict(
            market="NRFI", game_id="123", entity_id="123", side="UNDER", line=0.5,
            model_p=.54, generated_at_utc="2026-08-13T15:00:00+00:00",
            cutoff_at_utc="2026-08-13T17:00:00+00:00",
            model_artifact_sha256="a"*64, feature_contract_sha256="b"*64,
            source_cutoff="2026-08-12", model_version="NRFI_V6_FORWARD_SHADOW",
            identity={"away_starter_id":1,"home_starter_id":2}, provenance={"lineup":"projected"},
        ); base.update(kw); return ShadowPrediction(**base)

    def test_pregame_row_is_bound_and_outcomeless(self):
        d=self.row().to_dict()
        self.assertEqual(len(d["row_id"]),64)
        self.assertIsNone(d["outcome"])
        self.assertIsNone(d["outcome_attached_at_utc"])

    def test_late_prediction_fails(self):
        with self.assertRaisesRegex(ForwardShadowError,"PREDICTION_NOT_PREGAME"):
            self.row(generated_at_utc="2026-08-13T17:00:00+00:00").to_dict()

    def test_manifest_rejects_outcome(self):
        d=self.row().to_dict(); d["outcome"]=1
        with self.assertRaisesRegex(ForwardShadowError,"PREDICTION_LEDGER_CONTAINS_OUTCOME"):
            build_manifest([d],generated_at=datetime.now(timezone.utc))

    def test_write_manifest_hashes_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"ledger.json"; man=Path(td)/"manifest.json"
            write_prediction_ledger([self.row()],output=out,manifest=man,generated_at=datetime(2026,8,13,15,tzinfo=timezone.utc))
            m=json.loads(man.read_text())
            self.assertEqual(m["prediction_count"],1)
            self.assertFalse(m["outcomes_present"])
            self.assertEqual(len(m["ledger_file_sha256"]),64)

if __name__ == "__main__": unittest.main()
