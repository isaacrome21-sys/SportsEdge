# Pick-Card Style Brief (durable — for the future renderer rebuild)

Adopted Oct 11, 2026 from the 4-account X research (see
`~/workspace/sportsedge/x_accounts_penguin_corbie_myspariedge.md`, section B).
Style reference: Penguin's "The Penguin Card" — "Pixar meets Vegas sportsbook".
Do NOT rebuild the renderer until scheduled; when rebuilt, follow this brief.

## Naming and anchor
- Named card format: **"The Edge Card"** (mirrors "The Penguin Card").
- Mascot anchor: a single recognizable mascot graphic reused on every card
  (their penguin; ours TBD — one mascot, kept consistent, recognizable small).
- Every card timestamped (`as of <UTC>`); plays are per-card, never recycled.

## Visual direction
- Glossy, maximalist sportsbook aesthetic: hyper-saturated palette —
  hot magenta/purple, electric green, gold, deep navy.
- Card background/banner: stylized celebration scene (theirs: cartoon penguins
  in neon jerseys in a neon sportsbook, glowing odds boards, confetti).
- Typography: heavy rounded bold headlines; casual body text.
- Numbers ALWAYS with units ("EV +3.1%", "52.4% model", never bare "+3.1").

## Per-play structure
- Each play as an emoji-bulleted block (emoji as structural bullets, not noise):
  - play line FIRST: `🏷 (TIME) Player/team + market + line + price`
  - then `→ model NN% → EV ±NN%` — probability stated BEFORE any status word.
  - 2–4 short dash-bullet reasons (casual tone; derived only from verified
    inputs, never invented narratives).
  - status/uncertainty flags after the EV (e.g. WATCH: quote stale).
- Plays stacked, ranked by EV. A zero-edge card renders the same format with
  an explicit "NO EDGES TODAY" block — never padded, never hidden.

## Tally posts
- Stacked result tallies allowed ONLY on the paper ledger: month-by-month,
  red months shown, every profit figure next to its units-risked denominator.
- Every tally labeled **HYPOTHETICAL / RESEARCH ONLY — no bets placed**.

## NEVER (hard lines, even in graphics)
- No streak-brag framing ("10-0 🔥", heaters, win-rate hype) — ever.
- No unverifiable unit claims ("+102u last 32 days") — paper units only, with
  the denominator shown and red months included.
- No black-box marketing ("10,000 simulations", "best model") — calibration
  evidence or silence.
- No "pick" framing that implies staking authority — research output only.
- Never present the tally as actual betting results.
