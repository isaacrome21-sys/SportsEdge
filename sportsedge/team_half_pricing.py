"""Market-blind, unvalidated team-total / football-half / MLB-F5 derivatives.

Only independent ESPN-verified game context is admitted. No user supplied
context overrides, probabilities, simulated player workloads, or venue coords.
Half is an explicit UNFITTED 0.50 score/variance scale, F5 is an UNFITTED 5/9
innings scale. These periods always stay research WATCH, even at fresh quotes.
No odds APIs or staking authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, sqrt
from typing import Mapping, Sequence

from artifacts import free_models as engine
from sportsedge.research_three_sport_bridge import price_three_sport_research

DERIVATIVES = frozenset({
    "TEAM_TOTAL", "TOTAL_1H", "SPREAD_1H", "TEAM_TOTAL_1H",
    "F5_TOTAL", "F5_TEAM_TOTAL",
})
TEAM_MARKETS = frozenset({"TEAM_TOTAL","TEAM_TOTAL_1H","F5_TEAM_TOTAL"})
PERIOD_MARKETS = DERIVATIVES - {"TEAM_TOTAL"}


def _fail(row, reason):
    return {
        "sport":row.get("sport"),"game_id":row.get("game_id"),
        "market":row.get("market"),"selection":row.get("side"),
        "status":"NO_MODEL_OR_MARKET","reason":str(reason)[:180],
        "research_only":True,"official_authority":False,
        "model_p_authority":False,"staking_authority":False,
    }


def _team_side(row):
    value = str(row.get("team") or "").strip()
    home = str(row.get("home") or "").strip()
    away = str(row.get("away") or "").strip()
    norm = engine.PublicContext.key
    if norm(value) == "home" or norm(value) == norm(home):
        return "HOME"
    if norm(value) == "away" or norm(value) == norm(away):
        return "AWAY"
    return None


def _scoring(sport, home, away, kickoff, now, provider):
    if sport not in {"NFL","CFB","MLB"}:
        raise ValueError("SPORT_NOT_SUPPORTED_BY_TEAM_PERIOD_MODEL")
    if sport == "CFB" and any(engine.PublicContext.key(x) in engine.IL_COLLEGE_NAMES for x in (home,away)):
        raise ValueError("ILLINOIS_COLLEGE_EXCLUDED")
    if not home or not away or home == away:
        raise ValueError("AWAY_HOME_REQUIRED")
    start = engine.dt(kickoff)
    if start is None or start <= now:
        raise ValueError("PREGAME_UNIQUE_KICKOFF_REQUIRED")
    # Bind the derived market to the independently verified fixture
    # competition ID, never an owner-provided JSON "game_id".
    fixture = provider.fixture(sport, away, home, start)
    if fixture is None or not isinstance(fixture[1], dict):
        raise ValueError("UNIQUE_PUBLIC_MATCHUP_REQUIRED")
    event_id = str(fixture[1].get("id") or "").strip()
    if not event_id:
        raise ValueError("PUBLIC_ESPN_GAME_ID_UNVERIFIED")
    # Do not pass caller-controlled context, venue coordinates or ESPN IDs.
    ctx, verified_start, notes = engine.context_for(sport,away,home,start,provider,{})
    if verified_start is None or verified_start <= now:
        raise ValueError("PUBLIC_MATCHUP_NOT_VERIFIED")
    if abs((verified_start-start).total_seconds()) > 900:
        raise ValueError("PUBLIC_FIXTURE_KICKOFF_MISMATCH")
    joined=" ".join(notes).upper()
    if any(x not in joined for x in ("HOME_HISTORY_COUNT:", "AWAY_HISTORY_COUNT:")):
        raise ValueError("TWO_TEAM_PUBLIC_HISTORY_REQUIRED")
    if "TEAM_IDENTITY_UNMATCHED" in joined or "HISTORY_MISSING" in joined:
        raise ValueError("TEAM_HISTORY_UNVERIFIED")
    if sport in {"NFL","CFB"}:
        if ("HOME_INJURIES:HEURISTIC_OUT_DOUBTFUL" not in joined or
            "AWAY_INJURIES:HEURISTIC_OUT_DOUBTFUL" not in joined):
            raise ValueError("PUBLIC_TEAM_INJURY_FEED_UNVERIFIED")
    if not any(flag in joined for flag in ("WEATHER:INDOOR_VERIFIED", "WEATHER:HEURISTIC_FORECAST")):
        raise ValueError("PUBLIC_VENUE_ENVIRONMENT_UNVERIFIED")
    base, sd_total, sd_margin, hfa = engine.PRIORS[sport]
    hm = base + hfa/2 + ctx["home_rating"]
    am = base - hfa/2 + ctx["away_rating"]
    if sport == "MLB":
        hm += ctx["home_pitcher_adj"]
        am += ctx["away_pitcher_adj"]
    else:
        hm += ctx["home_injury_pts"] + ctx["home_form"]
        am += ctx["away_injury_pts"] + ctx["away_form"]
    hm += ctx.get("weather_total_adj",0)/2
    am += ctx.get("weather_total_adj",0)/2
    if not min(hm,am) > .2:
        raise ValueError("IMPLAUSIBLE_SCORE_MEAN")
    return hm,am,sd_total,sd_margin,verified_start,notes,event_id


def _normal_outcome(mean,sd,side,line,*,spread=False):
    if sd <= 0 or not isfinite(sd) or not isfinite(line):
        raise ValueError("NONFINITE_DERIVATIVE_DISTRIBUTION")
    # Normal mass on discrete point totals/spreads (continuity correction).
    # This inherits the game model approximation; is NOT a fitted half model.
    decision = -line if spread else line
    # For spread, margin > -handicap. For totals, OVER > threshold.
    central=mean-decision
    cdf=lambda z: engine.cdf(z,0,sd)
    whole=float(decision).is_integer()
    push=(cdf(0.5-central)-cdf(-0.5-central)) if whole else 0.0
    if spread or side=="OVER":
        win=1-cdf((0.5 if whole else 0)-central)
    else:
        win=cdf((-0.5 if whole else 0)-central)
    win=max(0,min(1,float(win)));push=max(0,min(1,float(push)))
    if win+push>1+1e-6:
        raise ValueError("DERIVATIVE_PROBABILITY_MASS_INVALID")
    return win,push


def _poisson_outcome(mean,side,line):
    if mean < 0 or not isfinite(mean):
        raise ValueError("IMPLAUSIBLE_SCORE_MEAN")
    mass=engine.poisson(mean,max_k=75)
    win=sum(prob for n,prob in enumerate(mass)
            if (n>line if side=="OVER" else n<line))
    push=sum(prob for n,prob in enumerate(mass) if n==line)
    return win,push


def _estimate(row,scored,now):
    hm,am,sd_t,sd_m,verified,notes,game_id=scored
    sport=str(row["sport"]).upper()
    market=str(row["market"]).upper()
    side=str(row.get("side") or row.get("selection") or "").upper()
    if market not in DERIVATIVES:
        raise ValueError("DERIVATIVE_MARKET_UNSUPPORTED")
    if market in {"F5_TOTAL","F5_TEAM_TOTAL"} and sport!="MLB":
        raise ValueError("F5_MLB_ONLY")
    if market in {"TOTAL_1H","SPREAD_1H","TEAM_TOTAL_1H"} and sport not in {"NFL","CFB"}:
        raise ValueError("FOOTBALL_FIRST_HALF_ONLY")
    if side not in ({"HOME","AWAY"} if market=="SPREAD_1H" else {"OVER","UNDER"}):
        raise ValueError("MARKET_SELECTION_UNSUPPORTED")
    line=engine.numeric(row.get("line"),"DERIVATIVE_LINE")
    if market not in {"SPREAD_1H"} and line<0:
        raise ValueError("NEGATIVE_TOTAL_LINE")
    period=market in PERIOD_MARKETS
    scale=(5/9 if market.startswith("F5_") else .50 if period else 1.0)
    h,a=hm*scale,am*scale
    team_side=_team_side(row) if market in TEAM_MARKETS else None
    if market in TEAM_MARKETS and not team_side:
        raise ValueError("TEAM_TOTAL_SIDE_UNRESOLVED")
    if market in TEAM_MARKETS:
        mean=h if team_side=="HOME" else a
        if sport=="MLB":
            p,push=_poisson_outcome(mean,side,line)
        else:
            # Team score Var = (Var(total)+Var(margin))/4 assumes zero
            # total/margin covariance; no calibrated derivative variance.
            sd=sqrt(sd_t*sd_t+sd_m*sd_m)/2*sqrt(scale)
            p,push=_normal_outcome(mean,sd,side,line)
    elif market in {"TOTAL_1H","F5_TOTAL"}:
        mean=h+a
        if sport=="MLB":
            p,push=_poisson_outcome(mean,side,line)
        else:
            p,push=_normal_outcome(mean,sd_t*sqrt(scale),side,line)
    else:
        mean=(h-a) if side=="HOME" else (a-h)
        p,push=_normal_outcome(mean,sd_m*sqrt(scale),side,line,spread=True)
    if not 0<p<1 or not 0<=push<1 or p+push>=1:
        raise ValueError("DERIVATIVE_PROBABILITY_NOT_CALIBRATED_OR_DEGENERATE")
    model={
        "sport":sport,"game_id":game_id,
        "market":market,"selection":side,"line":line,
        "estimate_p":p,"push_p":push,
        "status":"PRICED_RESEARCH","market_blind":True,
        "model_source":"FREE_ESPN_SCORE_DERIVATIVE_UNVALIDATED_RATIO_"+str(round(scale,4)),
        "as_of_utc":now.isoformat(),"kickoff_utc":verified.isoformat(),
        "phase":"PREGAME","validated_vs_close":False,
        "official_authority":False,"model_p_authority":False,
        "staking_authority":False,"research_only":True,
        "home_team":row.get("home"),"away_team":row.get("away"),
        "raw_home_mean":round(hm,4),"raw_away_mean":round(am,4),
        "score_period_fraction":scale,
    }
    if team_side:
        model["player_id"]="TEAM:"+team_side
        model["team"]=team_side
    return model


def _quote_line_matches(market,quote_line,row_line):
    """Whether a candidate quote belongs to a model row's paired market.

    Totals and team totals quote both sides at ONE shared line. A spread is
    a single market quoted from opposite sides at signed-opposite lines:
    the favorite's -X and the underdog's +X. Pairing a spread row therefore
    admits both the row's own line and its exact negation; anything else
    (a different threshold, or the same threshold unsigned) is a different
    market and must never be paired into a no-vig price.
    """
    try:
        q=float(quote_line); r=float(row_line)
    except (TypeError,ValueError):
        return quote_line==row_line
    if market=="SPREAD_1H":
        return q==r or q==-r
    return q==r


def price_team_half_rows(rows:Sequence[Mapping],*,now=None,getter=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("MODEL_NOW_TIMEZONE_REQUIRED")
    now=now.astimezone(timezone.utc)
    provider=engine.PublicContext(now,getter=getter)
    cache={}
    result=[]
    for row in rows:
        key=(str(row.get("sport") or "").upper(),str(row.get("away") or ""),
             str(row.get("home") or ""),str(row.get("kickoff") or row.get("commence_time") or ""))
        if key not in cache:
            try:
                cache[key]=_scoring(key[0], key[2], key[1], key[3], now, provider)
            except (KeyError,TypeError,ValueError,AttributeError) as exc:
                cache[key]=str(exc)
        scored=cache[key]
        if not isinstance(scored,tuple):
            result.append(_fail(row,scored));continue
        try:
            model=_estimate(row,scored,now)
            # Line- and team-specific bookmaker quote identity. HOME vs
            # AWAY team totals at the same threshold can never cross-pair.
            quotes=[]
            for q in rows:
                if ((str(q.get("sport") or "").upper(),str(q.get("away") or ""),
                     str(q.get("home") or ""),str(q.get("kickoff") or q.get("commence_time") or ""))!=key or
                    str(q.get("market") or "").upper()!=model["market"] or
                    not _quote_line_matches(model["market"],q.get("line"),row.get("line"))):
                    continue
                other_team=_team_side(q) if model["market"] in TEAM_MARKETS else None
                if model["market"] in TEAM_MARKETS and other_team!=model["team"]:
                    continue
                quotes.append({
                    "sport":model["sport"],"game_id":model["game_id"],
                    "market":model["market"],"line":q.get("line"),
                    "selection":str(q.get("side") or q.get("selection") or "").upper(),
                    "odds":q.get("odds",q.get("price")),
                    "book":q.get("book") or "draftkings",
                    "quote_captured_at":q.get("quote_captured_at"),
                    "player_id":model.get("player_id"),
                    "home_team":row.get("home"),"away_team":row.get("away"),
                })
            priced=price_three_sport_research([model],quotes,as_of=now.isoformat())["rows"][0]
            priced["line"]=model["line"]
            priced["team"]=model.get("team")
            priced["raw_home_mean"]=model["raw_home_mean"]
            priced["raw_away_mean"]=model["raw_away_mean"]
            priced["score_period_fraction"]=model["score_period_fraction"]
            priced["source"]="FREE_ESPN_SCORE_DERIVATIVE_UNVALIDATED"
            if model["market"] in PERIOD_MARKETS and priced["status"]=="RESEARCH_CANDIDATE_NOT_VALIDATED":
                priced["status"]="WATCH_UNFITTED_PERIOD_SPLIT"
            result.append(priced)
        except (KeyError,TypeError,ValueError,AttributeError) as exc:
            result.append(_fail(row,exc))
    return result,provider.receipts
