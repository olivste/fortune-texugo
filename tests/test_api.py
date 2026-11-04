"""HTTP contracts without a database; PostgreSQL integration remains a separate check."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LEGACY_ACCOUNTS_ENABLED", "true")
    monkeypatch.setenv("PHONE_VERIFICATION_REQUIRED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("PRIZES_ENABLED", "false")
    monkeypatch.setenv("DEMO_UNLIMITED_SPINS", "false")
    # No context manager: these unit tests intentionally do not run DB startup.
    return TestClient(main.app)


@pytest.mark.parametrize('key', ['', 'wrong', 'inválida'])
def test_admin_rejects_bad_key(client, monkeypatch, key):
    monkeypatch.setenv('ADMIN_API_KEY', 'test-admin-secret')
    connect = MagicMock(side_effect=AssertionError('Unauthorized database access'))
    monkeypatch.setattr(main, 'connect', connect)
    assert client.get('/api/admin/stats', headers={'X-Admin-Key': key.encode('utf-8')}).status_code == 403
    connect.assert_not_called()


def test_admin_disabled_without_secret(client, monkeypatch):
    monkeypatch.delenv('ADMIN_API_KEY', raising=False)
    assert client.get('/api/admin/stats').status_code == 403


def test_admin_stats(client, monkeypatch):
    monkeypatch.setenv('ADMIN_API_KEY', 'test-admin-secret')
    connection = MagicMock()
    connection.__enter__.return_value.execute.return_value.fetchone.side_effect = [{'n': 4}, {'n': 7}, {'probability_bps': 200}]
    connection.__enter__.return_value.execute.return_value.fetchall.return_value = [{'id': 1, 'name': 'Copo Risca Faca', 'symbol': 'copo', 'stock': 5, 'total_quantity': 5, 'chance_multiplier': 1}]
    monkeypatch.setattr(main, 'connect', lambda: connection)
    result = client.get('/api/admin/stats', headers={'X-Admin-Key': 'test-admin-secret'})
    assert result.status_code == 200
    assert result.json()['players'] == 4
    assert result.json()['spins'] == 7
    assert result.json()['stock'] == 5
    assert result.json()['probability'] == 0.02
    assert result.json()['mode'] == 'demo'
    assert result.headers['cache-control'] == 'no-store'


def test_demo_cannot_be_enabled_by_environment(client, monkeypatch):
    monkeypatch.setenv('AUTHORIZED', 'true')
    connection = MagicMock()
    connection.__enter__.return_value.execute.return_value.fetchone.return_value = {'probability_bps': 200}
    monkeypatch.setattr(main, 'connect', lambda: connection)
    assert client.get('/api/config').json()['demo'] is True


@pytest.mark.parametrize('body', [
    {'name': ' ', 'phone': '27999999999'},
    {'name': 'Ana', 'phone': '00000000000'},
    {'name': 'Ana', 'phone': '123'},
])
def test_invalid_registration_never_reaches_database(client, monkeypatch, body):
    monkeypatch.setattr(main, 'connect', MagicMock(side_effect=AssertionError('Invalid input reached database')))
    assert client.post('/api/register', json=body).status_code == 422


def test_session_requires_token(client):
    assert client.get('/api/session').status_code == 401


def test_admin_page_and_scripts_are_served(client):
    assert client.get('/admin.html').status_code == 200
    assert client.get('/assets/admin.js').status_code == 200
    assert client.get('/assets/game.js').status_code == 200


@pytest.mark.parametrize('path,method', [
    ('/api/admin/prizes', 'get'), ('/api/admin/redeem', 'post'),
])
def test_prize_admin_requires_key(client, monkeypatch, path, method):
    monkeypatch.setenv('ADMIN_API_KEY', 'test-admin-secret')
    assert getattr(client, method)(path).status_code == 403


def test_live_requires_authorization_reference(monkeypatch):
    monkeypatch.setenv('PRIZES_ENABLED', 'true')
    monkeypatch.delenv('AUTHORIZATION_REFERENCE', raising=False)
    with pytest.raises(RuntimeError, match='AUTHORIZATION_REFERENCE'):
        main.validate_campaign_settings()


def test_live_requires_strong_admin_key(monkeypatch):
    monkeypatch.setenv('PRIZES_ENABLED', 'true')
    monkeypatch.setenv('AUTHORIZATION_REFERENCE', 'test-only')
    monkeypatch.setenv('ADMIN_API_KEY', 'short')
    with pytest.raises(RuntimeError, match='ADMIN_API_KEY'):
        main.validate_campaign_settings()


def test_spin_requires_idempotency_key(client):
    assert client.post('/api/spin', json={'session': 'x' * 64}).status_code == 422


@pytest.mark.parametrize('won', [False, True])
def test_middle_line_matches_prize_result(monkeypatch, won):
    monkeypatch.setattr(main.secrets, 'choice', lambda choices: choices[0])
    grid = main.make_grid(won)
    assert all(len(column) == 3 for column in grid)
    assert main.line_matches([column[1] for column in grid]) is won
    if won:
        assert sum(column[1] == 'wild' for column in grid) == 1
    if not won:
        assert len({column[1] for column in grid}) > 1


@pytest.mark.parametrize('path,method', [
    ('/api/admin/settings', 'get'), ('/api/admin/settings', 'put'),
    ('/api/admin/prize-types', 'post'), ('/api/admin/prize-types/1', 'put'),
])
def test_settings_and_catalog_require_admin(client, monkeypatch, path, method):
    monkeypatch.setenv('ADMIN_API_KEY', 'test-admin-secret')
    monkeypatch.setattr(main, 'connect', MagicMock(side_effect=AssertionError('Unauthorized database access')))
    assert getattr(client, method)(path).status_code == 403


@pytest.mark.parametrize('probability', ['-1', '100.01', '0.001', 'NaN', 'Infinity'])
def test_invalid_probability_rejected_before_database(client, monkeypatch, probability):
    monkeypatch.setenv('ADMIN_API_KEY', 'test-admin-secret')
    monkeypatch.setattr(main, 'connect', MagicMock(side_effect=AssertionError('Invalid input reached database')))
    assert client.put('/api/admin/settings', headers={'X-Admin-Key': 'test-admin-secret'},
                      json={'version': 1, 'probability_percent': probability}).status_code == 422


@pytest.mark.parametrize('change', [{'name': '  '}, {'symbol': 'unknown'}, {'symbol': 'wild'}, {'total_quantity': -1}, {'total_quantity': 1.5}, {'total_quantity': True}, {'total_quantity': 10001}, {'priority': 0}, {'priority': 10001}, {'priority': 1.5}])
def test_invalid_catalog_rejected_before_database(client, monkeypatch, change):
    monkeypatch.setenv('ADMIN_API_KEY', 'test-admin-secret')
    monkeypatch.setattr(main, 'connect', MagicMock(side_effect=AssertionError('Invalid input reached database')))
    body = {'version': 1, 'name': 'Pulseira de entrada no bar', 'symbol': 'texugo', 'total_quantity': 3, 'active': True, **change}
    assert client.post('/api/admin/prize-types', headers={'X-Admin-Key': 'test-admin-secret'}, json=body).status_code == 422


@pytest.mark.parametrize('line,expected', [
    (['copo', 'wild', 'copo'], True),
    (['wild', 'ficha', 'wild'], True),
    (['wild', 'wild', 'wild'], True),
    (['carta', 'carta', 'carta'], True),
    (['copo', 'wild', 'ficha'], False),
    (['wild', 'texugo', 'bananinha'], False),
    (['copo', 'ficha', 'carta'], False),
])
def test_wild_substitution(line, expected):
    assert main.line_matches(line) is expected


def test_losing_grid_never_becomes_a_win_when_random_rolls_are_all_wild(monkeypatch):
    monkeypatch.setattr(main.secrets, 'choice', lambda choices: 'wild' if 'wild' in choices else choices[0])
    grid = main.make_grid(False)
    assert not main.line_matches([column[1] for column in grid])


def test_wild_substitutes_every_real_prize_symbol():
    for symbol in [symbol for symbol in main.SYMBOLS if symbol != 'wild']:
        grid = main.make_grid(True, symbol)
        assert {column[1] for column in grid} == {symbol, 'wild'}
        assert any(column == ['wild'] * 3 for column in grid)
