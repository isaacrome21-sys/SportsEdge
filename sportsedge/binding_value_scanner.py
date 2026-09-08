"""Defense-in-depth scanner for binding identities that were renamed or nested.

Primary enforcement is structural binding/provenance. This scanner catches common
value-smuggling mistakes without treating key names alone as proof of identity.
"""
from __future__ import annotations
from typing import Any, Mapping

class BindingValueError(ValueError): pass

SENSITIVE_KEYS=frozenset({"event_id","game_number","book_key","team_id","player_id","pitcher_ids","american_odds","retrieved_at"})

def _walk(value:Any,path:str="$"):
    if isinstance(value,Mapping):
        for k,v in value.items():
            p=f"{path}.{k}";yield p,str(k),v;yield from _walk(v,p)
    elif isinstance(value,(list,tuple)):
        for i,v in enumerate(value):yield from _walk(v,f"{path}[{i}]")

def assert_no_quote_identity_in_model_payload(payload:Mapping[str,Any])->None:
    """Reject quote-origin identity fields from model-only payloads, recursively."""
    hits=[path for path,key,_ in _walk(payload) if key in SENSITIVE_KEYS]
    if hits:raise BindingValueError(f"QUOTE_IDENTITY_PROHIBITED_IN_MODEL_PAYLOAD:{sorted(hits)}")
