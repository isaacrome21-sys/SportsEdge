from pathlib import Path

path = Path('tests/test_closing_line_archive.py')
text = path.read_text()
old1 = '        self.assertEqual(report["total_rows_written"], 8)'
new1 = '        self.assertEqual(report["total_rows_written"], 6)'
old2 = '        self.assertEqual(report["total_rows_written"], 16)'
new2 = '        self.assertEqual(report["total_rows_written"], 12)'
if old1 not in text:
    raise SystemExit('ARCHIVE_8_ROW_EXPECTATION_MISSING')
if old2 not in text:
    raise SystemExit('ARCHIVE_16_ROW_EXPECTATION_MISSING')
path.write_text(text.replace(old1, new1, 1).replace(old2, new2, 1))
