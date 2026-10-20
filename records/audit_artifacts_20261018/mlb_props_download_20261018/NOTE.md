# Pointer — the whole file lives on another records branch

The chunked copy of the MLB Props Download artifact that was being
pushed into this folder was **stopped by owner direction** (Oct 19,
2026) after 5 of 376 chunks (`chunks/part-0001.csv` .. `part-0005.csv`)
had landed. Those commits are left as they stand — no history rewrite.
The partial chunks here are not the dataset and should not be read as
one.

The complete artifact is committed **whole** on branch
`records/mlb-props-artifact-20261019` @ `41f040ce` (zip sha256
`853e6b9d48db16269f7e270e561999158de81faac90bbc1d9121644bd6add0e1`,
the digest GitHub states for the artifact).

Close-check outcome (posted on #2409, Oct 19): in the enclosed
`mlb_props_targets.csv`, `ts` is a quote time — no quote falls after
`start_time`, and most selections carry several quotes, so the last
quote before first pitch is a real close; that question is settled.
Coverage, though, is only **4 games (March 22–31, 2026)** with hits
and strikeouts markets only and no total bases: the 200,000-row cap
cut the 645,149 scanned rows down to a few games. Hits and
strikeouts: **INSUFFICIENT_DATA**. Total bases: **market never
measured**. What unblocks the check is a new download with no row
cap, or filtered by date range so the rows cover many games.
