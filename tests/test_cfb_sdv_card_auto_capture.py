import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cfb_card_v2_autocap", ROOT / "scripts" / "run_cfb_sdv_card_v2.py")
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)


class AutoCaptureTest(unittest.TestCase):
    def test_success_returns_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "live"

            def fake_capture(directory):
                Path(directory).mkdir(parents=True)
                (Path(directory) / "receipt.json").write_text("{}")

            self.assertEqual(card._auto_capture_sdv_live(target, capture=fake_capture), target)

    def test_failure_falls_back_to_none(self):
        def failing_capture(directory):
            raise OSError("network down")

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(card._auto_capture_sdv_live(Path(tmp) / "live", capture=failing_capture))

    def test_capture_that_writes_nothing_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(card._auto_capture_sdv_live(Path(tmp) / "live", capture=lambda d: None))


if __name__ == "__main__":
    unittest.main()
