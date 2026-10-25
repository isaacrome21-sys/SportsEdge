import json,sys,os,glob
out=open(sys.argv[2],'a')
for f in sorted(glob.glob(sys.argv[1]+'/*.json')):
    try: d=json.load(open(f))
    except Exception as e: print('bad',f,e); continue
    if not isinstance(d,dict): print('skip',f); continue
    P=d.get('all_plays') or []
    if not P: continue
    p0=P[0]
    g={'gid':p0.get('game_id'),'date':p0.get('game_date'),'start':p0.get('game_start'),
       'home':p0.get('home_abbreviation'),'away':p0.get('away_abbreviation'),
       'hfin':p0.get('home_final'),'afin':p0.get('away_final'),'venue':p0.get('venue_name')}
    hg=ag=None
    for p in P:
        if hg is None and p.get('home_goalie'): hg=p['home_goalie']
        if ag is None and p.get('away_goalie'): ag=p['away_goalie']
        if hg and ag: break
    g['hg'],g['ag']=hg,ag
    S=[]; pens=[0,0]; toi={}
    last=None
    for p in P:
        et=p.get('event_type')
        if p.get('period_type')=='SHOOTOUT' or (p.get('period') or 0)>4: continue
        t=p.get('game_seconds')
        st=p.get('strength_state')
        hs,as_=p.get('home_skaters'),p.get('away_skaters')
        if hs is not None and as_ is not None: st2='%sv%s'%(hs,as_)
        else: st2=None
        if last is not None and t is not None and st2:
            toi[last[1]]=toi.get(last[1],0)+max(0,t-last[0])
        if t is not None and st2: last=(t,st2)
        side=p.get('event_team_type')
        if et=='PENALTY' and side in('home','away'): pens[side=='away']+=1
        if et in('SHOT','MISSED_SHOT','GOAL') and side in('home','away'):
            S.append([0 if side=='home' else 1, 1 if et=='GOAL' else (2 if et=='SHOT' else 0),
                      p.get('shot_distance'),p.get('shot_angle'),st,(p.get('secondary_type') or '')[:5],
                      1 if p.get('empty_net') else 0,
                      p.get('away_goalie') if side=='home' else p.get('home_goalie'),p.get('period'),t])
    g['tb']=[[x.get('power_play_opportunities'),x.get('power_play_goals'),x.get('shots')] for x in (d.get('team_box') or [])]; g['tbn']=[x.get('tri_code') for x in (d.get('team_box') or [])]
    g['shots']=S; g['pens']=pens; g['toi']=toi
    out.write(json.dumps(g)+'\n')
