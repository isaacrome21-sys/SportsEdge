# OddsPapi live multi-book research intake

`scripts/collect_oddspapi_live_multibook.py` provides an optional, deliberately
budgeted alternative to the existing The Odds API DraftKings four-sport collector.

## Defaults and examples

The first command performs **zero network requests** and consumes zero credits:

```bash
python3 scripts/collect_oddspapi_live_multibook.py \
  --fixture-id id1000003969653792
```

A live research snapshot requires an explicitly chosen fixture and paid-call cap:

```bash
export SPORTSEDGE_ODDSPAPI_KEY="(configure in the deployment secret store)"
python3 scripts/collect_oddspapi_live_multibook.py \
  --fixture-id id1000003969653792 \
  --bookmakers draftkings,pinnacle,fanduel \
  --max-billable 1 \
  --reserve 25 \
  --out-dir artifacts/oddspapi_live
```

The example fixture ID is from the provider's API documentation, **not** a
verified upcoming game. Replace it with an actual future OddsPapi fixture ID
obtained through the sanctioned fixtures catalog. No sportsbook login, HTML
scraping, CAPTCHA workaround, or implicit paid fixture discovery is used.
Do not put keys in arguments, chat, Git, or artifact files.

**Charge policy:** `/v4/odds` costs one request even when a fixture is empty or
errors. `/v4/account` is free. Before **each** odds request, the collector
checks the active subscription's `request_limit` and `request_count` and
requires at least 25 calls remain in reserve *after* the proposed spend.
Two fixture IDs need `--max-billable 2` or more. A failed, unknown, or
ambiguous account/quota state blocks calls. Plan requests across workers to
avoid simultaneous budget races; this job is designed for one serialized lane.

**What is saved:** One JSON file per fixture, containing the unchanged provider
fixture response and a separate normalized research-only projection of **paired
numeric-line OVER/UNDER quotes**. For each matched pair the output retains:
bookmaker slug; opaque provider market, player, and outcome IDs; exact line;
both American prices; both independent source timestamps; an indicative market
no-vig reference (never a model probability); and a disabled PLAY field.
Provider fields `changedAt` and `bookmakerChangedAt` are not intake times,
and both must be fresh and nonfuture within 180 seconds when present.

Only outcomes with a documented `<line>/over` or `<line>/under` format are
paired. Other bookmaker markets, including moneylines, spreads, team totals,
and ambiguous prop IDs, **remain available in raw snapshots** for explicit
catalog admission/mapping. They are NOT silently treated as recognized lines.
Fixture identity must agree, event must be pregame, and missing/duplicate
opposites or suspended markets fail closed. No raw record is retroactively
counted toward a forward betting test.

## Workflow boundaries

- Existing automatic DK + peers route: `scripts/collect_auto_dk_four_sports.py`;
  the proposed freshness fix is reviewed independently in PR #2509.
- OddsPapi fallback is **research/archive only**, not a replacement for the
  frozen ATD, NBA, NFL or team-total evaluators.
- Raw odds and no-vig market context do not imply a model has beaten the market.
  No automatic `PLAY`, confidence 99, or score uplift is granted.
- This adapter makes no live calls during unit tests. Tests inject an offline
  transport and test the exact paid-call counting, quota refusal and pairing.

Provider specifications:
- https://oddspapi.io/en/docs/get-odds
- https://oddspapi.io/en/docs/get-account
- https://oddspapi.io/en/docs/requests-and-quota
