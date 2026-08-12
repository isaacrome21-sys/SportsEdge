"""Split-source historical assembly for Statcast V5.

Identity rows are first-inning PA events; contact rows are full-game batted-ball
events.  Features are built from the identity rows against state containing only
prior-date contacts, then all same-date contacts are applied after every game on
that date has been featured.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Sequence

from .statcast_v5_data import PlateAppearance, StatcastDataError, V5State, feature_game_before_update, update_state


def build_prior_only_game_features_split(
    identity_rows:Sequence[PlateAppearance],
    contact_rows:Sequence[PlateAppearance],
    transformer:Any,
    **kwargs,
)->tuple[list[dict[str,Any]],V5State]:
    identities=defaultdict(lambda:defaultdict(list)); contacts=defaultdict(lambda:defaultdict(list))
    for r in identity_rows: identities[r.game_date][r.game_pk].append(r)
    for r in contact_rows:
        if r.is_contact: contacts[r.game_date][r.game_pk].append(r)
    state=V5State(); out=[]
    all_dates=sorted(set(identities)|set(contacts))
    for gd in all_dates:
        pending_contacts=[]
        for gp in sorted(identities.get(gd,{})):
            gr=identities[gd][gp]
            try: out.append(feature_game_before_update(state,gr,**kwargs))
            except StatcastDataError as exc: out.append({'game_pk':gp,'game_date':gd,'blocked':str(exc)})
        for gp in sorted(contacts.get(gd,{})):
            pending_contacts.append(contacts[gd][gp])
        for gr in pending_contacts: update_state(state,gr,transformer)
    return out,state
