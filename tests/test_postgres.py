"""Real PostgreSQL transaction tests. Each test owns a disposable schema.
Set FORTUNE_TEST_DATABASE_URL to a dedicated local test database to run.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient

from api import main


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setenv("LEGACY_ACCOUNTS_ENABLED", "true")
    monkeypatch.setenv("PHONE_VERIFICATION_REQUIRED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    url = os.environ.get('FORTUNE_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set FORTUNE_TEST_DATABASE_URL to run PostgreSQL tests')
    namespace = 'test_fortune_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(namespace)))

    def connect():
        conn = psycopg.connect(url, row_factory=dict_row)
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(namespace)))
        conn.commit()
        return conn

    monkeypatch.setattr(main, 'connect', connect)
    monkeypatch.setenv('PHONE_PEPPER', 'test-phone-pepper-' + 'x' * 32)
    monkeypatch.setenv('ADMIN_API_KEY', 'test-admin-key-' + 'x' * 32)
    monkeypatch.setenv('AUTHORIZATION_REFERENCE', 'TEST-ONLY-NOT-AN-AUTHORIZATION')
    monkeypatch.setenv('PRIZES_ENABLED', 'true')
    monkeypatch.setenv('DEMO_UNLIMITED_SPINS', 'false')
    monkeypatch.setattr(main.secrets, 'randbelow', lambda n: 0)
    try:
        with TestClient(main.app) as client:
            yield client, connect
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(namespace)))


def register(client, number=0):
    result = client.post('/api/register', json={'name': 'Participante Teste', 'phone': f'279{number:08d}'})
    assert result.status_code == 201, result.text
    return result.json()['session']


def spin(client, token, request_id=None):
    return client.post('/api/spin', json={'session': token, 'request_id': request_id or str(uuid4())})


def headers():
    return {'X-Admin-Key': os.environ['ADMIN_API_KEY']}


def test_win_replay_limit_restore_and_redemption(database):
    client, connect = database
    token = register(client)
    request_id = str(uuid4())
    first = spin(client, token, request_id).json()
    assert first['won'] is True and first['stock'] == 4
    assert set(column[1] for column in first['grid']) == {'copo', 'wild'}
    assert spin(client, token, request_id).json() == first
    assert spin(client, token).status_code == 409  # winners cannot spin again
    assert spin(client, token).status_code == 409
    assert spin(client, token).status_code == 409
    assert spin(client, token, request_id).json() == first  # replay after credits exhausted
    recovered = client.get('/api/session', headers={'Authorization': 'Bearer ' + token}).json()
    assert recovered['spins_left'] == 0
    assert recovered['prize']['claim_code'] == first['claim_code']
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM spins').fetchone()['n'] == 1
        assert conn.execute('SELECT authorization_reference FROM spins LIMIT 1').fetchone()['authorization_reference'] == 'TEST-ONLY-NOT-AN-AUTHORIZATION'
    body = {'claim_code': first['claim_code']}
    assert client.post('/api/admin/redeem', headers=headers(), json=body).status_code == 200
    assert client.post('/api/admin/redeem', headers=headers(), json=body).status_code == 409
    assert client.get('/api/admin/prizes', headers=headers()).json()[0]['redeemed_at']
    assert client.get('/api/session', headers={'Authorization': 'Bearer ' + token}).json()['prize']['redeemed_at']


def test_hundred_concurrent_spins_never_award_more_than_five(database):
    client, connect = database
    tokens = [register(client, i) for i in range(100)]
    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(lambda token: spin(client, token), tokens))
    assert all(response.status_code == 200 for response in responses)
    assert sum(response.json()['won'] for response in responses) == 5
    with connect() as conn:
        assert conn.execute('SELECT sum(stock) AS stock FROM prize_types').fetchone()['stock'] == 0
        assert conn.execute('SELECT count(*) AS n FROM prizes').fetchone()['n'] == 5
        assert conn.execute('SELECT count(*) AS n FROM spins').fetchone()['n'] == 100
        # Restart / migration must never replenish inventory.
        conn.execute(main.SCHEMA, prepare=False)
        assert conn.execute('SELECT sum(stock) AS stock FROM prize_types').fetchone()['stock'] == 0
    assert client.get('/api/config').json()['stock'] == 0


def test_concurrent_retries_consume_only_one_credit(database):
    client, connect = database
    token = register(client)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(lambda _: spin(client, token, key), range(24)))
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)
    with connect() as conn:
        assert conn.execute('SELECT spins_left FROM players').fetchone()['spins_left'] == 0
        assert conn.execute('SELECT count(*) AS n FROM spins').fetchone()['n'] == 1
        assert conn.execute('SELECT sum(stock) AS stock FROM prize_types').fetchone()['stock'] == 4


def test_concurrent_distinct_requests_respect_three_credits(database, monkeypatch):
    client, connect = database
    monkeypatch.setenv('PRIZES_ENABLED', 'false')
    token = register(client)
    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(lambda _: spin(client, token), range(20)))
    assert sum(response.status_code == 200 for response in responses) == 3
    assert sum(response.status_code == 409 for response in responses) == 17
    with connect() as conn:
        assert conn.execute('SELECT spins_left FROM players').fetchone()['spins_left'] == 0


def test_failed_transaction_restores_credit_stock_and_prize(database, monkeypatch):
    client, connect = database
    token = register(client)
    def fail(*_):
        raise RuntimeError('Simulated failure after stock decrement')
    monkeypatch.setattr(main, 'make_grid', fail)
    with pytest.raises(RuntimeError, match='Simulated failure'):
        spin(client, token)
    with connect() as conn:
        assert conn.execute('SELECT spins_left FROM players').fetchone()['spins_left'] == 3
        assert conn.execute('SELECT sum(stock) AS stock FROM prize_types').fetchone()['stock'] == 5
        assert conn.execute('SELECT count(*) AS n FROM prizes').fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) AS n FROM spins').fetchone()['n'] == 0


@pytest.mark.parametrize('roll,won', [(199, True), (200, False), (9999, False)])
def test_two_percent_boundary(database, monkeypatch, roll, won):
    client, _ = database
    monkeypatch.setattr(main.secrets, 'randbelow', lambda n: roll % n)
    assert spin(client, register(client)).json()['won'] is won


def test_demo_never_awards_even_with_winning_roll(database, monkeypatch):
    client, connect = database
    monkeypatch.setenv('PRIZES_ENABLED', 'false')
    token = register(client)
    for _ in range(3):
        result = spin(client, token).json()
        assert result['demo'] is True and result['won'] is False and result['claim_code'] is None
    with connect() as conn:
        assert conn.execute('SELECT sum(stock) AS stock FROM prize_types').fetchone()['stock'] == 5
        assert conn.execute('SELECT count(*) AS n FROM prizes').fetchone()['n'] == 0


def test_simultaneous_redemptions_only_one_succeeds(database):
    client, _ = database
    result = spin(client, register(client)).json()
    def redeem(_):
        return client.post('/api/admin/redeem', headers=headers(), json={'claim_code': result['claim_code']})
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(redeem, range(8)))
    assert sum(r.status_code == 200 for r in responses) == 1
    assert sum(r.status_code == 409 for r in responses) == 7


def test_duplicate_phone_and_invalid_session(database):
    client, _ = database
    register(client)
    assert client.post('/api/register', json={'name': 'Outro nome', 'phone': '+55 (27) 90000-0000'}).status_code == 409
    assert spin(client, 'x' * 64).status_code == 401


def test_unlimited_preview_accepts_exhausted_session_without_changing_balance(database, monkeypatch):
    client, connect = database
    monkeypatch.setenv('PRIZES_ENABLED', 'false')
    token = register(client)
    for _ in range(3):
        assert spin(client, token).status_code == 200
    monkeypatch.setenv('DEMO_UNLIMITED_SPINS', 'true')
    for _ in range(12):
        result = spin(client, token).json()
        assert result['unlimited_spins'] is True and result['spins_left'] == 3
        assert result['won'] is False
    with connect() as conn:
        assert conn.execute('SELECT spins_left FROM players').fetchone()['spins_left'] == 0
        assert conn.execute('SELECT sum(stock) AS stock FROM prize_types').fetchone()['stock'] == 5
    monkeypatch.setenv('DEMO_UNLIMITED_SPINS', 'false')
    assert spin(client, token).status_code == 409


def test_unlimited_flag_does_not_bypass_live_campaign_limit(database, monkeypatch):
    client, _ = database
    monkeypatch.setenv('DEMO_UNLIMITED_SPINS', 'true')
    monkeypatch.setattr(main.secrets, 'randbelow', lambda n: 9999)
    token = register(client)
    for _ in range(3):
        result = spin(client, token).json()
        assert result['unlimited_spins'] is False
    assert spin(client, token).status_code == 409


def get_settings(client):
    result = client.get('/api/admin/settings', headers=headers())
    assert result.status_code == 200
    return result.json()


def set_chance(client, chance):
    return client.put('/api/admin/settings', headers=headers(),
                      json={'version': get_settings(client)['version'], 'probability_percent': chance})


def edit_item(client, item, **changes):
    body = {key: item[key] for key in ['name', 'symbol', 'total_quantity', 'active', 'priority', 'chance_multiplier']}
    body.update(changes)
    body['version'] = get_settings(client)['version']
    return client.put(f'/api/admin/prize-types/{item["id"]}', headers=headers(), json=body)


def add_item(client, **changes):
    return client.post('/api/admin/prize-types', headers=headers(), json={
        'version': get_settings(client)['version'], 'name': 'Pulseira de entrada no bar',
        'symbol': 'ficha', 'priority': 2, 'total_quantity': 3, 'active': True, **changes})


def test_admin_probability_takes_effect_at_exact_boundary(database, monkeypatch):
    client, connect = database
    assert set_chance(client, '10.25').status_code == 200
    assert client.get('/api/config').json()['probability'] == 0.1025
    monkeypatch.setattr(main.secrets, 'randbelow', lambda n: 1024 % n)
    assert spin(client, register(client, 0)).json()['won'] is True
    monkeypatch.setattr(main.secrets, 'randbelow', lambda n: 1025 % n)
    assert spin(client, register(client, 1)).json()['won'] is False
    with connect() as conn:
        assert conn.execute('SELECT probability_bps FROM campaign').fetchone()['probability_bps'] == 1025
        assert conn.execute('SELECT count(*) AS n FROM admin_changes').fetchone()['n'] == 1


def test_zero_percent_and_demo_with_hundred_percent_never_award(database, monkeypatch):
    client, _ = database
    set_chance(client, 0)
    assert spin(client, register(client, 0)).json()['won'] is False
    monkeypatch.setenv('PRIZES_ENABLED', 'false')
    assert set_chance(client, 100).status_code == 200
    assert spin(client, register(client, 1)).json()['won'] is False


def test_different_prize_name_symbol_and_historical_snapshot(database):
    client, _ = database
    cup = get_settings(client)['items'][0]
    assert edit_item(client, cup, active=False).status_code == 200
    result = add_item(client, total_quantity=1)
    assert result.status_code == 201
    shirt = result.json()['items'][-1]
    token = register(client)
    won = spin(client, token).json()
    assert won['won'] is True and won['prize_name'] == 'Pulseira de entrada no bar'
    assert won['prize_symbol'] == 'ficha' and won['stock'] == 0
    assert set(column[1] for column in won['grid']) == {'ficha', 'wild'}
    assert edit_item(client, shirt, name='Pulseira atualizada').status_code == 200
    prize = client.get('/api/session', headers={'Authorization': 'Bearer ' + token}).json()['prize']
    assert prize['prize_name'] == 'Pulseira de entrada no bar'
    assert client.get('/api/admin/prizes', headers=headers()).json()[0]['prize_name'] == 'Pulseira de entrada no bar'
    assert spin(client, register(client, 1)).json()['won'] is False


def test_stock_edits_preserve_awards_and_do_not_replenish_on_stale_form(database):
    client, _ = database
    cup = get_settings(client)['items'][0]
    win = spin(client, register(client)).json()
    assert edit_item(client, cup, total_quantity=0).status_code == 409
    # Saving the original total after a concurrent award keeps the remaining stock at 4.
    saved = edit_item(client, cup)
    assert saved.status_code == 200 and saved.json()['items'][0]['stock'] == 4
    increased = edit_item(client, cup, total_quantity=8)
    assert increased.status_code == 200 and increased.json()['items'][0]['stock'] == 7
    assert edit_item(client, cup, active=False, total_quantity=8).status_code == 200
    assert client.get('/api/config').json()['stock'] == 0
    assert client.post('/api/admin/redeem', headers=headers(), json={'claim_code': win['claim_code']}).status_code == 200


def test_concurrent_catalog_edits_reject_stale_version(database):
    client, _ = database
    version = get_settings(client)['version']
    def update(value):
        return client.put('/api/admin/settings', headers=headers(), json={'version': version, 'probability_percent': value})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(update, [10, 20]))
    assert sorted(r.status_code for r in responses) == [200, 409]


def test_concurrent_spins_respect_each_prize_type_inventory(database,monkeypatch):
    client, connect = database
    rng=main.secrets.SystemRandom()
    monkeypatch.setattr(main.secrets,'randbelow',lambda n:0 if n==10000 else rng.randrange(n))
    assert add_item(client, total_quantity=3).status_code == 201
    tokens = [register(client, i) for i in range(30)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(lambda token: spin(client, token), tokens))
    assert all(r.status_code == 200 for r in responses)
    wins = [r.json() for r in responses if r.json()['won']]
    assert len(wins) == 8
    assert sum(p['prize_name'] == 'Copo Risca Faca' for p in wins) == 5
    assert sum(p['prize_name'] == 'Pulseira de entrada no bar' for p in wins) == 3
    with connect() as conn:
        assert all(row['stock'] == 0 for row in conn.execute('SELECT stock FROM prize_types').fetchall())


def test_random_prizes_can_award_wristbands_before_cups_and_replay_is_unchanged(database, monkeypatch):
    client, _ = database
    assert add_item(client,total_quantity=2).status_code==201
    monkeypatch.setattr(main.secrets,'randbelow',lambda n:0 if n==10000 else n-1)
    token=register(client)
    key=str(uuid4())
    first=spin(client,token,key).json()
    assert first['prize_name']=='Pulseira de entrada no bar'
    config=client.get('/api/config').json()
    assert config['selection_mode']=='random_weighted' and config['current_prize'] is None
    assert next(item for item in config['prize_options'] if item['symbol']=='copo')['stock']==5
    set_chance(client,0)
    assert spin(client,token,key).json()==first


def test_display_order_does_not_force_prizes_and_paused_items_are_excluded(database,monkeypatch):
    client, _ = database
    added=add_item(client,priority=2).json()
    wristband=next(item for item in added['items'] if item['symbol']=='ficha')
    cup=next(item for item in added['items'] if item['symbol']=='copo')
    assert edit_item(client,wristband,priority=1).status_code==200
    assert edit_item(client,cup,priority=3).status_code==200
    # Last weighted ticket chooses the displayed-last cup, even while wristbands remain.
    monkeypatch.setattr(main.secrets,'randbelow',lambda n:0 if n==10000 else n-1)
    assert spin(client,register(client)).json()['prize_name']=='Copo Risca Faca'
    assert edit_item(client,cup,active=False).status_code==200
    assert spin(client,register(client,1)).json()['prize_name']=='Pulseira de entrada no bar'


def test_original_cup_migration_preserves_stock_codes_and_restart(database):
    client, connect = database
    won = spin(client, register(client)).json()
    # Reproduce the pre-catalog schema, including a previously awarded cup.
    with connect() as conn:
        conn.execute('ALTER TABLE prizes DROP COLUMN prize_type_id, DROP COLUMN prize_name, DROP COLUMN prize_symbol')
        conn.execute('DROP TABLE prize_types')
        conn.execute('ALTER TABLE campaign ADD COLUMN stock SMALLINT DEFAULT 4 CHECK (stock BETWEEN 0 AND 5)')
        conn.execute('ALTER TABLE campaign DROP COLUMN probability_bps, DROP COLUMN settings_version')
        conn.execute(main.SCHEMA, prepare=False)
        conn.execute("UPDATE prize_types SET priority=7 WHERE catalog_key='original-cup'")
        conn.execute(main.SCHEMA, prepare=False)
        cup = conn.execute('SELECT * FROM prize_types').fetchone()
        assert cup['stock'] == 4 and cup['total_quantity'] == 5 and cup['priority'] == 7
        prize = conn.execute('SELECT * FROM prizes').fetchone()
        assert prize['claim_code'] == won['claim_code'] and prize['prize_type_id'] == cup['id']
        assert prize['prize_name'] == 'Copo Risca Faca'


def test_prize_weights_split_the_global_chance_without_multiplying_it(database,monkeypatch):
    client, _ = database
    assert add_item(client,total_quantity=10,chance_multiplier=2).status_code==201
    config=client.get('/api/config').json()
    cup,wristband=config['prize_options']
    assert config['probability']==0.02
    assert cup['selection_probability']==pytest.approx(1/3)
    assert wristband['selection_probability']==pytest.approx(2/3)
    assert cup['probability']==pytest.approx(.02/3)
    assert wristband['probability']==pytest.approx(.04/3)
    monkeypatch.setattr(main.secrets,'randbelow',lambda n:200 % n)
    assert spin(client,register(client)).json()['won'] is False
    monkeypatch.setattr(main.secrets,'randbelow',lambda n:199 if n==10000 else n-1)
    won=spin(client,register(client,1)).json()
    assert won['won'] and won['prize_name']=='Pulseira de entrada no bar'
    assert won['spin_probability']==.02
    set_chance(client,60)
    assert client.get('/api/config').json()['probability']==.6
    saved_wristband=next(item for item in get_settings(client)['items'] if item['id']==wristband['id'])
    assert edit_item(client,saved_wristband,name='Pulseira bar').json()['items'][1]['chance_multiplier']==2


@pytest.mark.parametrize('ticket,expected',[(0,'copo'),(1,'ficha'),(2,'ficha')])
def test_weighted_draw_has_exact_integer_boundaries(monkeypatch,ticket,expected):
    items=[{'symbol':'copo','chance_multiplier':1},{'symbol':'ficha','chance_multiplier':2}]
    def draw(n):
        assert n==3
        return ticket
    monkeypatch.setattr(main.secrets,'randbelow',draw)
    assert main.random_prize(items)['symbol']==expected


def test_readable_code_and_winner_cannot_spin_even_after_redemption(database):
    client, connect = database
    result = client.post('/api/register', json={'name': 'João da Silva', 'phone': '+55 (27) 90000-0000'})
    token = result.json()['session']
    won = spin(client, token).json()
    assert won['claim_code'] == 'joaodasilva27900000000'
    assert won['spins_left'] == 0
    assert spin(client, token).status_code == 409
    assert client.post('/api/admin/redeem', headers=headers(), json={'claim_code': won['claim_code'].upper()}).status_code == 200
    assert spin(client, token).status_code == 409
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM spins').fetchone()['n'] == 1
        assert conn.execute('SELECT sum(stock) AS stock FROM prize_types').fetchone()['stock'] == 4


def test_legacy_phone_confirmation_checks_digest_without_consuming_spin(database):
    client, connect = database
    token = register(client)
    with connect() as conn:
        conn.execute('UPDATE players SET claim_code_base=NULL')
    assert spin(client, token).status_code == 409
    state = client.get('/api/session', headers={'Authorization': 'Bearer ' + token}).json()
    assert state['needs_phone_confirmation'] is True and state['spins_left'] == 3
    wrong = client.post('/api/session/confirm-phone', json={'session': token, 'phone': '27911111111'})
    assert wrong.status_code == 422
    state = client.post('/api/session/confirm-phone', json={'session': token, 'phone': '+55 (27) 90000-0000'}).json()
    assert state['needs_phone_confirmation'] is False
    won = spin(client, token).json()
    assert won['claim_code'] == 'participanteteste27900000000'


def test_legacy_winner_code_can_be_updated_and_previous_code_still_redeems(database):
    client, connect = database
    token = register(client)
    key = str(uuid4())
    spin(client, token, key)
    previous = 'ABCD' * 8
    with connect() as conn:
        conn.execute('UPDATE players SET claim_code_base=NULL')
        conn.execute('UPDATE prizes SET claim_code=%s', (previous,))
        conn.execute("UPDATE spins SET response=jsonb_set(response,'{claim_code}',to_jsonb(%s::text))", (previous,))
    updated = client.post('/api/session/confirm-phone', json={'session': token, 'phone': '27900000000'}).json()
    assert updated['prize']['claim_code'] == 'participanteteste27900000000'
    assert updated['spins_left'] == 0
    assert spin(client, token).status_code == 409
    assert spin(client, token, key).json()['claim_code'] == previous
    assert client.post('/api/admin/redeem', headers=headers(), json={'claim_code': previous.lower()}).status_code == 200
    assert client.post('/api/admin/redeem', headers=headers(), json={'claim_code': updated['prize']['claim_code']}).status_code == 409


def test_simultaneous_new_spins_stop_immediately_after_win(database):
    client, connect = database
    token = register(client)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: spin(client, token), range(20)))
    assert sum(r.status_code == 200 for r in results) == 1
    assert sum(r.status_code == 409 for r in results) == 19
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM prizes').fetchone()['n'] == 1
        assert conn.execute('SELECT spins_left FROM players').fetchone()['spins_left'] == 0


def state(client, token):
    return client.get('/api/session', headers={'Authorization': 'Bearer ' + token}).json()


def verify_manual(client, connect, token, number=0):
    with connect() as conn:
        player_id = conn.execute('SELECT id FROM players WHERE session_digest=%s', (main.digest(token),)).fetchone()['id']
    return client.post('/api/admin/verify-phone', headers=headers(), json={
        'player_id': player_id, 'phone': f'279{number:08d}', 'checked': True, 'note': 'Contato presencial confirmado'})


def test_verified_referrals_credit_exactly_once_under_concurrency(database, monkeypatch):
    client, connect = database
    monkeypatch.setenv('PHONE_VERIFICATION_REQUIRED', 'true')
    parent = register(client)
    assert state(client, parent)['spins_left'] == 0
    assert spin(client, parent).status_code == 403
    code = state(client, parent)['referral_code']
    result = client.post('/api/register', json={'name': 'Amigo Teste', 'phone': '27900000001', 'referral_code': code})
    assert result.status_code == 201
    friend = result.json()['session']
    assert verify_manual(client, connect, friend, 1).status_code == 200
    assert state(client, parent)['bonus_spins_earned'] == 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: verify_manual(client, connect, parent), range(6)))
    assert all(r.status_code == 200 for r in responses)
    assert state(client, parent)['spins_left'] == 4
    assert state(client, parent)['bonus_spins_earned'] == 1
    assert client.post('/api/register', json={'name': 'Duplicado', 'phone': '27900000001', 'referral_code': code}).status_code == 409
    assert client.post('/api/register', json={'name': 'Eu mesmo', 'phone': '27900000000', 'referral_code': code}).status_code == 422
    assert spin(client, parent).json()['won']
    assert spin(client, parent).status_code == 409


def test_otp_rejects_false_codes_and_preserves_attempts(database, monkeypatch):
    client, connect = database
    monkeypatch.setenv('PHONE_VERIFICATION_REQUIRED', 'true')
    token = register(client)
    from api import participation
    sid = 'VE' + 'a'*32
    monkeypatch.setattr(participation, 'send_code', lambda phone: sid)
    calls = []
    monkeypatch.setattr(participation, 'check_code', lambda sid, code: calls.append(code) or False)
    body = {'session': token, 'phone': '27900000000'}
    assert client.post('/api/verification/start', json={**body, 'phone': '27900000001'}).status_code == 422
    assert client.post('/api/verification/start', json=body).status_code == 200
    assert client.post('/api/verification/start', json=body).status_code == 429
    for _ in range(6):
        assert client.post('/api/verification/check', json={'session': token, 'code': '123456'}).status_code == 422
    assert len(calls) == 5
    assert state(client, token)['phone_verified'] is False
    assert spin(client, token).status_code == 403
    with connect() as conn:
        conn.execute("UPDATE phone_verifications SET sent_at=now()-interval '61 seconds'")
    assert client.post('/api/verification/start', json=body).status_code == 429


def test_otp_approval_and_expiry_and_no_provider_bypass(database, monkeypatch):
    client, connect = database
    from api import participation
    monkeypatch.setenv('PHONE_VERIFICATION_REQUIRED', 'true')
    for key in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_VERIFY_SERVICE_SID'):
        monkeypatch.delenv(key, raising=False)
    token = register(client)
    body = {'session': token, 'phone': '27900000000'}
    assert client.post('/api/verification/start', json=body).status_code == 503
    assert client.post('/api/session/confirm-phone', json=body).status_code == 200
    assert spin(client, token).status_code == 403
    monkeypatch.setattr(participation, 'send_code', lambda phone: 'VE' + 'b'*32)
    monkeypatch.setattr(participation, 'check_code', lambda sid, code: code == '654321')
    assert client.post('/api/verification/start', json=body).status_code == 200
    assert client.post('/api/verification/check', json={'session': token, 'code': '654321'}).json()['phone_verified'] is True
    assert state(client, token)['spins_left'] == 3
    other = register(client, 1)
    assert client.post('/api/verification/start', json={'session': other, 'phone': '27900000001'}).status_code == 200
    with connect() as conn:
        conn.execute("UPDATE phone_verifications SET expires_at=now()-interval '1 second'")
    assert client.post('/api/verification/check', json={'session': other, 'code': '654321'}).status_code == 422
    assert client.get('/api/admin/participants').status_code in (401,403)
    assert client.post('/api/admin/verify-phone', json={'player_id': 1, 'phone': '27900000000', 'checked': True, 'note': 'Teste presencial'}).status_code in (401,403)


def test_referral_cap_and_winners_never_gain_new_spins(database, monkeypatch):
    client, connect = database
    monkeypatch.setenv('REFERRAL_MAX_BONUS_SPINS', '1')
    parent = register(client)
    verify_manual(client, connect, parent)
    code = state(client, parent)['referral_code']
    for number in range(1,4):
        result = client.post('/api/register', json={'name': 'Amigo Teste', 'phone': f'279{number:08d}', 'referral_code': code}).json()
        if number == 3:
            assert spin(client, parent).json()['won'] is True
        assert verify_manual(client, connect, result['session'], number).status_code == 200
    assert state(client, parent)['bonus_spins_earned'] == 1
    assert state(client, parent)['spins_left'] == 0
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM referrals WHERE status='credited'").fetchone()['n'] == 1


def test_rate_limit_counts_rejections_and_persists(database, monkeypatch):
    client, connect = database
    from api import participation
    from fastapi import HTTPException
    monkeypatch.setenv('RATE_LIMIT_ENABLED', 'true')
    participation.limit(connect, 'test', 'private-ip', 1, 3600)
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            participation.limit(connect, 'test', 'private-ip', 1, 3600)
        assert error.value.status_code == 429
    with connect() as conn:
        row = conn.execute("SELECT attempts,key_digest FROM request_limits WHERE scope='test'").fetchone()
        assert row['attempts'] == 3 and 'private-ip' not in row['key_digest']
