#!/usr/bin/env python3
"""PGA H2H Leg 1 screen executor — design §4/§6, Amendment 1 reference (b′).

Implements the machinery of the PGA Tour tournament-matchups design of
record (research/new_sports_designs_20261027/
PGA_H2H_MATCHUPS_DESIGN_PREREG_DRAFT.md) and its Amendment 1 DRAFT
(reference (b′): Bradley–Terry on per-event owgr_rank, PR #2896):

  * corpus loading from the G-PGA-2 extracted-content store with pin
    verification (per-event content hashes + corpus hash);
  * point-in-time feature machinery under design §5: a FeatureWindow
    that can only see events strictly before the target event, and
    composite (event_id, year) identity everywhere;
  * the §4 construction: trailing-24-month, 6-month-half-life,
    shrinkage-weighted SG skill (UNPRICED below 40 measured rounds),
    hard-shrunk same-event course history, per-player residual
    round-score SD floored/capped at the field's 10th/90th percentiles,
    and a seeded field simulation with a simulated cut;
  * reference (a): pairwise probabilities implied by the outright Close
    odds, field-normalized;
  * reference (b′): exactly Amendment 1 §3.2 — strength r^(−α), α by
    maximum likelihood (golden-section, bracket [0.01, 2.00], tolerance
    1e-6) over decided both-valid-rank pairs in the §6 fit window;
  * scoring: log loss conditional on a non-tied finish (design §4.4
    convention), calibration error over probability deciles, per-season
    matchup volume;
  * the verdict path (run_leg1) behind three gates — Amendment 1
    adoption, content-pin admission, and pinned design parameters. No
    artifact in existence today can pass the first two gates, so the
    verdict path refuses by construction and stamps the run record
    PRE_ADOPTION_CHECK / NOT_EXECUTABLE. The landing check
    (run_landing_check.py) exercises the plumbing and records the
    refusal; it produces NO verdict and NO criterion results.

Consumed fields are declared in CONSUMED_ROW_FIELDS. The extracted
records' "excluded" object (dg_pts — DISQUALIFIED as lookahead by
Amendment 1 §3.1 — and dg_rank) is dropped at load and is never read
by any code path in this module.

Where the design text leaves a constant or a form unpinned, this
module does not invent one silently: the value is either a required
ExecutorConfig field with no default (the verdict path refuses while
it is unpinned) or a named reading in READINGS_REGISTER.md, flagged
for the adoption/freeze review.

Stdlib only. Deterministic: seeded RNG, golden-section search, sorted
iteration orders everywhere.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

EXECUTOR_VERSION = "PGA_H2H_EXECUTOR_V1"

# The complete set of extracted row fields this executor reads. The
# admission packet's "excluded" fields (dg_pts, dg_rank) are absent by
# construction; a family test audits this declaration against the code.
CONSUMED_ROW_FIELDS = frozenset(
    {"dg_id", "player_name", "fin", "total", "rounds", "open", "close", "owgr_rank"}
)

MIN_MEASURED_ROUNDS = 40  # design §4.1: below this a player is UNPRICED
WINDOW_MONTHS = 24  # design §4.1: trailing 24 months
HALF_LIFE_MONTHS = 6.0  # design §4.1: recency half-life
COURSE_PRIOR_ROUNDS = 8.0  # design §4.2: prior weight equivalent to 8 rounds
DESIGN_SIM_COUNT = 100_000  # design §4.4: simulated events per test event
ALPHA_BRACKET = (0.01, 2.00)  # Amendment 1 §3.2 step 4
ALPHA_TOL = 1e-6  # Amendment 1 §3.2 step 4
TEST_SEASONS = (2023, 2024, 2025)  # design §6 Leg 1 chronology
FIT_WINDOW_MAX_SEASON = {2023: 2022, 2024: 2023, 2025: 2024}  # design §6
VOLUME_FLOOR_PER_SEASON = 1500  # design §6 criterion 4
CALIBRATION_MAX = 0.05  # design §6 criterion 3
_DAYS_PER_MONTH = 30.4375  # mean month; READINGS_REGISTER R-SKILL-2


class PITViolation(Exception):
    """Raised when feature machinery is asked to touch an event that is
    not strictly before the target event (design §5)."""


class ScreenRefusal(Exception):
    """The verdict path's refusal. Carries the run-record stamps and the
    named reasons; the verdict is always NOT_EXECUTABLE."""

    def __init__(self, reasons):
        self.verdict = "NOT_EXECUTABLE"
        self.stamps = ["PRE_ADOPTION_CHECK"]
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


# ---------------------------------------------------------------- corpus


@dataclass
class PlayerRow:
    dg_id: int
    player_name: str
    fin: object
    total: object
    rounds: list  # [{r, score, par, sg}] — only rounds present on the page
    open: object
    close: object
    owgr_rank: object


@dataclass
class Event:
    event_id: str
    calendar_year: int
    season: int
    day: date
    name: str
    rows: list

    @property
    def key(self):
        """Composite (event_id, year) identity — design §5. Event_id
        alone is never an identity in this module."""
        return (self.event_id, self.calendar_year)


@dataclass
class Corpus:
    events: list  # sorted by (day, event_id)
    corpus_sha256: str
    manifest_status: str


def _row_from_content(raw: dict) -> PlayerRow:
    # The loader reads exactly CONSUMED_ROW_FIELDS; the extracted
    # record's "excluded" object is dropped here and never consulted.
    return PlayerRow(
        dg_id=raw["dg_id"],
        player_name=raw["player_name"],
        fin=raw["fin"],
        total=raw["total"],
        rounds=raw["rounds"],
        open=raw["open"],
        close=raw["close"],
        owgr_rank=raw["owgr_rank"],
    )


def load_corpus(extracted_dir: str, manifest: dict) -> Corpus:
    """Load the extracted-content store, verifying every event file
    against the manifest's content pin and the corpus hash."""
    entries = manifest["events"]
    lines = []
    events = []
    for e in sorted(entries, key=lambda x: (x["date"], x["event_id"])):
        path = os.path.join(extracted_dir, e["content_file"])
        with open(path, "rb") as f:
            body = f.read()
        digest = hashlib.sha256(body).hexdigest()
        if digest != e["content_sha256"]:
            raise ValueError(
                f"content pin mismatch for {e['content_file']}: "
                f"{digest} != {e['content_sha256']}"
            )
        lines.append(f"{e['event_id']}|{e['date']}|{e['content_sha256']}")
        content = json.loads(body.decode("utf-8"))
        events.append(
            Event(
                event_id=content["event_id"],
                calendar_year=content["calendar_year"],
                season=content["season"],
                day=date.fromisoformat(content["date"]),
                name=content["name"],
                rows=[_row_from_content(r) for r in content["rows"]],
            )
        )
    corpus_digest = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
    if corpus_digest != manifest["corpus_sha256"]:
        raise ValueError("corpus hash mismatch against manifest")
    events.sort(key=lambda ev: (ev.day, ev.event_id))
    return Corpus(
        events=events,
        corpus_sha256=corpus_digest,
        manifest_status=manifest.get("status", ""),
    )


