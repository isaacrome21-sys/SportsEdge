"""Forward capture for the strict paired MLB OOS evaluator.

The strict evaluator (``strict_paired_oos.evaluate``) certifies *archived
live observations*: a frozen model's pregame prediction, a verified
two-sided same-book quote pair captured shortly before first pitch, and
explicit point-in-time receipts. Those observations cannot be reconstructed
retrospectively (probable-pitcher announcement times and pregame weather
forecasts are not archived by the free sources), so they must be captured
live, before first pitch, and preserved verbatim.

Archive layout (data-branch ready; the whole directory can live on the
``data`` branch unchanged)::

    archive/strict-forward-capture/
        captures/<fixture_id>__<market>__<selection>.json   (write-once)
        settlements.jsonl                                   (append-only)

A capture file holds every ``strict_paired_oos.REQUIRED`` field except
``outcome``, plus a ``capture_provenance`` envelope and a ``prediction``
section. Captures are immutable: ``write_capture`` refuses to overwrite
an existing file. Outcomes arrive later as appended settlement lines;
assembling evaluator rows joins the two without mutating either. A
settlement with ``correction: true`` supersedes an earlier settlement
for the same key (the original line is still preserved in the file).

Each (fixture, market, selection) is an INDEPENDENT observation with its
own matched same-book quote pair — markets are never merged into one
record. Lane labeling is mandatory: ``candidate_p`` is always the
market-blind Lane A probability for the record's own selection and
line; the market-anchored Lane B probability, when the production
pipeline emits one, lives only in ``prediction.market_anchored`` with
label ``MARKET_ANCHORED`` and is never the candidate. The ``prediction``
section also stores the production pricer's push-aware
P(win)/P(push)/P(loss) for the candidate lane. Settlements carry an
explicit ``outcome_state`` of ``WIN`` / ``LOSS`` / ``PUSH``; a PUSH
settlement blocks that observation at assembly (reported, never graded),
because the strict evaluator is binary-only.

This module never prices anything and never touches the network. The
capture CLI (``scripts/capture_strict_mlb_record.py``) runs the frozen
production pricer live and hands the resulting probabilities here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "MLB_STRICT_FORWARD_CAPTURE_V1"
ARCHIVE_DIRNAME = "strict-forward-capture"
OPPOSITES = {"HOME": "AWAY", "AWAY": "HOME",
             "OVER": "UNDER", "UNDER": "OVER"}
MARKETS = {"ML", "SPREAD", "TOTAL"}
# Fields the strict evaluator requires; a capture carries all but outcome.
EVALUATOR_FIELDS = (
    "fixture_id", "series_id", "market", "selection", "line",
    "kickoff_utc", "as_of_utc", "feature_max_available_at_utc",
    "train_last_final_at_utc", "model_source_sha", "market_blind",
    "candidate_p", "existing_p",
    "market_book", "opposite_book", "market_yes_american",
    "market_no_american", "market_yes_captured_at_utc",
    "market_no_captured_at_utc", "opposite_selection",
)


class CaptureError(ValueError):
    pass


def _stamp(value, key):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CaptureError("TIMESTAMP_INVALID:" + key) from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise CaptureError("TIMESTAMP_NOT_UTC_AWARE:" + key)
    return stamp.astimezone(timezone.utc)


def _iso(stamp):
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _probability(value, key):
    if isinstance(value, bool):
        raise CaptureError("PROBABILITY_INVALID:" + key)
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise CaptureError("PROBABILITY_INVALID:" + key) from exc
    if not isfinite(x) or not 0 < x < 1:
        raise CaptureError("PROBABILITY_INVALID:" + key)
    return x


def _american(value, key):
    """Mirror strict_paired_oos._decimal acceptance: |odds| must clear 100
    (exactly -100 is invalid there, so it is invalid here)."""
    if isinstance(value, bool):
        raise CaptureError("ODDS_INVALID:" + key)
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise CaptureError("ODDS_INVALID:" + key) from exc
    if not isfinite(v) or v == 0 or -100 <= v < 100:
        raise CaptureError("ODDS_INVALID:" + key)
    return int(v) if float(v).is_integer() else v


def fixture_id_for(away, home, kickoff_utc):
    """Harness fixture-id contract: league-local (America/New_York) date."""
    kick = _stamp(kickoff_utc, "kickoff_utc")
    local_date = kick.astimezone(ZoneInfo("America/New_York")).date()
    return f"mlb:{local_date.isoformat()}:{away}:{home}"


def compliance_warnings(fields):
    """Non-fatal evaluator-compliance risks, computed at capture time.

    A warning never blocks archiving (the archive is a truthful record);
    it tells the operator immediately that the strict evaluator will
    reject this row at evaluation time, and why.
    """
    kick = _stamp(fields["kickoff_utc"], "kickoff_utc")
    as_of = _stamp(fields["as_of_utc"], "as_of_utc")
    feature_at = _stamp(fields["feature_max_available_at_utc"],
                        "feature_max_available_at_utc")
    train_at = _stamp(fields["train_last_final_at_utc"],
                      "train_last_final_at_utc")
    yes_at = _stamp(fields["market_yes_captured_at_utc"],
                    "market_yes_captured_at_utc")
    no_at = _stamp(fields["market_no_captured_at_utc"],
                   "market_no_captured_at_utc")
    warnings = []
    if not (train_at < as_of < kick):
        warnings.append("PIT_TRAIN_OR_FEATURE_LEAKAGE_RISK")
    if feature_at > as_of:
        warnings.append("FEATURE_AVAILABLE_AFTER_AS_OF_RISK")
    if not (yes_at < kick and no_at < kick):
        warnings.append("MARKET_QUOTE_NOT_PREGAME_RISK")
    if abs((yes_at - no_at).total_seconds()) > 120:
        warnings.append("MARKET_PAIR_ASYNCHRONOUS_RISK")
    if (kick - max(yes_at, no_at)).total_seconds() > 1800:
        warnings.append("MARKET_NOT_VERIFIED_CLOSE_RISK")
    return warnings


def build_capture_record(*, away, home, kickoff_utc, series_id, market,
                         selection, line, book, selection_american,
                         selection_captured_at_utc, opposite_american,
                         opposite_captured_at_utc, candidate_p, existing_p,
                         model_source_sha, as_of_utc,
                         feature_max_available_at_utc,
                         train_last_final_at_utc, provenance,
                         prediction=None):
    """Assemble one immutable capture record (evaluator row minus outcome).

    ``market_yes_*`` is the row's selection; ``market_no_*`` is the
    opposite selection, same book. ``candidate_p`` must come from the
    frozen production pricer run live (market-blind Lane A);
    ``existing_p`` from the comparison model named in ``provenance``.
    """
    market = str(market).upper()
    selection = str(selection).upper()
    if market not in MARKETS:
        raise CaptureError("MARKET_UNSUPPORTED:" + market)
    if selection not in OPPOSITES:
        raise CaptureError("SELECTION_INVALID:" + selection)
    if market == "ML":
        if str(line) != "ML":
            raise CaptureError("ML_LINE_MUST_BE_ML")
        if selection not in {"HOME", "AWAY"}:
            raise CaptureError("ML_SELECTION_MUST_BE_HOME_OR_AWAY")
    else:
        try:
            point = float(line)
        except (TypeError, ValueError) as exc:
            raise CaptureError("MARKET_LINE_INVALID") from exc
        if not isfinite(point):
            raise CaptureError("MARKET_LINE_INVALID")
        if market == "TOTAL" and selection not in {"OVER", "UNDER"}:
            raise CaptureError("TOTAL_SELECTION_MUST_BE_OVER_OR_UNDER")
        if market == "SPREAD" and selection not in {"HOME", "AWAY"}:
            raise CaptureError("SPREAD_SELECTION_MUST_BE_HOME_OR_AWAY")
    book = str(book or "").strip()
    if not book:
        raise CaptureError("BOOK_UNKNOWN")
    if not str(model_source_sha or "").strip():
        raise CaptureError("MODEL_SHA_MISSING")
    if not str(series_id or "").strip():
        raise CaptureError("SERIES_ID_MISSING")
    fields = {
        "fixture_id": fixture_id_for(away, home, kickoff_utc),
        "series_id": str(series_id),
        "market": market,
        "selection": selection,
        "opposite_selection": OPPOSITES[selection],
        "line": "ML" if market == "ML" else float(line),
        "kickoff_utc": _iso(_stamp(kickoff_utc, "kickoff_utc")),
        "as_of_utc": _iso(_stamp(as_of_utc, "as_of_utc")),
        "feature_max_available_at_utc": _iso(_stamp(
            feature_max_available_at_utc, "feature_max_available_at_utc")),
        "train_last_final_at_utc": _iso(_stamp(
            train_last_final_at_utc, "train_last_final_at_utc")),
        "model_source_sha": str(model_source_sha),
        "market_blind": True,
        "candidate_p": _probability(candidate_p, "candidate_p"),
        "existing_p": _probability(existing_p, "existing_p"),
        "market_book": book,
        "opposite_book": book,
        "market_yes_american": _american(selection_american,
                                         "selection_american"),
        "market_no_american": _american(opposite_american,
                                        "opposite_american"),
        "market_yes_captured_at_utc": _iso(_stamp(
            selection_captured_at_utc, "selection_captured_at_utc")),
        "market_no_captured_at_utc": _iso(_stamp(
            opposite_captured_at_utc, "opposite_captured_at_utc")),
    }
    if prediction is not None and not isinstance(prediction, dict):
        raise CaptureError("PREDICTION_SECTION_NOT_OBJECT")
    record = dict(fields)
    record["capture_schema"] = VERSION
    record["compliance_warnings"] = compliance_warnings(fields)
    record["capture_provenance"] = provenance
    if prediction is not None:
        record["prediction"] = prediction
    return record


def capture_filename(record):
    raw = "{}__{}__{}".format(record["fixture_id"], record["market"],
                              record["selection"])
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_"
                   for c in raw)
    return safe + ".json"


def captures_dir(archive_dir):
    return Path(archive_dir) / "captures"


def settlements_path(archive_dir):
    return Path(archive_dir) / "settlements.jsonl"


def write_capture(archive_dir, record):
    """Write one capture file exactly once. Existing files are never
    overwritten — a second capture of the same key is an operator error,
    not an edit."""
    directory = captures_dir(archive_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / capture_filename(record)
    if path.exists():
        raise CaptureError("CAPTURE_ALREADY_EXISTS:" + str(path))
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return path


def append_settlement(archive_dir, settlement):
    """Append one settlement line. Never rewrites prior lines."""
    path = settlements_path(archive_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(settlement, sort_keys=True) + "\n")
    return path


def read_captures(archive_dir):
    directory = captures_dir(archive_dir)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        out.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return out


def read_settlements(archive_dir):
    path = settlements_path(archive_dir)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _settlement_key(entry):
    return (str(entry.get("fixture_id")), str(entry.get("market")),
            str(entry.get("selection")), str(entry.get("line")))


def assemble_rows(archive_dir):
    """Join captures + settlements into strict-evaluator rows.

    Returns ``(rows, excluded)``; every unjoined capture is reported in
    ``excluded`` with an exact reason — nothing is silently dropped.
    Settlement precedence: the first settlement for a key stands, unless
    a later line is marked ``correction: true`` (the latest correction
    wins; originals remain in the append-only file).
    """
    chosen = {}
    for entry in read_settlements(archive_dir):
        key = _settlement_key(entry)
        if key not in chosen or entry.get("correction") is True:
            chosen[key] = entry
    rows, excluded = [], []
    for path, record in read_captures(archive_dir):
        key = (str(record["fixture_id"]), str(record["market"]),
               str(record["selection"]), str(record["line"]))
        settlement = chosen.get(key)
        if settlement is None:
            excluded.append({"capture": path.name, "key": list(key),
                             "reason": "OUTCOME_NOT_SETTLED"})
            continue
        outcome = settlement.get("outcome")
        if outcome not in (0, 1) or isinstance(outcome, bool):
            is_push = (settlement.get("outcome_state") == "PUSH"
                       or settlement.get("outcome_grade") == 0.5)
            excluded.append({
                "capture": path.name, "key": list(key),
                "reason": ("PUSH_NOT_BINARY_SETTLEABLE" if is_push
                           else "NONBINARY_SETTLEMENT")})
            continue
        row = {k: record[k] for k in EVALUATOR_FIELDS}
        row["outcome"] = int(outcome)
        rows.append(row)
    return rows, excluded
