"""#2350 re-audit 2: Unicode/obfuscation-hardened Illinois matching (NFKC, zero-width
and confusable stripping, Cyrillic->Latin, underscore/camelCase split, letters-only
collapsed form) without overblocking look-alikes such as Northwestern St."""
import pytest

from sportsedge.research import cbb_foundation as F
from sportsedge.research.cbb_foundation import FoundationError, PlayerInput, TeamInput

BLOCK = ["De Paul", "DePaul_Blue_Demons", "DePaulBlueDemons", "BradleyBraves",
         "SIUEdwardsville", "Edwardsville", "IL State", "Il. State", "ILLST", "Chi State",
         "N'western", "\uff24\uff45\uff30\uff41\uff55\uff4c", "De\u200bPaul",
         "D\u0435Paul", "D e P a u l", "Saint Xavier", "Lewis",
         "Br\u0430dley", "\u200dSIUE\ufeff", "Loyola\u00a0Chicago", "N\u2019western"]
ALLOW = ["Northwestern St.", "Northwestern State", "Northwestern State Demons",
         "Indiana", "Indiana State", "Loyola Marymount", "Loyola Maryland", "Iowa",
         "Iowa State", "Eastern Michigan", "Western Michigan", "Northern Iowa",
         "Southern Indiana", "Boston University", "Florida Panthers", "Xavier",
         "Gonzaga Bulldogs", "Saint Louis", "St. John's"]


@pytest.mark.parametrize("name", BLOCK)
def test_obfuscated_illinois_forms_blocked(name):
    assert F.illinois_excluded(name), repr(name)
    with pytest.raises(FoundationError) as e:
        TeamInput(name, (PlayerInput("x_p0", 1, 1, 1),)).validate()
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
    assert F.market_terminal("MONEYLINE", name, "AWY")["terminal"] == "BLOCKED_BY_AUTHORIZATION"


@pytest.mark.parametrize("name", ALLOW)
def test_lookalikes_not_overblocked(name):
    assert not F.illinois_excluded(name), name
    assert F.market_terminal("MONEYLINE", name, "AWY")["terminal"] == "RESEARCH_ONLY"
