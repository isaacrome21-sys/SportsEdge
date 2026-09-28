import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

SCRIPT=Path("scripts/audit_nfl_qb_injury_coverage.py")

def test_roster_qb_without_injury_row_fails_closed(tmp_path):
    injuries=[]; rosters=[]
    for season in range(2009,2026):
        for week in range(1,19):
            key=f"QB-{season}-{week}"
            rosters.append({"season":season,"week":week,"position":"QB","team":"T","gsis_id":key})
            if not (season==2009 and week==1):
                injuries.append({"season":season,"week":week,"position":"QB","report_status":"Questionable","gsis_id":key,"date_modified":f"{season}-09-01T00:00:00Z"})
    ip=tmp_path/"inj.csv"; rp=tmp_path/"ros.csv"; op=tmp_path/"out.json"
    pd.DataFrame(injuries).to_csv(ip,index=False); pd.DataFrame(rosters).to_csv(rp,index=False)
    p=subprocess.run([sys.executable,str(SCRIPT),"--input",str(ip),"--weekly-rosters",str(rp),"--output",str(op)],capture_output=True,text=True)
    assert p.returncode!=0
    out=json.loads(op.read_text())
    assert out["status"]=="FAIL_CLOSED"
    assert out["roster_qb_keys_without_injury_row"]==1
    assert out["unmatched_by_season_week"]["2009-01"]==1
    assert out["missing_state_policy"]=="ROSTER_QB_WITHOUT_PIT_INJURY_ROW_IS_MISSING_NOT_AVAILABLE"
    assert out["development_validation_scoring_authority"] is False
