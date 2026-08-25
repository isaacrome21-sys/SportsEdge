import pytest

from sportsedge.ufc_source import UFCSourceError, bout_rounds_from_detail


class Response:
    def __init__(self, text):
        self._text = text
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return self._text.encode('utf-8')


def opener_for(text):
    def opener(request, timeout=20):
        return Response(text)
    return opener


def test_bout_rounds_parses_three_round_time_format():
    html = '<i>TIME_FORMAT:</i> 3 Rnd (5-5-5)'
    assert bout_rounds_from_detail('http://ufcstats.com/fight-details/x', opener=opener_for(html)) == 3


def test_bout_rounds_parses_five_round_time_format():
    html = '<i>TIME_FORMAT:</i> 5 Rnd (5-5-5-5-5)'
    assert bout_rounds_from_detail('http://ufcstats.com/fight-details/x', opener=opener_for(html)) == 5


def test_bout_rounds_fails_closed_without_time_format():
    with pytest.raises(UFCSourceError, match='BOUT_TIME_FORMAT_MISSING'):
        bout_rounds_from_detail('http://ufcstats.com/fight-details/x', opener=opener_for('<html></html>'))
