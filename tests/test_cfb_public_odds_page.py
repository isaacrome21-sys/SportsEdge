from copy import deepcopy
import pytest
from scripts.import_cfb_public_odds_page import parse_page, attach_user_draftkings

STAMP = "2026-10-10T10:50:00Z"
KICK = "2026-10-10T16:00:00Z"


def page():
    return '''<table class="odds-table"><tbody id="odds-table-moneyline--0">
    <tr><td><span data-format="date" data-value="2026-10-10T16:00:00Z"></span></td>
    <th class="book-logo">Open</th><th class="book-logo"><img alt="DraftKings"></th>
    <th class="book-logo"><img alt="BetMGM"></th><th class="book-logo"><img alt="Consensus"></th></tr>
    <tr><td><a class="team-name">UCF</a></td>
    <td class="game-odds"><span class="data-moneyline">+999</span></td>
    <td class="game-odds"><span class="data-moneyline">+300</span></td>
    <td class="game-odds"><span class="data-moneyline">+325</span></td>
    <td class="game-odds"><span class="data-moneyline">+350</span></td></tr>
    <tr><td><a class="team-name">Oklahoma State</a></td>
    <td class="game-odds"><span class="data-moneyline">-1200</span></td>
    <td class="game-odds"><span class="data-moneyline">-400</span></td>
    <td class="game-odds"><span class="data-moneyline">-425</span></td>
    <td class="game-odds"><span class="data-moneyline">-450</span></td></tr>
    </tbody></table>'''


def parsed():
    return parse_page(page(), captured_at=STAMP, source_url="https://example.test/odds")


def test_real_moneyline_markup_and_book_column_identity():
    event = parsed()[0]
    assert [b['key'] for b in event['bookmakers']] == ['draftkings', 'betmgm']
    assert event['bookmakers'][1]['markets'][0]['outcomes'][0]['price'] == 325
    assert event['book_quote_receipt_verified'] is False
    assert 'last_update' not in event['bookmakers'][0]


def test_user_dk_offer_replaces_public_dk_without_mutating_reference():
    events = parsed()
    before = deepcopy(events)
    rows, missing = attach_user_draftkings(events, [
        {'away': 'UCF', 'home': 'Oklahoma State', 'start_ts': KICK, 'ml': [350, -455]}])
    dk = next(b for b in rows[0]['bookmakers'] if b['key'] == 'draftkings')
    assert dk['markets'][0]['outcomes'][0]['price'] == 350
    assert events == before
    assert missing == []


def test_wrong_kickoff_cannot_match_other_meeting():
    rows, missing = attach_user_draftkings(parsed(), [
        {'away': 'UCF', 'home': 'Oklahoma State', 'start_ts': '2026-10-17T16:00:00Z', 'ml': [350, -455]}])
    assert rows == []
    assert missing[0]['reason'] == 'PUBLIC_KICKOFF_MISMATCH'


def test_empty_or_incomplete_public_page_fails_explicitly():
    with pytest.raises(ValueError, match='NO_ODDS_TABLE_GAMES'):
        parse_page('<html></html>', captured_at=STAMP, source_url='test')
    broken = page().split('<tr><td><a class="team-name">Oklahoma State')[0] + '</tbody></table>'
    with pytest.raises(ValueError, match='INCOMPLETE_GAME_PAIR'):
        parse_page(broken, captured_at=STAMP, source_url='test')
