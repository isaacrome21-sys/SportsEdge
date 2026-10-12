# umpscorecards.com Probe (2026-10-11)

X-account review item 1 (Bucket A). **Verdict: no keyless stable path —
documented and stopped. The umpire factor stays NOT_WIRED / MISSING.**

## Method (deliberately light: 4 requests total)

1. `GET /` — confirmed SvelteKit SPA shell.
2. `GET /robots.txt`, `/terms`, `/terms-of-use` — all return the SPA shell
   (no real robots.txt served; no terms page at standard paths).
3. `GET /_app/immutable/entry/app.Y20YjaoF.js` — frontend bundle; reveals the
   frontend data routes: `/data/umpires`, `/data/games`, `/data/pitchers`,
   `/data/batters`, `/data/catchers`, `/data/teams`.
4. `GET /data/umpires/__data.json` — SvelteKit load payload. **No umpire data:**
   the payload is `{"type":"data","nodes":[{...{"patreonStatus":1},
   {"signedIn":2,"tier":3,"accessLevel":4}...}, ...]}` — i.e. the umpire
   accuracy dataset sits behind Patreon sign-in/tier gating.

Recorded fixture: `tests/fixtures/umpscorecards_probe_20261011.json`
(test `test_umpscorecards_probe_fixture_documents_gate` pins this finding —
if the site ever opens a keyless path, the fixture and test must be
revisited).

## Why this kills the build (three independent reasons)

1. **No keyless stable API.** The frontend data path requires a Patreon
   session. Isaac's standing rules: no new signups, no paywalled sources.
2. **Pregame availability.** Even the gated data is post-game scorecards;
   a factor needs *pregame* umpire assignments, which MLB announces day-of
   via press release (see `UMPIRE_NOT_WIRED_REASON` in
   `sportsedge/free_factors.py`).
3. **Structural expiry (ABS).** MLB's automated ball-strike (ABS) challenge
   system, live in 2026, corrects called pitches on challenge — the umpire
   zone-effect is compressed by design. The factor stays MISSING until the
   harness proves a *residual* out-of-sample. No residual has been shown, so
   per the review item's critical caveat: do not over-invest.

## Registry state

- `mlb_umpire`: NOT_WIRED (unchanged; note updated with this probe).
- `umpire_zone` (Retrosheet-derived K/BB deltas): NOT_WIRED / MISSING until
  proven stable OOS. Deriving it from Retrosheet info records is Phase 2's
  documented validation path, but per the ABS caveat that build is deferred
  until someone shows a residual exists — it is *not* started here.
