"""Freeze serialization regressions; constructed fixtures are not fit evidence."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.build_nfl_prop_model_artifact import main, _write
from sportsedge.football_prop_run_machine import canonical_hash, FootballPropRunError


class NFLPropFreezeSerializationTests(unittest.TestCase):
    def test_staging_directory_does_not_change_declared_freeze(self):
        artifact = {
            'artifact_version': 'UNIT_TEST_ONLY',
            'source_manifest_sha256': 'a' * 64,
            'nested': {'z': 0.125, 'a': 'é'},
        }
        with TemporaryDirectory() as temp:
            outputs = []
            for name in ('attempt_a', 'attempt_b'):
                root = Path(temp) / name
                args = [
                    'build_nfl_prop_model_artifact.py', '--pbp', 'fixture.csv',
                    '--git-sha', 'b' * 40, '--artifact-version', 'UNIT_TEST_ONLY',
                    '--output', str(root / 'model.json'),
                    '--diagnostics-output', str(root / 'diagnostics.json'),
                    '--freeze-output', str(root / 'freeze.json'),
                    '--artifact-path', 'artifacts/football/nfl_offensive_prop_ab_model.json',
                ]
                with patch('sys.argv', args), patch(
                    'scripts.build_nfl_prop_model_artifact.fit_nfl_prop_artifact',
                    return_value=(deepcopy(artifact), {'status': 'FIXTURE', 'team_count': 0}),
                ), redirect_stdout(StringIO()):
                    self.assertEqual(main(), 0)
                outputs.append(root)
            for name in ('model.json', 'diagnostics.json', 'freeze.json'):
                self.assertEqual((outputs[0] / name).read_bytes(), (outputs[1] / name).read_bytes())
            freeze = json.loads((outputs[0] / 'freeze.json').read_bytes())
            self.assertEqual(freeze['artifact_sha256'], canonical_hash(artifact))
            self.assertFalse(freeze['promotion_authority'])

    def test_dictionary_order_and_json_roundtrip_preserve_hash(self):
        first = {'z': [0.125, -0.0, 1e-12], 'a': {'é': 'text', 'b': 2}}
        second = {'a': {'b': 2, 'é': 'text'}, 'z': [0.125, -0.0, 1e-12]}
        self.assertEqual(canonical_hash(first), canonical_hash(second))
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'model.json'
            _write(path, first)
            self.assertEqual(canonical_hash(json.loads(path.read_bytes())), canonical_hash(first))

    def test_nonfinite_values_never_reach_disk(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'model.json'
            for value in (float('nan'), float('inf'), float('-inf')):
                with self.subTest(value=value), self.assertRaises(FootballPropRunError):
                    _write(path, {'rate': value})
                self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
