"""t140: keep anchor test fixtures runnable on hosted CI's OpenSSL 3.0.

#2223 failed full-discovery-honesty and automation-core at 48bf3351 because a
fixture called ``openssl x509 -req -not_before/-not_after`` (OpenSSL >= 3.4 only);
41 tests errored at setup. 2d9fdea3 switched to ``openssl ca -startdate/-enddate``.
This guard stops a 3.4+-only x509 option from coming back into any test or
fixture source, so the regression is caught locally on newer OpenSSL too.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
_FORBIDDEN = re.compile(r"""["'](-not_before|-not_after)["']""")


def test_no_openssl34_only_x509_validity_flags_in_test_sources():
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name == Path(__file__).name:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _FORBIDDEN.search(line):
                offenders.append(f"{path.name}:{lineno}")
    assert offenders == [], f"OpenSSL>=3.4-only x509 flags used: {offenders}"


def test_guard_pattern_matches_the_original_failure():
    assert _FORBIDDEN.search('"-out", "tsa.pem", "-not_before", "20200101000000Z"')
    assert not _FORBIDDEN.search("# -not_before needs OpenSSL >= 3.4")
