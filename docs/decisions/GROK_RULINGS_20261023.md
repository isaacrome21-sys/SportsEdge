# Grok rulings recorded for the completion gap ledger (Oct 23, 2026 CT)

Recorded by Grok under the owner's delegation ("You make all rulings", Oct 22,
2026). No earlier repo record of these decisions existed; this file is that
record. Research-only; nothing here validates any family or grants play.

## ruling-6-focus-pause

Dated Oct 22, 2026. NHL attempt 2, NBA secondary props and MLB game-line
commissioning are paused until the first completed verdict review in NFL props
or NBA props (expected mid-to-late November 2026 at the earliest). In the
canonical MLB/NFL scope this pauses: F5_MONEYLINE, F5_RUN_LINE,
F5_TEAM_TOTALS, F5_TOTALS, NRFI, YRFI. NFL Part 2/2B, the ATD freeze package,
the passing-yards screen, NBA props V1/V2 and NBA team totals continue.

## owner-hold-either-pitcher-20261015

Dated Oct 15, 2026 (owner ruling, recorded here by Grok). EITHER_PITCHER
pricing (EITHER_PITCHER_BB, EITHER_PITCHER_ER, EITHER_PITCHER_HITS_ALLOWED)
stays refused until the underlying pitcher marginals are repaired. Matches the
gate EITHER_PITCHER_MARGINAL_TAIL_ERROR in sportsedge/canonical_coverage.py.

## MLB pitcher Infrastructure gaps are already covered (2026-10-23)

Grok ruling under owner t234u/t242u. PITCHER_K, PITCHER_BB, PITCHER_ER and
PITCHER_HITS_ALLOWED were listed as NO_FORWARD_TEST_CONFIG. All four are covered by the
committed, frozen one-shot study `docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md` (v2,
2026-10-04; DK PIT quote archive, run once after the 2026 postseason), and PITCHER_K also
by `config/research/mlb_pitcher_k_forward_validation_v1.json`
(FROZEN_BEFORE_FIRST_PROSPECTIVE_PREDICTION). `PROGRAM.md` already records "no duplicate
instruments" for this set. No new forward-test config is built; neither frozen instrument
is modified. Status COVERED_BY_COMMITTED_FROZEN_INSTRUMENT is structural only: no score
points, nothing validated, play_allowed false.

## Quarter spreads refused as moneyline-derivable (2026-10-23)

Grok ruling, Option 1, dated Oct 23, 2026, on the t248 NOT CLEARED finding. In
`sportsedge/nfl_period_lines_empirical.py` the quarter margin pmf is the public
history's pooled margin pmf moved by one shift. Any public quarter spread price (even
+/-1.5) plus that history pins the shift by bisection, and so rebuilds the refused
NAIVE_FAIL quarter moneyline exactly. Every Q1-Q4 spread is therefore refused with
`NAIVE_FAIL:Qn_MONEYLINE_DERIVABLE`; all quarter spreads were inconclusive versus naive
in the screens anyway, so no screen-supported market is lost. Public Q1-Q4 output carries
only identifiers, governance and refusal codes, plus the Q2 total and its `total_pmf`
(Q2_TOTAL was not refused); margin pmfs, team means and refused total pmfs are dropped.
H1/H2 are unchanged. Screens run through the guarded unrestricted path and reproduce
byte for byte. Test: `tests/test_nfl_period_lines_bisection_rebuild_20261023.py` runs
the bisection rebuild against every public output. Ledger: no status changes (its
quarter rows track the wired PERIOD_DERIVATIVE engine, not this screen engine). SCREEN /
NOT_VALIDATED, play_allowed false; nothing validated.

## DK-API workflows are manual-only (2026-10-23)

Grok ruling dated Oct 23, 2026, under owner delegation t234u, enforcing the owner's
invariant that DraftKings data comes from rendered pages only. Seven workflows import or
run a module that builds a DraftKings API URL (`/sites/US-SB/api`,
`sportsbook-nash.draftkings.com/api`): draftkings-prop-provider-probe,
mlb-prop-pit-archive, nfl-market-maker-radar-capture, mlb-moneyline-forward-evidence,
nfl-2026-line-capture, nfl-dk-direct-confirmation-capture and
sportsedge-auto-dk-four-sports. On six of them (all but the frozen nfl-2026-line-capture, see the exception below) the cron lines are deleted and the push,
pull_request (and, on mlb-moneyline-forward-evidence, workflow_run) triggers removed;
only workflow_dispatch remains. No source module is deleted and no collector was run.
Guard: `tests/test_dk_api_scheduled_workflow_guard_20261023.py`. Proposal branch
grok/t250-dk-api-guard-20261023; merging stays with the owner.

