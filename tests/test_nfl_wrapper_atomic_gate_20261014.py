import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('wrapper_atomic', ROOT / 'scripts/run_nfl_auto_gated.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_child(monkeypatch, callback):
    class Loader:
        def exec_module(self, mod):
            mod.main = callback
    class Spec:
        loader = Loader()
    monkeypatch.setattr(importlib.util, 'spec_from_file_location', lambda *a, **k: Spec())
    monkeypatch.setattr(importlib.util, 'module_from_spec', lambda spec: type('Child', (), {})())


def test_default_output_is_gated_before_publication(tmp_path, monkeypatch):
    mod = load()
    monkeypatch.chdir(tmp_path)
    target = Path('artifacts/run_it/nfl_card.json')
    def child():
        staged = Path(sys.argv[sys.argv.index('--output') + 1])
        assert staged != target and not target.exists()
        staged.write_text(json.dumps({'rows': [{'market': 'ANYTIME_TD', 'model_p': .7}]}))
        assert not target.exists()
        return 0
    fake_child(monkeypatch, child)
    assert mod.main([]) == 0
    card = json.loads(target.read_text())
    assert 'model_p' not in card['rows'][0]
    assert card['registry_gate']['blocked'] == 1


def test_gate_failure_publishes_only_blocker(tmp_path, monkeypatch):
    mod = load()
    target = tmp_path / 'card.json'
    target.write_text('{"old": true}')
    def child():
        assert json.loads(target.read_text()) == {'old': True}
        staged = Path(sys.argv[sys.argv.index('--output') + 1])
        staged.write_text('{"rows":[{"market":"ANYTIME_TD","model_p":0.9}]}')
        return 0
    fake_child(monkeypatch, child)
    monkeypatch.setattr(mod, 'gate_output', lambda path: (_ for _ in ()).throw(OSError('denied')))
    assert mod.main(['--output=' + str(target)]) == 2
    assert json.loads(target.read_text()) == {'status': 'BLOCKED', 'blocker': 'REGISTRY_GATE_FAILED'}


def test_sidecar_uses_gated_runner_and_correct_default():
    text = (ROOT / 'scripts/emit_nfl_both_side_board.py').read_text()
    assert 'scripts/run_nfl_auto_gated.py' in text
    assert 'artifacts/run_it/nfl_card.json' in text
