import hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from sportsedge.statcast_v5_artifacts import StatcastV5ArtifactError, _manifest_rows

class Tests(unittest.TestCase):
    def test_manifest_requires_unique_sha_bound_files(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'manifest.json'
            p.write_text(json.dumps({'schema_version':1,'files':[{'path':'a.joblib','sha256':'a'*64,'bytes':1}]}))
            rows=_manifest_rows(p)
            self.assertEqual(rows['a.joblib']['sha256'],'a'*64)

    def test_duplicate_manifest_filename_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'manifest.json'
            p.write_text(json.dumps({'schema_version':1,'files':[{'path':'x/a.joblib','sha256':'a'*64},{'path':'y/a.joblib','sha256':'b'*64}]}))
            with self.assertRaisesRegex(StatcastV5ArtifactError,'MANIFEST_DUPLICATE'):
                _manifest_rows(p)

    def test_bad_sha_shape_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'manifest.json'
            p.write_text(json.dumps({'schema_version':1,'files':[{'path':'a.joblib','sha256':'not-a-sha'}]}))
            with self.assertRaisesRegex(StatcastV5ArtifactError,'MANIFEST_IDENTITY_INVALID'):
                _manifest_rows(p)

if __name__=='__main__': unittest.main()
