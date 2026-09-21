# Manual line intake

Odds API is not used. Quotes enter as pasted two-sided lines or JSON under `manual_inputs/`.

Parser: `sportsedge.manual_line_paste.parse_manual_line_paste`.

Example:

```text
NFL 2026-09-21 DK retrieved_at=2026-09-21T10:40:00-05:00
KC @ NYJ
  ML   KC -185 / NYJ +155
  spread KC -3.5 -110 / NYJ +3.5 -110
  total  43.5  over -108 / under -112
```

Rules:
- both sides required
- timezone on `retrieved_at` required
- output is quotes only
- footer remains `NOT Model_P / NOT Truth Gate / NOT OFFICIAL`
