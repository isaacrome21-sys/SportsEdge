# Preservation note — RUN IT 2026-10-13

These artifacts were committed and pushed to branch `records/run-it-20261013` on 2026-10-13 (morning CT), BEFORE the day's kickoffs (Delaware@MTSU 23:00Z; CLE@TB and FIU@JSU 2026-10-14T00:00Z), so the GitHub server-side commit record independently timestamps their existence. Grading appends to the pregame records in the workspace; it never edits the files preserved here.

- `MANIFEST_20261013.md` — the hash manifest binding the card JSONs and records (created 2026-10-13T10:22:41Z).
- `20261013_CLE_TB_pregame_record.md`, `20261013_CFB_pregame_record.md` — the pregame records, byte-identical to the manifest hashes (be03f084… / 5b0d57ae…).
- `dk_mlb_refresh.txt`, `dk_cfb_refresh.txt` — raw DraftKings board read notes (quote observations at 10:04Z / 10:08Z).
- `run_canonical.py`, `run_supp.py` — the exact intake drivers that produced the cards.
- `cards_archive.tar.gz.b64` — base64 of a tar.gz containing the three card JSONs (card_mlb_canonical.json, card_cfb_canonical.json, card_mlb_supp.json). Archive SHA-256: 89aec786d9f81a2bb3e49701d0f7d28acdf40616f7054ef5bb6b341bcbe0d30a. Extract with: `base64 -d cards_archive.tar.gz.b64 | tar -xz` — each member's SHA-256 must match the manifest (d48bb6f7… / 7f018b4f… / 5ed08664…).
