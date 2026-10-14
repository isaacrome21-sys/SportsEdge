import ast
from pathlib import Path
import unittest

from sportsedge.canonical_coverage import resolve_market


class InterceptionCoverageTests(unittest.TestCase):
    def test_quarterback_interception_alias_keeps_empirical_route(self):
        result = resolve_market('NFL', 'PLAYER_INTERCEPTIONS')
        self.assertEqual(result['market'], 'interceptions')
        self.assertEqual(result['state'], 'PRICED_PATH')

    def test_defensive_interceptions_remain_blocked(self):
        for name in ('DEFENSIVE_PLAYER_INTERCEPTIONS', 'player_interceptions'):
            with self.subTest(name=name):
                result = resolve_market('NFL', name)
                self.assertEqual(result['market'], 'player_interceptions')
                self.assertEqual(result['state'], 'BLOCKED')
                self.assertEqual(result['blocker'], 'NO_ENGINE')

    def test_alias_literals_have_no_silent_duplicate_keys(self):
        import sportsedge.canonical_coverage as coverage
        tree = ast.parse(Path(coverage.__file__).read_text())
        assignment = next(node for node in tree.body
                          if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name)
                                  and target.id == 'INTAKE_ALIASES'
                                  for target in node.targets))
        for dictionary in ast.walk(assignment.value):
            if isinstance(dictionary, ast.Dict):
                keys = [ast.literal_eval(key) for key in dictionary.keys]
                self.assertEqual(len(keys), len(set(keys)))


if __name__ == '__main__':
    unittest.main()
