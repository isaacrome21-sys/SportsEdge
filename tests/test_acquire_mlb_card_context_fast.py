from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts import acquire_mlb_card_context


class AcquireMlbCardContextFastTests(TestCase):
    def test_workers_fetch_all_games_and_preserve_artifacts(self):
        payload = {
            "games": [
                {"resolved_game": {"game_pk": 101}},
                {"resolved_game": {"game_pk": 202}},
                {"resolved_game": {"game_pk": 303}},
            ]
        }

        calls = []

        def fake_acquire(*, game_pk, as_of):
            calls.append(game_pk)
            return {
                "status": "OK",
                "payload_sha256": f"sha-{game_pk}",
                "game_pk": game_pk,
            }

        with TemporaryDirectory() as td:
            root = Path(td)
            engine = root / "engine.json"
            out = root / "ctx"
            engine.write_text(json.dumps(payload), encoding="utf-8")

            rc = acquire_mlb_card_context.main(
                [
                    "--engine-output",
                    str(engine),
                    "--out-dir",
                    str(out),
                    "--workers",
                    "3",
                ],
                acquire=fake_acquire,
            )

            self.assertEqual(rc, 0)
            self.assertCountEqual(calls, [101, 202, 303])
            for pk in (101, 202, 303):
                stored = json.loads((out / f"{pk}.json").read_text(encoding="utf-8"))
                self.assertEqual(stored["game_pk"], pk)
            self.assertEqual(
                json.loads((out / "failures.json").read_text(encoding="utf-8")),
                [],
            )

    def test_workers_reject_zero(self):
        with TemporaryDirectory() as td:
            engine = Path(td) / "engine.json"
            engine.write_text(json.dumps({"games": []}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                acquire_mlb_card_context.main(
                    ["--engine-output", str(engine), "--workers", "0"],
                    acquire=lambda **_: {},
                )


if __name__ == "__main__":
    import unittest

    unittest.main()
