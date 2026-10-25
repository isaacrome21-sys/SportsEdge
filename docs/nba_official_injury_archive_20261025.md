# NBA official injury PDF archive — research-only (2026-10-25)

This independent collector is the first piece of source-intake work tracked by #2647. Its purpose is **preserving official NBA injury-report releases with observed UTC receipt times**, not interpreting availability or pricing player props.

## Official source

- Season index: https://official.nba.com/nba-injury-report-2026-27-season/
- Official PDF host: https://ak-static.cms.nba.com/referee/injury/
- Observed 2026-10-24 example: `Injury-Report_2026-10-24_10_15PM.pdf`, containing an NBA injury report and statuses. Reports appear at many intervals throughout the day.
- Time in a PDF filename is only an **unverified provider filename hint**. It does not prove that a user or sportsbook could see the PDF at that time. Only a real, forward receipt proves when our process received it.

## Usage

Default invocation **does not make network requests, create directories or write data**:

```sh
python scripts/collect_nba_official_injury_reports.py
```

Explicit opt-in live capture for a specified Eastern date:

```sh
python scripts/collect_nba_official_injury_reports.py --live --date 2026-10-24 --output-dir captures/nba_official_injuries
```

The script fetches the official season index, accepts only matching HTTPS links on the official NBA static PDF host, chooses the latest named report for the requested date, validates the downloaded PDF magic and EOF marker, and saves:

- Raw bytes named by the date plus SHA256 digest, refusing to overwrite conflicting bytes.
- A distinct JSON observation receipt for each network capture: exact selected source URL, filename-time hint, the observed index/PDF UTC received-at times, raw hash/length/path, and negative admission flags.

The script refuses missing dates, malformed links, off-site links in the index, non-PDF bytes, oversized responses, corrupt existing archive files, and network failures. No quotas, credentials or paid calls are involved.

## Non-admission and remaining work

Every receipt declares `research_only=true`, `pricing_input=false`, `play_eligible=false`, `model_p=null`, `pit_available=false`, and `source_report_time_verified=false`. The raw PDF is **UNPARSED**.

Separate reviewable work is required to:

1. Extract player rows reliably across multiline PDF layouts (especially injury-reason wrapping) and retain the report's own team/game context.
2. Verify complete team/game coverage and canonical NBA player identities rather than assume omitted players are available.
3. Pair statuses and lineup projections to actual decision timestamps and game starts with a prospective as-of record; retain historical NO_PIT_EVIDENCE where no prior observation exists.
4. Confirm legal rights for automated use and any redistribution. The presence of publicly downloadable NBA PDFs is not an unrestricted data redistribution license.
5. Integrate with current NBA minute/rotation evidence only after separate independent validation; do not let NBA league-issued status and projected starting lineups become interchangeable.

No workflow is enabled by this PR. Nothing reads this collector in any pricing, grading, promotion, or betting path. Offline tests use synthetic HTML/PDF envelopes and cover allowlist enforcement, newest selection, bad dates/PDFs, immutable storage, and opt-in network safety. **Synthetic tests do not establish real-world source admission.**

## Related work

- Owner source integration tracker: #2647
- Owner full-repo chronological test mandate: #2637
- Concurrent NBA final score persistence draft: #2640
- Existing SportsEdge source and governance rules remain unchanged.