# ---------------------------------------------------------------- outcomes


def parse_finish(fin):
    """Finish -> (group, position). Groups: 0 = numeric finish
    (T-prefixed included), 1 = MDF (made cut, did not finish),
    2 = CUT, 3 = no decided standing (WD / DQ / anything else).
    READINGS_REGISTER R-OUT-1."""
    if isinstance(fin, str):
        s = fin.strip()
        if s.startswith("T"):
            s = s[1:]
        if s.isdigit():
            return (0, int(s))
        if fin == "MDF":
            return (1, None)
        if fin == "CUT":
            return (2, None)
    return (3, None)


def decided_pair(fin_a, fin_b):
    """+1 if a finished ahead of b, -1 if behind, 0 for a tie,
    None when the pair has no decided finish (either side group 3,
    or an equal standing)."""
    ga, pa = parse_finish(fin_a)
    gb, pb = parse_finish(fin_b)
    if ga == 3 or gb == 3:
        return None
    if ga != gb:
        return 1 if ga < gb else -1
    if ga == 0:
        if pa == pb:
            return 0
        return 1 if pa < pb else -1
    return 0


# ---------------------------------------------------------------- PIT window


def _minus_months(d: date, months: int) -> date:
    y = d.year - (months // 12)
    m = d.month - (months % 12)
    if m <= 0:
        y -= 1
        m += 12
    # clamp the day to the target month's length
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    last_day = (nxt - timedelta(days=1)).day
    return date(y, m, min(d.day, last_day))


@dataclass
class FeatureWindow:
    """The only door feature code has to the corpus for a target event.
    It yields strictly-prior events only; asking it for the target
    itself or a later event raises PITViolation."""

    corpus: Corpus
    target: Event
    _prior: list = field(default=None)
    _index: dict = field(default=None)

    def prior_events(self):
        if self._prior is None:
            self._prior = [e for e in self.corpus.events if e.day < self.target.day]
        return self._prior

    def get_event(self, event: Event) -> Event:
        if event.day >= self.target.day:
            raise PITViolation(
                f"event {event.key} on {event.day} is not strictly before "
                f"target {self.target.key} on {self.target.day}"
            )
        return event

    def round_records(self):
        """Index of the window: per-player chronological round records
        from prior events inside the trailing 24 months, plus the
        field's decay-weighted SG mean over the same records."""
        if self._index is not None:
            return self._index
        cutoff = _minus_months(self.target.day, WINDOW_MONTHS)
        per_player = {}
        w_sum = 0.0
        w_sg = 0.0
        for ev in self.prior_events():
            if ev.day < cutoff:
                continue
            age_months = (self.target.day - ev.day).days / _DAYS_PER_MONTH
            w = 0.5 ** (age_months / HALF_LIFE_MONTHS)
            for row in ev.rows:
                for rnd in row.rounds:
                    per_player.setdefault(row.dg_id, []).append(
                        {
                            "day": ev.day,
                            "event_id": ev.event_id,
                            "sg": rnd.get("sg"),
                            "score": rnd.get("score"),
                            "weight": w,
                        }
                    )
                    if rnd.get("sg") is not None:
                        w_sum += w
                        w_sg += w * rnd["sg"]
        self._index = {
            "per_player": per_player,
            "field_mean_sg": (w_sg / w_sum) if w_sum > 0 else 0.0,
        }
        return self._index


# ---------------------------------------------------------------- construction


@dataclass
class ExecutorConfig:
    """Design parameters. The first three are NOT pinned by the design
    text (see READINGS_REGISTER): they have no defaults, and the
    verdict path refuses while any is None. Landing checks supply
    explicitly labeled PLUMBING_ONLY values."""

    shrinkage_prior_rounds: float = None  # §4.1 shrink strength — unpinned
    cut_size: int = None  # §4.4 simulated cut size — unpinned
    day_draw_sd: float = None  # §4.3 shared course-day draw SD — unpinned
    n_sims: int = DESIGN_SIM_COUNT
    design_sim_count: int = DESIGN_SIM_COUNT
    seed: int = None


@dataclass
class PlayerPrice:
    dg_id: int
    skill: float
    course_adj: float
    sd: float
    n_rounds: int

    @property
    def mu(self):
        return self.skill + self.course_adj


def _percentile(sorted_vals, pct):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_vals[int(rank)]
    frac = rank - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _player_sd(records):
    scores = [r["score"] for r in records if r["score"] is not None]
    if len(scores) < 2:
        return None
    mu = sum(scores) / len(scores)
    return math.sqrt(sum((s - mu) ** 2 for s in scores) / len(scores))


def price_field(window: FeatureWindow, config: ExecutorConfig):
    """Price the target event's field under design §4. Returns
    {dg_id: PlayerPrice} for priced players only; players under the
    40-measured-round floor are UNPRICED (absent, never defaulted)."""
    if config.shrinkage_prior_rounds is None:
        raise ScreenRefusal(["UNPINNED_DESIGN_PARAMETER:shrinkage_prior_rounds"])
    idx = window.round_records()
    per_player = idx["per_player"]
    field_mean = idx["field_mean_sg"]

    # Field SD bounds over the priceable population (READINGS R-VAR-2).
    sds = []
    for dg_id, records in per_player.items():
        n_sg = sum(1 for r in records if r["sg"] is not None)
        if n_sg >= MIN_MEASURED_ROUNDS:
            sd = _player_sd(records)
            if sd is not None:
                sds.append(sd)
    sds.sort()
    sd_floor = _percentile(sds, 10)
    sd_cap = _percentile(sds, 90)

    prices = {}
    for row in window.target.rows:
        records = per_player.get(row.dg_id, [])
        sg_records = [r for r in records if r["sg"] is not None]
        n = len(sg_records)
        if n < MIN_MEASURED_ROUNDS:
            continue  # UNPRICED
        w_sum = sum(r["weight"] for r in sg_records)
        w_sg = sum(r["weight"] * r["sg"] for r in sg_records)
        k = config.shrinkage_prior_rounds
        skill = (w_sg + k * field_mean) / (w_sum + k)
        # Course fit: prior editions of this same event (same event_id,
        # strictly prior dates by window construction), >= 2 editions,
        # shrunk with an 8-round prior weight (§4.2; READINGS R-COURSE-1).
        course_adj = 0.0
        ev_records = [r for r in records if r["event_id"] == window.target.event_id]
        if len({r["day"] for r in ev_records}) >= 2:
            ev_sgs = [r["sg"] for r in ev_records if r["sg"] is not None]
            if ev_sgs:
                course_adj = (len(ev_sgs) / (len(ev_sgs) + COURSE_PRIOR_ROUNDS)) * (
                    sum(ev_sgs) / len(ev_sgs)
                )
        sd = _player_sd(records)
        if sd is None:
            continue
        sd = min(max(sd, sd_floor), sd_cap)
        prices[row.dg_id] = PlayerPrice(
            dg_id=row.dg_id, skill=skill, course_adj=course_adj, sd=sd, n_rounds=n
        )
    return prices


def simulate_event(prices: dict, config: ExecutorConfig, rng: random.Random):
    """Simulate the event; return {(i, j): (ahead, behind, tie)} counts
    over unordered pairs (i < j by dg_id), where 'ahead' counts i
    finishing ahead of j. Performance is simulated in SG space
    (READINGS R-SIM-1): each round a player draws
    Normal(mu, sd) plus a shared course-day draw; after R2 the
    simulated cut keeps the top config.cut_size (ties at the line
    survive); non-survivors rank below all survivors, ordered by their
    R1+R2 performance."""
    if config.cut_size is None:
        raise ScreenRefusal(["UNPINNED_DESIGN_PARAMETER:cut_size"])
    if config.day_draw_sd is None:
        raise ScreenRefusal(["UNPINNED_DESIGN_PARAMETER:day_draw_sd"])
    ids = sorted(prices)
    counts = {pair: [0, 0, 0] for pair in itertools.combinations(ids, 2)}
    for _ in range(config.n_sims):
        day = [rng.gauss(0.0, config.day_draw_sd) for _ in range(4)]
        perf = {}
        for dg in ids:
            p = prices[dg]
            perf[dg] = [rng.gauss(p.mu, p.sd) + day[r] for r in range(4)]
        cum2 = {dg: perf[dg][0] + perf[dg][1] for dg in ids}
        ranked2 = sorted(ids, key=lambda dg: (-cum2[dg], dg))
        if len(ranked2) > config.cut_size:
            line = cum2[ranked2[config.cut_size - 1]]
            survivors = {dg for dg in ids if cum2[dg] >= line}
        else:
            survivors = set(ids)
        total = {dg: sum(perf[dg]) for dg in survivors}

        def finish_key(dg):
            if dg in survivors:
                return (0, -total[dg])
            return (1, -cum2[dg])

        for i, j in itertools.combinations(ids, 2):
            ki, kj = finish_key(i), finish_key(j)
            if ki < kj:
                counts[(i, j)][0] += 1
            elif ki > kj:
                counts[(i, j)][1] += 1
            else:
                counts[(i, j)][2] += 1
    return counts


def conditional_probs(counts):
    """{(i, j): P(i ahead | non-tied finish)} — design §4.4's priced
    comparison; pairs with no decided simulation are absent."""
    out = {}
    for pair, (a, b, _t) in counts.items():
        if a + b > 0:
            out[pair] = a / (a + b)
    return out


# ---------------------------------------------------------------- reference (a)


def valid_close(close) -> bool:
    return isinstance(close, (int, float)) and close not in (-9999.0,) and close > 1.0


def ref_a_probs(event: Event):
    """Field-normalized outright-Close implied probabilities
    (READINGS R-REFA-1): q_i = (1/close_i) / sum_j(1/close_j) over
    rows with a valid close; pairwise P(i ahead of j) = q_i/(q_i+q_j)."""
    raw = {}
    for row in event.rows:
        if valid_close(row.close):
            raw[row.dg_id] = 1.0 / row.close
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {dg: q / total for dg, q in raw.items()}


def ref_a_pair(probs: dict, i: int, j: int):
    if i not in probs or j not in probs:
        return None
    return probs[i] / (probs[i] + probs[j])


# ---------------------------------------------------------------- reference (b′)


def valid_rank(v) -> bool:
    """Amendment 1 §3.2 step 1: a rank is valid iff it is an integer >= 1
    (the corpus's only invalid values are the -9999/-9998 sentinels)."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def bt_prob(rank_i, rank_j, alpha: float) -> float:
    """Amendment 1 §3.2 step 3: P(i ahead of j) = r_j^α / (r_i^α + r_j^α)."""
    si = rank_i ** (-alpha)
    sj = rank_j ** (-alpha)
    return si / (si + sj)


def collect_bt_pairs(events):
    """Decided pairs with both ranks valid, as (winner_rank, loser_rank)
    — the accumulation Amendment 1 §3.2 step 4 fits α over."""
    pairs = []
    for ev in events:
        ranked = [r for r in ev.rows if valid_rank(r.owgr_rank)]
        for a, b in itertools.combinations(ranked, 2):
            d = decided_pair(a.fin, b.fin)
            if d == 1:
                pairs.append((a.owgr_rank, b.owgr_rank))
            elif d == -1:
                pairs.append((b.owgr_rank, a.owgr_rank))
    return pairs


def fit_alpha(pairs) -> float:
    """Maximum-likelihood α over [0.01, 2.00] by golden-section search
    until the bracket is narrower than 1e-6 (Amendment 1 §3.2 step 4).
    Deterministic. Raises ValueError on an empty pair set."""
    if not pairs:
        raise ValueError("no decided both-valid-rank pairs to fit alpha")

    def loglik(alpha):
        total = 0.0
        for rw, rl in pairs:
            p = bt_prob(rw, rl, alpha)
            total += math.log(max(p, 1e-300))
        return total

    lo, hi = ALPHA_BRACKET
    gr = (math.sqrt(5) - 1) / 2
    c = hi - gr * (hi - lo)
    d = lo + gr * (hi - lo)
    fc, fd = loglik(c), loglik(d)
    while hi - lo >= ALPHA_TOL:
        if fc < fd:
            lo = c
            c, fc = d, fd
            d = lo + gr * (hi - lo)
            fd = loglik(d)
        else:
            hi = d
            d, fd = c, fc
            c = hi - gr * (hi - lo)
            fc = loglik(c)
    return (lo + hi) / 2


# ---------------------------------------------------------------- scoring


def log_loss(p: float, y: int) -> float:
    p = min(max(p, 1e-15), 1 - 1e-15)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def calibration_error(scored):
    """Mean |predicted − realized| over probability deciles
    (design §6 criterion 3; READINGS R-CAL-1: unweighted mean over
    non-empty deciles). scored = [(p, y), ...]."""
    bins = [[] for _ in range(10)]
    for p, y in scored:
        idx = min(int(p * 10), 9)
        bins[idx].append((p, y))
    errs = []
    table = []
    for i, b in enumerate(bins):
        if not b:
            continue
        mp = sum(p for p, _ in b) / len(b)
        my = sum(y for _, y in b) / len(b)
        errs.append(abs(mp - my))
        table.append({"bin": i, "n": len(b), "mean_p": mp, "mean_y": my})
    if not errs:
        return None, table
    return sum(errs) / len(errs), table


def score_event_pairs(prob_by_pair: dict, event: Event):
    """Score one event's pairwise probabilities against its recorded
    finishes. Returns (scored, tie_mass_count, undecided_count) where
    scored = [(p, y)] over decided pairs present in prob_by_pair,
    y=1 when the pair's first player finished ahead."""
    by_id = {r.dg_id: r for r in event.rows}
    scored = []
    ties = 0
    undecided = 0
    for (i, j), p in prob_by_pair.items():
        d = decided_pair(by_id[i].fin, by_id[j].fin)
        if d is None:
            undecided += 1
        elif d == 0:
            ties += 1
        else:
            scored.append((p, 1 if d == 1 else 0))
    return scored, ties, undecided


# ---------------------------------------------------------------- gates + verdict


@dataclass
class Gates:
    amendment_adopted: bool = False
    pin_admitted: bool = False


def _check_gates(manifest_status: str, config: ExecutorConfig, gates: Gates):
    reasons = []
    if not gates.amendment_adopted:
        reasons.append("AMENDMENT_1_NOT_ADOPTED")
    if not gates.pin_admitted or not manifest_status.startswith("ADMITTED"):
        reasons.append("CONTENT_PIN_NOT_ADMITTED")
    for name in ("shrinkage_prior_rounds", "cut_size", "day_draw_sd", "seed"):
        if getattr(config, name) is None:
            reasons.append(f"UNPINNED_DESIGN_PARAMETER:{name}")
    if config.n_sims != config.design_sim_count:
        reasons.append("SIM_COUNT_NOT_AS_DESIGNED")
    if reasons:
        raise ScreenRefusal(reasons)


def run_leg1(corpus: Corpus, config: ExecutorConfig, gates: Gates):
    """The Leg 1 verdict path. Refuses (ScreenRefusal) unless the
    amendment is adopted, the content pin is admitted, and every design
    parameter is pinned — conditions no existing artifact satisfies.
    If reached in a future governed state, it executes §6 as written:
    per test season, fit α on the §6 fit window, price and simulate
    each test event, and score the candidate and both references over
    their defined comparison sets."""
    _check_gates(corpus.manifest_status, config, gates)
    rng = random.Random(config.seed)
    record = {
        "executor_version": EXECUTOR_VERSION,
        "corpus_sha256": corpus.corpus_sha256,
        "seasons": {},
    }
    pooled = {"candidate": [], "ref_a": [], "ref_b": []}
    for season in TEST_SEASONS:
        fit_events = [
            e for e in corpus.events if e.season <= FIT_WINDOW_MAX_SEASON[season]
        ]
        alpha = fit_alpha(collect_bt_pairs(fit_events))
        test_events = [e for e in corpus.events if e.season == season]
        season_rec = {"alpha": alpha, "matchups": 0, "events": len(test_events)}
        for ev in test_events:
            window = FeatureWindow(corpus, ev)
            prices = price_field(window, config)
            counts = simulate_event(prices, config, rng)
            cand = conditional_probs(counts)
            scored, _ties, _und = score_event_pairs(cand, ev)
            pooled["candidate"].extend(scored)
            season_rec["matchups"] += len(scored)
            ra = ref_a_probs(ev)
            ra_pairs = {}
            rb_pairs = {}
            ranks = {r.dg_id: r.owgr_rank for r in ev.rows}
            for i, j in cand:
                p_a = ref_a_pair(ra, i, j)
                if p_a is not None:
                    ra_pairs[(i, j)] = p_a
                if valid_rank(ranks.get(i)) and valid_rank(ranks.get(j)):
                    rb_pairs[(i, j)] = bt_prob(ranks[i], ranks[j], alpha)
            pooled["ref_a"].extend(score_event_pairs(ra_pairs, ev)[0])
            pooled["ref_b"].extend(score_event_pairs(rb_pairs, ev)[0])
        record["seasons"][str(season)] = season_rec

    def pooled_ll(scored):
        return sum(log_loss(p, y) for p, y in scored) / len(scored) if scored else None

    cal, _table = calibration_error(pooled["candidate"])
    ll_c, ll_a, ll_b = pooled_ll(pooled["candidate"]), pooled_ll(pooled["ref_a"]), pooled_ll(pooled["ref_b"])
    criteria = {
        "1_logloss_better_than_ref_a": ll_c is not None and ll_a is not None and ll_c < ll_a,
        "2_logloss_better_than_ref_b_prime": ll_c is not None and ll_b is not None and ll_c < ll_b,
        "3_calibration_within_bound": cal is not None and cal <= CALIBRATION_MAX,
        "4_volume_floor_each_season": all(
            record["seasons"][str(s)]["matchups"] >= VOLUME_FLOOR_PER_SEASON
            for s in TEST_SEASONS
        ),
    }
    record["pooled_log_loss"] = {"candidate": ll_c, "ref_a": ll_a, "ref_b_prime": ll_b}
    record["calibration_error"] = cal
    record["criteria"] = criteria
    record["verdict"] = "PASS" if all(criteria.values()) else "FAIL"
    return record
