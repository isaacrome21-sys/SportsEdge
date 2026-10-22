"""File-based, read-only CFB/NHL research readout. No network, book, PLAY.

Input JSON example:
{"as_of":"2026-10-21T17:00:00Z",
 "nhl_games":[{"away":"Flyers","home":"Sabres","event_id":"X",
  "event_start":"2026-10-21T23:00:00Z","fixture_source_ref":"receipt"}],
 "cfb_games":[{"away":"New Mexico State","home":"Sam Houston",
  "event_id":"Y","event_start":"2026-10-21T23:00:00Z"}]}
Each fixture reference is a caller assertion, NOT verified provenance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.research.cfb_nhl_coverage_v1 import (
    nhl_research_snapshot,cfb_readiness,
)
from sportsedge.research.nhl_paired_market_readout_v1 import (
    nhl_paired_market_readout,
)


def run_payload(raw):
    if not isinstance(raw,dict):
        raise ValueError("CFB_NHL_READOUT_OBJECT_REQUIRED")
    if not raw.get("as_of"):
        raise ValueError("CFB_NHL_READOUT_AS_OF_REQUIRED")
    nhl,cfb=raw.get("nhl_games",[]),raw.get("cfb_games",[])
    if not isinstance(nhl,list) or not isinstance(cfb,list):
        raise ValueError("CFB_NHL_READOUT_GAMES_MUST_BE_LISTS")
    if len(nhl)+len(cfb)==0:
        raise ValueError("CFB_NHL_READOUT_NO_GAMES")
    outputs=[]
    seen=set()
    for sport,items in (("NHL",nhl),("CFB",cfb)):
        for g in items:
            if not isinstance(g,dict):
                raise ValueError("CFB_NHL_READOUT_GAME_OBJECT_REQUIRED")
            gid=str(g.get("event_id") or "").strip()
            if not gid or (sport,gid) in seen:
                raise ValueError("CFB_NHL_READOUT_DUPLICATE_OR_MISSING_EVENT")
            seen.add((sport,gid))
            common={"away":g.get("away"),"home":g.get("home"),
                    "event_id":gid,"event_start":g.get("event_start"),
                    "as_of":raw["as_of"]}
            if sport=="NHL":
                result=nhl_research_snapshot(
                    **common,fixture_source_ref=g.get("fixture_source_ref"),
                    total_line=g.get("total_line",5.5))
                # Explicit OPT-IN only: no synthetic book lines are produced
                # when paired_markets is missing. A caller's capture/source
                # strings remain *declarations*, never verified evidence.
                if "paired_markets" in g:
                    markets=g["paired_markets"]
                    if not isinstance(markets,list) or not markets:
                        raise ValueError("NHL_PAIRED_MARKETS_NONEMPTY_LIST_REQUIRED")
                    if len({str(m.get("market") or "").upper()
                            for m in markets if isinstance(m,dict)}) != len(markets):
                        raise ValueError("NHL_DUPLICATE_MARKET_PAIR")
                    paired=[]
                    for m in markets:
                        if not isinstance(m,dict):
                            raise ValueError("NHL_PAIRED_MARKET_OBJECT_REQUIRED")
                        paired.append(nhl_paired_market_readout(
                            **common,
                            fixture_source_ref=g.get("fixture_source_ref"),
                            quote_source_ref=m.get("quote_source_ref"),
                            capture_id=m.get("capture_id"),market=m.get("market"),
                            quote_rows=m.get("quote_rows"),book=m.get("book","DraftKings")))
                    result={**result,"paired_market_diagnostics":paired}
            else:
                result=cfb_readiness(
                    **common,qb_manifest_pin=g.get("qb_manifest_pin"),
                    paired_dk_capture_ref=g.get("paired_dk_capture_ref"))
            outputs.append(result)
    receipt=hashlib.sha256(json.dumps(raw,sort_keys=True,
                    separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
    return {"schema":"CFB_NHL_RESEARCH_READOUT_V1",
            "input_sha256":receipt, "as_of":raw["as_of"],
            "items":outputs,"count":len(outputs),
            "source_provenance":"CALLER_SUPPLIED_NOT_INDEPENDENTLY_AUTHENTICATED",
            "book_quote_authentication":"NONE",
            "model_validation":"NONE", "play_authority":False}


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args(argv)
    result=run_payload(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
