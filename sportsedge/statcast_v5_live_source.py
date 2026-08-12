"""Official-source live Statcast updater for SportsEdge V5.

The historical rebuild emits a hashed rolling state through end-2025.  Live runs
only need prior 2026 batted-ball contacts to advance that state.  Current-game
starter and lineup identities come from MLB StatsAPI, not Savant outcome rows.
"""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
from pathlib import Path
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib

from .statcast_v5_data import PlateAppearance, V5State, parse_savant_csv
from .statcast_v5_live import build_prior_state

SAVANT="https://baseballsavant.mlb.com/statcast_search/csv"
TRANSIENT_HTTP={429,500,502,503,504}
BATTED_BALL_TYPES="ground_ball|line_drive|fly_ball|popup|"

class StatcastLiveSourceError(ValueError):
    pass


def sha256_file(path:str|Path)->str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_hashed_state(path:str|Path,expected_sha256:str)->V5State:
    p=Path(path)
    if not p.is_file(): raise StatcastLiveSourceError(f"STATCAST_BASE_STATE_MISSING:{p}")
    got=sha256_file(p)
    if got!=expected_sha256: raise StatcastLiveSourceError(f"STATCAST_BASE_STATE_SHA_MISMATCH:{got}")
    try: state=joblib.load(p)
    except Exception as exc: raise StatcastLiveSourceError(f"STATCAST_BASE_STATE_LOAD_FAILED:{type(exc).__name__}") from exc
    if not isinstance(state,V5State): raise StatcastLiveSourceError("STATCAST_BASE_STATE_TYPE_INVALID")
    return state


def _url(year:int,lo:date,hi:date)->str:
    params={
        'all':'true','type':'details','player_type':'batter',
        'game_date_gt':(lo-timedelta(days=1)).isoformat(),
        'game_date_lt':(hi+timedelta(days=1)).isoformat(),
        'hfGT':'R|','hfSea':f'{year}|','hfBBT':BATTED_BALL_TYPES,
        'min_pitches':'0','min_results':'0','min_pas':'0',
        'sort_col':'pitches','player_event_sort':'api_p_release_speed','sort_order':'desc',
    }
    return SAVANT+'?'+urlencode(params)


def _download(year:int,lo:date,hi:date,cache:Path,opener:Callable=urlopen,max_attempts:int=4)->bytes:
    cache.mkdir(parents=True,exist_ok=True); p=cache/f"contacts_{lo}_{hi}.csv"
    if p.exists():
        raw=p.read_bytes()
        if b'game_date' in raw[:5000] and b'game_pk' in raw[:5000]: return raw
        p.unlink(missing_ok=True)
    last='UNKNOWN'
    for attempt in range(1,max_attempts+1):
        req=Request(_url(year,lo,hi),headers={
            'Accept':'text/csv,application/csv;q=0.9,*/*;q=0.1',
            'User-Agent':'Mozilla/5.0 (compatible; SportsEdge/5.0)',
            'Referer':'https://baseballsavant.mlb.com/statcast_search',
            'Accept-Language':'en-US,en;q=0.9',
        })
        try:
            with opener(req,timeout=120) as r: raw=r.read()
            if b'game_date' in raw[:5000] and b'game_pk' in raw[:5000]:
                p.write_bytes(raw); return raw
            sig=raw[:100].decode('utf-8',errors='replace').replace('\n',' ')
            last=f"NON_CSV:{sig!r}"
        except HTTPError as exc:
            last=f"HTTP_{exc.code}"
            if exc.code not in TRANSIENT_HTTP: raise StatcastLiveSourceError(f"STATCAST_LIVE_HTTP_FATAL:{exc.code}") from exc
        except (URLError,TimeoutError) as exc:
            last=f"{type(exc).__name__}:{exc}"
        if attempt<max_attempts: time.sleep(min(2**attempt,8))
    raise StatcastLiveSourceError(f"STATCAST_LIVE_FETCH_EXHAUSTED:{lo}:{hi}:{last}")


def _fetch_adaptive(year:int,lo:date,hi:date,cache:Path,opener:Callable=urlopen)->list[PlateAppearance]:
    try: raw=_download(year,lo,hi,cache,opener=opener)
    except StatcastLiveSourceError:
        if lo>=hi: raise
        mid=lo+timedelta(days=(hi-lo).days//2)
        return _fetch_adaptive(year,lo,mid,cache,opener)+_fetch_adaptive(year,mid+timedelta(days=1),hi,cache,opener)
    rows=parse_savant_csv(raw.decode('utf-8-sig',errors='replace'))
    return [r for r in rows if lo<=date.fromisoformat(r.game_date)<=hi]


def fetch_prior_season_contacts(*,year:int,start_date:date,cutoff_date:date,cache_dir:str|Path,opener:Callable=urlopen)->list[PlateAppearance]:
    """Fetch contacts with game_date strictly before cutoff_date."""
    last=cutoff_date-timedelta(days=1)
    if last<start_date: return []
    cache=Path(cache_dir); out=[]; cur=start_date
    while cur<=last:
        hi=min(last,cur+timedelta(days=6)); out.extend(_fetch_adaptive(year,cur,hi,cache,opener)); cur=hi+timedelta(days=1)
    bad=[r for r in out if date.fromisoformat(r.game_date)>=cutoff_date]
    if bad: raise StatcastLiveSourceError("STATCAST_LIVE_CUTOFF_VIOLATION")
    keys=[(r.game_pk,r.at_bat_number) for r in out]
    if len(keys)!=len(set(keys)): raise StatcastLiveSourceError("STATCAST_LIVE_DUPLICATE_PA")
    return out


def roll_state_to_cutoff(*,base_state:V5State,transformer,year:int,start_date:date,cutoff_date:date,cache_dir:str|Path,opener:Callable=urlopen)->V5State:
    rows=fetch_prior_season_contacts(year=year,start_date=start_date,cutoff_date=cutoff_date,cache_dir=cache_dir,opener=opener)
    return build_prior_state(rows,transformer,initial_state=base_state)