Exception, Grok ruling 2026-10-23c (frozen tests never change mid-clock; not relaxable):
`nfl-2026-line-capture` is a frozen confirmation lane. Its workflow,
`scripts/nfl_2026_line_capture.py` and `config/nfl_2026_capture.json` stay
byte-identical to main 53a636af, and so do `tests/test_nfl_2026_capture_contract.py`,
`tests/test_ws_credit_schedule_policy.py` and its entry in
`config/odds_api_request_projection_v3.json` (still scheduled). The DK guard lists it as
`FROZEN_LANE_EXCEPTION_OWNER_DECISION`: reported (it still reaches a DK API builder on
cron), not failed, until the owner decides. The market-provider frozen-exclusion gate
passes. The other six DK-API workflows stay manual-only.

## Auto-triggered DK-importing CI jobs classified (2026-10-23)

Grok ruling dated Oct 23, 2026, under t234u (DK rendered pages only). The
mlb-moneyline-forward-evidence `workflow_run` removal stands. Eleven further
auto-triggered workflows reach a DK-API module; each was classified by reading its code:

- Live DraftKings API request in CI, no mock: `direct-dk-market-archive-contract`
  (inline `fetch_board` probe on pull_request) and `dk-nba-nhl-category-probe`
  (`scripts/probe_dk_game_lines_categories.py` on push to main). Both are now
  workflow_dispatch-only.
- Import-only / fixtures or mocks, no DK network: `market-maker-radar`,
  `mlb-additional-odds-contract`, `mlb-additional-pit-archive` (its live archive job is
  already dispatch-only and uses the Odds API, not DK), `nfl-lines-issue` (DK dfs modules
  reached only via the `sportsedge.dfs` package import; it fetches ESPN/nflverse),
  `football-nfl-promotion-evidence`, `nfl-v2-nested-diagnostic`, `nfl-v2h-first-readout`,
  `nfl-v2i-first-readout`, `nfl-v2j-first-readout`. Triggers unchanged; guarded by
  `tests/test_dk_api_no_live_requests_in_ci_20261023.py`, which runs their DK-importing
  test modules with socket/urllib/requests patched to refuse any draftkings host.

`collection-runtime-contract` (pull_request) was added to the mock-guarded set: its
`tests/test_archive_mlb_prop_odds.py` patches `fetch_mlb_prop_quotes`, and its
`--self-test` is synthetic. The network guard refuses draftkings hosts at socket,
urllib, requests, subprocess curl/wget and os.system level, and the hosts' resolved IPs
where they resolve. The earlier projection-config edit for nfl-2026-line-capture is
reverted (ruling 2026-10-23c). No credits spent; no collector run.

## 2026-10-23d — DK no-live-request guard becomes a whole-process network jail (t258)

The t255 audit (CLEARED, LOW) found the curl/wget block matched command text only: a
child Python process, `openssl s_client`, `nc` and a percent-encoded host
(`api.%64raftkings.com`) got through, and the IP block was empty offline. Ruling: the
guard in `tests/test_dk_api_no_live_requests_in_ci_20261023.py` now blocks ALL non-loopback
network access for the test process and its children, not just DraftKings names:

- In process: `getaddrinfo`, `create_connection`, `socket.connect`/`connect_ex`/`sendto`
  refuse every non-loopback host or IP (`LIVE_NETWORK_BLOCKED`); DK names, including
  percent-encoded ones, still raise `LIVE_DK_REQUEST_BLOCKED`. No dependence on resolved IPs.
- Children: every child runs under `unshare -rn` (empty network namespace) where the runner
  allows it. Otherwise the fallback is a dead proxy (`*_PROXY=http://127.0.0.1:9`, empty
  `NO_PROXY`), `tests/net_jail/sitecustomize.py` on `PYTHONPATH` jailing every child Python
  (`-I`/`-E`/`-S` children are rewritten to load the jail first), and refusal of children that
  name a network binary (openssl, nc/ncat/netcat, socat, telnet, ssh, curl, wget, …) or `/dev/tcp`.
