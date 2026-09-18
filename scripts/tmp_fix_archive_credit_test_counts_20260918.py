from pathlib import Path

path = Path('tests/test_closing_line_archive.py')
text = path.read_text()
replacements = [
    (
        '        self.assertEqual(report["total_rows_written"], 8)',
        '        self.assertEqual(report["total_rows_written"], 6)',
        'ARCHIVE_8_ROW_EXPECTATION_MISSING',
    ),
    (
        '        self.assertEqual(report["total_rows_written"], 16)',
        '        self.assertEqual(report["total_rows_written"], 12)',
        'ARCHIVE_16_ROW_EXPECTATION_MISSING',
    ),
    (
        '        self.assertEqual(set(report["sports"]), {"NFL", "CFB", "MLB", "UFC"})',
        '        self.assertEqual(set(report["sports"]), {"NFL", "CFB", "UFC"})',
        'ARCHIVE_ACTIVE_SPORTS_EXPECTATION_MISSING',
    ),
]
for old, new, error in replacements:
    if old not in text:
        raise SystemExit(error)
    text = text.replace(old, new, 1)
path.write_text(text)
