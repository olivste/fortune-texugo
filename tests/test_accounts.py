"""Account, wallet and privacy integration tests using a disposable PostgreSQL schema."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from api import accounts,main,security,retention
from test_postgres import database,headers


def make_cpf(number):
    value=f'{100000000+number:09d}'
    for size in (9,10):
        digit=sum(int(value[i])*(size+1-i) for i in range(size))*10%11
        value+=str(0 if digit==10 else digit)
    return value


def payload(n=0,**extra):
    return {'name':'Pessoa Teste','cpf':make_cpf(n),'instagram':f'pessoa_{n}',
            'password':'test-password-123','password_confirmation':'test-password-123',
            'terms_accepted':True,'adult':True,'terms_version':'2026-11-04','privacy_version':'2026-11-04',**extra}


@pytest.fixture
def setup_accounts(database,monkeypatch):
    client,connect=database
    monkeypatch.setenv('LEGACY_ACCOUNTS_ENABLED','false')
    monkeypatch.setenv('PRIZES_ENABLED','false')
    monkeypatch.setenv('DEMO_UNLIMITED_SPINS','false')
    monkeypatch.setenv('COOKIE_SECURE','false')
    monkeypatch.setenv('CPF_HMAC_KEY','test-cpf-hmac-'+'x'*40)
    monkeypatch.setenv('CPF_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setenv('ACCOUNT_REFERRAL_LIMIT','3')
    monkeypatch.setattr(accounts,'now',lambda:datetime(2026,11,4,tzinfo=timezone.utc))
    return client,connect


def actor(n=0,**extra):
    client=TestClient(main.app)
    result=client.post('/api/account/register',json=payload(n,**extra))
    assert result.status_code==201,result.text
    client.headers['X-CSRF-Token']=result.json()['csrf_token']
    return client,result.json()


def spin(client,key=None):
    return client.post('/api/spin',json={'request_id':str(key or uuid4())})


def promo(client,**overrides):
    data={'code':'RISCA10','spins':2,'max_redemptions':50,'starts_at':'2026-11-01T00:00:00Z','expires_at':'2026-12-05T23:59:59Z',**overrides}
    result=client.post('/api/admin/codes',headers=headers(),json=data)
    assert result.status_code==201,result.text
    return result.json()['id']


def redeem(client,code='risca10',key=None):
    return client.post('/api/account/redeem',json={'code':code,'operation_id':str(key or uuid4())})


def test_signup_hash_encryption_cookie_and_ledger(setup_accounts):
    _,connect=setup_accounts
    client,data=actor(instagram=' @PeSsOa.0 ')
    assert data['spins_left']==3 and data['user']['instagram']=='pessoa.0'
    with connect() as conn:
        account=conn.execute('SELECT * FROM accounts').fetchone()
        assert account['password_hash'].startswith('$argon2id$')
        assert security.PASSWORDS.verify(account['password_hash'],'test-password-123')
        assert make_cpf(0) not in account['cpf_cipher']
        assert Fernet(os.environ['CPF_ENCRYPTION_KEY'].encode()).decrypt(account['cpf_cipher'].encode()).decode()==make_cpf(0)
        assert account['accepted_at'] and account['adult_declared_at']
        assert conn.execute('SELECT amount,balance,kind FROM spin_ledger').fetchone()=={'amount':3,'balance':3,'kind':'CADASTRO'}
    serialized=str(data)
    assert 'password_hash' not in serialized and 'cpf_cipher' not in serialized and make_cpf(0) not in serialized
    login=client.post('/api/account/login',json={'cpf':make_cpf(0),'password':'test-password-123'})
    assert 'HttpOnly' in login.headers['set-cookie'] and 'SameSite=lax' in login.headers['set-cookie']


@pytest.mark.parametrize('extra',[
    {'cpf':'11111111111'},{'cpf':'12345678900'},{'cpf':'abc12345678900'},
    {'instagram':'bad..name'},{'instagram':'name with space'},{'instagram':'.invalid'},
    {'password':'short','password_confirmation':'short'},{'password_confirmation':'mismatched'},
    {'adult':False},{'terms_accepted':False},{'name':'Pessoa'},
])
def test_signup_invalid_fields(setup_accounts,extra):
    client,_=setup_accounts
    response=client.post('/api/account/register',json=payload(**extra))
    assert response.status_code==422
    assert 'test-password-123' not in response.text


def test_cpf_and_instagram_unique_and_normalized(setup_accounts):
    client,_=setup_accounts
    actor()
    assert client.post('/api/account/register',json=payload(1,cpf=make_cpf(0))).status_code==409
    assert client.post('/api/account/register',json=payload(2,instagram=' @PESSOA_0 ')).status_code==409


def test_login_bad_password_logout_csrf_and_expiry(setup_accounts):
    _,connect=setup_accounts
    client,data=actor()
    assert client.post('/api/account/login',json={'cpf':make_cpf(0),'password':'wrong-password'}).status_code==401
    client.headers.pop('X-CSRF-Token')
    assert spin(client).status_code==403
    client.headers['X-CSRF-Token']=data['csrf_token']
    assert client.post('/api/account/logout',json={}).status_code==200
    assert client.get('/api/account/me').status_code==401
    assert spin(client).status_code==401
    result=client.post('/api/account/login',json={'cpf':make_cpf(0),'password':'test-password-123'})
    assert result.status_code==200
    client.headers['X-CSRF-Token']=result.json()['csrf_token']
    with connect() as conn:
        conn.execute("UPDATE account_sessions SET expires_at=now()-interval '1 second'")
    assert spin(client).status_code==401


def test_no_login_or_legacy_bypass_and_cross_origin(setup_accounts):
    client,_=setup_accounts
    assert spin(client).status_code==401
    assert client.post('/api/register',json={'name':'Pessoa Teste','phone':'27900000000'}).status_code==410
    assert client.post('/api/account/register',headers={'Origin':'https://evil.example'},json=payload()).status_code==403
    assert client.post('/api/account/login',data={'cpf':make_cpf(0),'password':'secret'}).status_code==415


def test_three_spins_concurrent_exact_debit_and_replay(setup_accounts):
    _,connect=setup_accounts
    client,_=actor()
    key=uuid4()
    first=spin(client,key)
    assert first.status_code==200 and first.json()['spins_left']==2
    assert spin(client,key).json()==first.json()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:spin(client),range(8)))
    assert sum(r.status_code==200 for r in results)==2
    assert sum(r.status_code==409 for r in results)==6
    with connect() as conn:
        assert conn.execute('SELECT spins_left FROM players').fetchone()['spins_left']==0
        assert conn.execute("SELECT count(*) AS n FROM spin_ledger WHERE kind='GIRO_REALIZADO'").fetchone()['n']==3
        assert conn.execute('SELECT sum(amount) AS n FROM spin_ledger').fetchone()['n']==0


def test_referrals_automatic_once_without_cap(setup_accounts):
    _,connect=setup_accounts
    parent,data=actor()
    for n in range(1,6):
        actor(n,referral_instagram=' @PESSOA_0 ')
    current=parent.get('/api/account/me').json()
    assert current['referral_code']=='@pessoa_0' and current['referrals_total']==5
    assert current['bonus_spins_earned']==5 and current['referral_bonus_remaining'] is None
    assert current['spins_left']==8 and current['referrals_pending']==0
    assert parent.post('/api/account/register',json=payload(1,referral_instagram='pessoa_0')).status_code==409
    with connect() as conn:
        accounts.credit_referral(conn,2)
        assert conn.execute("SELECT count(*) AS n FROM spin_ledger WHERE kind='INDICACAO'").fetchone()['n']==5


@pytest.mark.parametrize('referral',['@pessoa_0','@inexistente'])
def test_self_referral_and_missing_referrer(setup_accounts,referral):
    client,_=setup_accounts
    assert client.post('/api/account/register',json=payload(referral_instagram=referral)).status_code==422


def test_concurrent_referrals_credit_every_new_friend(setup_accounts):
    parent,_=actor()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda n:actor(n,referral_instagram='pessoa_0')[1],range(1,7)))
    assert len(results)==6
    assert parent.get('/api/account/me').json()['spins_left']==9


def test_valid_promo_idempotency_and_duplicate(setup_accounts):
    client,_=actor();promo(client)
    key=uuid4();result=redeem(client,' risca10 ',key)
    assert result.status_code==200 and result.json()['credited']==2 and result.json()['spins_left']==5
    assert redeem(client,'RISCA10',key).json()['replayed'] is True
    assert redeem(client).status_code==409
    assert client.get('/api/account/me').json()['spins_left']==5


@pytest.mark.parametrize('settings,code,message',[
    ({},'MISSING','não existe'),({'active':False},'RISCA10','não existe'),
    ({'starts_at':'2026-10-01T00:00:00Z','expires_at':'2026-11-01T00:00:00Z'},'RISCA10','expirou'),
    ({'starts_at':'2026-12-01T00:00:00Z'},'RISCA10','não existe'),
])
def test_unavailable_promos(setup_accounts,settings,code,message):
    client,_=actor();promo(client,**settings)
    result=redeem(client,code)
    assert result.status_code in (404,409) and message in result.json()['detail']
    assert client.get('/api/account/me').json()['spins_left']==3


def test_last_promo_concurrent_global_limit(setup_accounts):
    actors=[actor(n)[0] for n in range(8)]
    promo(actors[0],max_redemptions=1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(redeem,actors))
    assert sum(r.status_code==200 for r in results)==1
    assert sum(r.status_code==409 for r in results)==7
    with setup_accounts[1]() as conn:
        assert conn.execute('SELECT redeemed_count FROM promo_codes').fetchone()['redeemed_count']==1
        assert conn.execute('SELECT count(*) AS n FROM promo_redemptions').fetchone()['n']==1


def test_same_user_concurrent_promo_redeems_once(setup_accounts):
    client,_=actor();promo(client)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:redeem(client),range(6)))
    assert sum(r.status_code==200 for r in results)==1
    assert client.get('/api/account/me').json()['spins_left']==5


def test_admin_balance_adjustment_audit_idempotence_and_suspension(setup_accounts):
    client,data=actor();uid=data['user']['id'];key=str(uuid4())
    body={'amount':2,'reason':'Bônus autorizado','operation_id':key}
    assert client.post(f'/api/admin/users/{uid}/balance',json=body).status_code==403
    path=f'/api/admin/users/{uid}/balance'
    assert client.post(path,headers=headers(),json=body).json()['spins_left']==5
    assert client.post(path,headers=headers(),json=body).json()['spins_left']==5
    assert client.post(path,headers=headers(),json={**body,'amount':3}).status_code==409
    assert client.post(path,headers=headers(),json={'amount':-6,'reason':'Remoção teste','operation_id':str(uuid4())}).status_code==409
    assert client.post(path,headers=headers(),json={'amount':-2,'reason':'Remoção teste','operation_id':str(uuid4())}).json()['spins_left']==3
    assert client.put(f'/api/admin/users/{uid}/status',headers=headers(),json={'status':'suspended','reason':'Teste suspensão'}).status_code==200
    assert spin(client).status_code in (401,403)
    assert client.post('/api/account/login',json={'cpf':make_cpf(0),'password':'test-password-123'}).status_code==403
    assert client.get('/api/admin/audit',headers=headers()).json()


@pytest.mark.parametrize('path',['/api/admin/codes','/api/admin/users','/api/admin/referrals','/api/admin/audit','/api/admin/suspicious','/api/admin/code-redemptions.csv','/api/admin/retention'])
def test_admin_routes_forbidden(setup_accounts,path):
    assert setup_accounts[0].get(path).status_code==403


def test_code_edits_preserve_old_redemptions_and_csv(setup_accounts):
    client,_=actor();pid=promo(client);redeem(client)
    settings=client.get('/api/admin/codes',headers=headers()).json()['items'][0]
    edit={key:settings[key] for key in ('code','spins','max_redemptions','starts_at','expires_at','active','description','version')}
    assert client.put(f'/api/admin/codes/{pid}',headers=headers(),json={**edit,'spins':4,'active':False}).status_code==200
    assert client.put(f'/api/admin/codes/{pid}',headers=headers(),json=edit).status_code==409
    history=client.get(f'/api/admin/codes/{pid}/redemptions',headers=headers()).json()
    assert history[0]['spins']==2
    exported=client.get('/api/admin/code-redemptions.csv',headers=headers())
    assert exported.status_code==200 and 'RISCA10' in exported.text and make_cpf(0) not in exported.text


def test_retention_deletes_all_cpf_identifiers_and_managed_backup(setup_accounts,tmp_path,monkeypatch):
    client,connect=setup_accounts
    user,data=actor()
    archive=tmp_path/'test.backup';archive.write_text('fake encrypted archive')
    (tmp_path/'test.fortune-backup.json').write_text('{"archive":"test.backup","expires_at":"2026-12-05T03:00:00+00:00"}')
    monkeypatch.setenv('MANAGED_BACKUP_DIRECTORY',str(tmp_path))
    assert retention.cleanup(connect,accounts.DEADLINE-timedelta(seconds=1))['deleted']==0
    assert retention.cleanup(connect,accounts.DEADLINE)['deleted']==1
    assert not archive.exists()
    assert retention.cleanup(connect,accounts.DEADLINE)['deleted']==0
    with connect() as conn:
        row=conn.execute('SELECT cpf_cipher,cpf_lookup,cpf_last2,cpf_deleted_at FROM accounts').fetchone()
        assert row['cpf_cipher'] is row['cpf_lookup'] is row['cpf_last2'] is None
        assert row['cpf_deleted_at']
    assert user.post('/api/account/login',json={'instagram':'pessoa_0','password':'test-password-123'}).status_code==200
    assert user.post('/api/account/login',json={'cpf':make_cpf(0),'password':'test-password-123'}).status_code==401
    monkeypatch.setattr(accounts,'now',lambda:accounts.DEADLINE)
    assert client.post('/api/account/register',json=payload(1)).status_code==409


def test_documented_hold_expires_and_cleanup_continues(setup_accounts):
    client,connect=setup_accounts
    user,data=actor();uid=data['user']['id']
    assert client.put(f'/api/admin/users/{uid}/cpf-hold',headers=headers(),json={'reason':'Conservação documentada para teste','legal_basis':'Obrigação legal documentada','until_at':'2026-12-06T00:00:00Z'}).status_code==200
    assert retention.cleanup(connect,accounts.DEADLINE)['deleted']==0
    assert retention.cleanup(connect,accounts.DEADLINE+timedelta(days=2))['deleted']==1


def test_reapply_migration_preserves_accounts_balances_codes_and_login(setup_accounts):
    client,connect=setup_accounts
    user,_=actor();promo(user);redeem(user);spin(user)
    with connect() as conn:
        conn.execute(main.SCHEMA,prepare=False)
        conn.execute((main.ROOT/'api/sql/accounts.sql').read_text(),prepare=False)
    assert user.get('/api/account/me').json()['spins_left']==4
    with connect() as conn:
        assert conn.execute('SELECT sum(amount) AS balance FROM spin_ledger').fetchone()['balance']==4
    assert user.post('/api/account/login',json={'cpf':make_cpf(0),'password':'test-password-123'}).status_code==200
    assert client.get('/api/admin/codes',headers=headers()).json()['metrics']['redemptions']==1


def test_winner_closes_remaining_wallet_and_blocks_bonuses(setup_accounts,monkeypatch):
    client,connect=setup_accounts
    user,data=actor();promo(user)
    monkeypatch.setenv('PRIZES_ENABLED','true')
    result=spin(user)
    assert result.status_code==200 and result.json()['won'] is True
    assert result.json()['spins_left']==0
    assert spin(user).status_code==409
    assert redeem(user).status_code==409
    actor(1,referral_instagram='pessoa_0')
    assert user.get('/api/account/me').json()['spins_left']==0
    with connect() as conn:
        assert conn.execute('SELECT sum(amount) AS balance FROM spin_ledger WHERE player_id=%s',(data['user']['id'],)).fetchone()['balance']==0


def test_login_rate_limit_persists_failed_attempts(setup_accounts,monkeypatch):
    client,_=actor()
    monkeypatch.setenv('RATE_LIMIT_ENABLED','true')
    for _ in range(8):
        assert client.post('/api/account/login',json={'cpf':make_cpf(0),'password':'incorrect-password'}).status_code==401
    assert client.post('/api/account/login',json={'cpf':make_cpf(0),'password':'test-password-123'}).status_code==429


def test_secure_cookie_document_versions_and_no_sensitive_spin_snapshots(setup_accounts,monkeypatch):
    client,connect=setup_accounts
    assert client.post('/api/account/register',json=payload(terms_version='old')).status_code==409
    actor_client,_=actor()
    result=spin(actor_client)
    assert result.status_code==200 and 'user' not in result.json()
    with connect() as conn:
        assert 'cpf_masked' not in str(conn.execute('SELECT response FROM spins').fetchone()['response'])
    monkeypatch.setenv('COOKIE_SECURE','true')
    response=client.post('/api/account/login',json={'cpf':make_cpf(0),'password':'test-password-123'})
    assert 'Secure' in response.headers['set-cookie'] and 'HttpOnly' in response.headers['set-cookie']


def test_concurrent_duplicate_signup_credits_only_one_referral(setup_accounts):
    _,connect=setup_accounts
    parent,_=actor()
    # Separate clients without lifespan: schema already belongs to the fixture.
    def request_only(_):
        client=TestClient(main.app)
        return client.post('/api/account/register',json=payload(1,referral_instagram='pessoa_0')).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(request_only,range(6)))
    assert results.count(201)==1 and results.count(409)==5
    assert parent.get('/api/account/me').json()['bonus_spins_earned']==1
    with connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM account_referrals').fetchone()['n']==1


def test_coupon_created_without_dates_is_immediately_redeemable(setup_accounts):
    client,_=actor()
    response=client.post('/api/admin/codes',headers=headers(),json={'code':'SEMPRAZO','spins':2,'max_redemptions':10})
    assert response.status_code==201
    row=client.get('/api/admin/codes',headers=headers()).json()['items'][0]
    assert row['expires_at'] is None
    assert client.get('/api/admin/codes',headers=headers()).json()['metrics']['active']==1
    assert redeem(client,'SEMPRAZO').json()['spins_left']==5
    settings={key:row[key] for key in ('code','spins','max_redemptions','starts_at','expires_at','active','description','version')}
    settings['version']+=1  # A redemption increments the version.
    assert client.put('/api/admin/codes/'+str(row['id']),headers=headers(),json=settings).status_code==200


def test_prize_code_uses_name_and_last_three_cpf_digits(setup_accounts,monkeypatch):
    _,connect=setup_accounts
    user,data=actor(name='João da Silva')
    monkeypatch.setenv('PRIZES_ENABLED','true')
    key=uuid4()
    result=spin(user,key)
    assert result.status_code==200
    code='joaodasilva'+make_cpf(0)[-3:]
    assert result.json()['claim_code']==code
    assert spin(user,key).json()['claim_code']==code
    assert user.get('/api/account/me').json()['prize']['claim_code']==code
    assert user.post('/api/admin/redeem',headers=headers(),json={'claim_code':code.upper()}).status_code==200
    assert user.post('/api/admin/redeem',headers=headers(),json={'claim_code':code}).status_code==409
    with connect() as conn:
        assert conn.execute('SELECT claim_code_base FROM players').fetchone()['claim_code_base']==code


def test_prize_code_collision_preserves_previously_issued_code(setup_accounts,monkeypatch):
    _,connect=setup_accounts
    user,data=actor()
    with connect() as conn:
        legacy=conn.execute("INSERT INTO players(name,session_digest,claim_code_base) VALUES('Pessoa Teste',%s,'old') RETURNING id",('x'*64,)).fetchone()['id']
        code='pessoateste'+make_cpf(0)[-3:]
        conn.execute('INSERT INTO prizes(player_id,claim_code) VALUES(%s,%s)',(legacy,code))
    monkeypatch.setenv('PRIZES_ENABLED','true')
    result=spin(user)
    assert result.status_code==200 and result.json()['won'] is True
    assert result.json()['claim_code']==code+'id'+str(data['user']['id'])
    with connect() as conn:
        assert conn.execute('SELECT claim_code FROM prizes WHERE player_id=%s',(legacy,)).fetchone()['claim_code']==code