- Each audit bypass has a test, the bypass tests run in both modes, and every probe
  targets a non-DK host, so neither the RED run nor CI ever contacts DraftKings.

Frozen lane files (`nfl-2026-line-capture.yml`, its tests and config) stay byte-identical
to main 53a636af. Residual: a non-Python child that opens raw sockets under an obfuscated
binary name is caught only when the namespace jail is available. Not self-cleared; needs
independent review.

## 2026-10-23e — network jail re-execs the guarded session under `unshare -rn` (t259)

The t258 audit (NOT CLEARED on 7b099d35) found four bypasses: (1) `_socket.socket().connect`;
(2) `importlib.reload(socket)` then `create_connection`; (3) `os.posix_spawn` of curl, which
skips the subprocess wrapper; (4) in fallback mode, a renamed curl run with `--noproxy '*'`.
Ruling:

- Layer 1 (isolation): `tests/net_jail/run_jailed.py` re-launches pytest under `unshare -rn`
  (loopback brought up, `/proc/net/dev` must show only `lo`, `SPORTSEDGE_NET_JAILED=1`).
  The `net_jail` fixture re-runs the module's live bypass tests once in that jailed session
  and requires each to pass there; inside the jail it re-checks the interface list, so the
  env var alone cannot fake isolation. In-process tricks have no route out.
- Without unshare the live bypass tests SKIP with `NET_JAIL_UNAVAILABLE`; they never claim
  isolation, and the wrapper exits 3 with the same marker.
- Layer 2 (in-process): `_socket.socket`/`SocketType`/`getaddrinfo` are patched (also covers a
  reloaded `socket`), and `os.posix_spawn`/`posix_spawnp`, `os.spawn*` and `os.exec*` refuse
  network binaries and DK commands. Network binaries are also identified by file content, so a
  renamed copy of curl is refused.
- One test per bypass, run both jailed and in-process; probes target example.com only, never DK.

The frozen lane stays byte-identical to main 53a636af. Residual: the layer-2 patches stop
mistakes, not a determined in-process attacker (e.g. ctypes syscalls); only layer 1 is isolation,
and it exists only where unshare is permitted. Not self-cleared; needs independent review.

## 2026-10-23f — session-wide network audit hook (t260)

The t259 audit (NOT CLEARED on b16ff0f5) found in-process routes to the unpatched C socket
type: `socket.socket.__bases__[0]().connect`, `_socket.socket.__mro__[1]()`, and ctypes
`connect`. Ruling:

- `tests/net_jail/audit_hook.py` registers one `sys.addaudithook` at session start
  (`tests/conftest.py` `pytest_configure`). It handles `socket.connect`, `socket.getaddrinfo`,
  `socket.sendto`, `socket.bind` (non-loopback; `0.0.0.0`/`""` counts as non-loopback),
  `subprocess.Popen`, `os.posix_spawn`, `os.exec` and `os.spawn` (network-binary, renamed
  network-binary-by-content and DK checks). Audit hooks cannot be removed, so it is gated by a
  session flag checked inside the hook; it is active only while the `dk_block` guard (or an
  explicit `active()` block) is in force and is a no-op for every other test.
- Because the events fire inside C, the `__bases__[0]`, `__mro__[1]`, fresh-`_socket`
  getaddrinfo, reload(socket), `posix.posix_spawn` and un-wrapped Popen routes are refused.
  One test per route, all probing example.com only.
- Layer 1 (`unshare -rn` re-exec, t259) is unchanged and remains the only real isolation.

Documented residuals:

- **ctypes / raw syscalls:** `ctypes` calls to libc `socket`/`connect` (or any foreign code)
  raise no audit event and bypass layers 2 and 3. Only the `unshare -rn` jail contains them;
  where unshare is unavailable the live tests skip with `NET_JAIL_UNAVAILABLE`.
- **Unix sockets at filesystem paths:** AF_UNIX connects/binds (e.g. `/var/run/docker.sock`,
  a local proxy socket) are not refused by the hook and are not removed by a network
  namespace, so a local daemon could relay traffic out. Not claimed as blocked.
- **Pre-hook DNS:** for a hostname, C resolves the name before `socket.connect`/`sendto` fire
  their audit event, so outside the jail one DNS query for the probe host can leave before the
  refusal. No TCP/UDP payload reaches the host.

Frozen lane files stay byte-identical to main 53a636af. Not self-cleared; needs independent review.
