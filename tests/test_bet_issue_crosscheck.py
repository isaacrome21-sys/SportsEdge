"""[BET] issue picks are listed next to AUTO leans and conflicts are flagged."""
import importlib.util
import sys
from pathlib import Path

D=Path(__file__).resolve().parents[1]/"scripts"
sys.path.insert(0,str(D))
sp=importlib.util.spec_from_file_location("bet_issue_crosscheck",D/"bet_issue_crosscheck.py")
x=importlib.util.module_from_spec(sp); sp.loader.exec_module(x)


def _issue(n,away,home,market,pick,line,ev,date="2026-10-24"):
    body=(f"### Sport\n\nNCAAF\n\n### Away team\n\n{away}\n\n### Home team\n\n{home}\n\n"
          f"### Game date\n\n{date}\n\n### Market\n\n{market}\n\n### Pick\n\n{pick}\n\n"
          f"### Line\n\n{line}\n\n### Price\n\n-110\n\n### Tool EV %\n\n{ev}\n")
    return {"number":n,"title":f"[BET] CFB {away} @ {home} — {pick} (SportsEdge CFB_OPPONENT_ADJUSTED_V1)","body":body}


AUTO={"CFB":[
    {"matchup":"USC @ Wisconsin","market":"TOTAL","side":"OVER","line":50.5,"ev":.04},
    {"matchup":"San Diego State @ Colorado State","market":"TOTAL","side":"UNDER","line":58.5,"ev":.02},
    {"matchup":"Iowa @ Minnesota","market":"SPREAD","side":"Iowa","line":-3.5,"ev":.03},
]}


def test_conflicts_flagged_and_ranked_by_ev():
    issues=[
        _issue(2556,"USC","Wisconsin","Spread","Wisconsin +2.5","2.5","2.0"),
        _issue(2555,"San Diego State","Colorado State","Total","Over","58.5","1.1"),
        _issue(2557,"Iowa","Minnesota","Spread","Iowa -3.5","-3.5","3.4"),
        _issue(2558,"Iowa","Minnesota","Spread","Iowa -3.5","-3.5","9.9",date="2026-10-17"),
        {"number":1,"title":"[SPORTSEDGE AUTO] 2026-10-24","body":""},
    ]
    out="\n".join(x.render_crosscheck(issues,AUTO,"2026-10-24"))
    bets=[l for l in out.splitlines() if l.startswith("- ")]
    assert ["#2557" in bets[0],"#2556" in bets[1],"#2555" in bets[2]]==[True]*3
    assert len(bets)==3
    assert "AUTO agrees" in bets[0]
    assert "different market" in bets[1]
    assert "other side" in bets[2]
    assert "disagree: 2" in out
    assert "official" not in out.lower() and "truth gate" not in out.lower()


def test_no_bets_message():
    out=x.render_crosscheck([],AUTO,"2026-10-24")
    assert "No open [BET] issues for this date." in out
