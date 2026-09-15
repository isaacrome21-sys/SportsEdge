from pathlib import Path
import unittest


class ProviderCLIRequiredBookTests(unittest.TestCase):
    def test_cli_can_request_but_not_assume_exact_book(self):
        text = Path("scripts/run_free_mlb_game_markets.py").read_text()
        self.assertIn('p.add_argument("--required-book", default=None)', text)
        self.assertIn('required_book=args.required_book', text)


if __name__ == "__main__":
    unittest.main()
