"""Full browser check against disposable PostgreSQL; never uses the campaign database."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from cryptography.fernet import Fernet
from playwright.sync_api import sync_playwright
import httpx


def cpf(n):
    value=f'{100000000+n:09d}'
    for size in (9,10):
        digit=sum(int(value[i])*(size+1-i) for i in range(size))*10%11
        value+=str(0 if digit==10 else digit)
    return value


def signup(page,n):
    page.get_by_role('button',name='ENTRAR OU CADASTRAR').click()
    page.get_by_role('button',name='CRIAR MINHA CONTA').click()
    page.locator('#name').fill('Pessoa Teste')
    page.locator('#cpf').fill(cpf(n));page.locator('#instagram').fill(f'visual_{n}')
    page.locator('#password').fill('browser-test-password');page.locator('#password-confirmation').fill('browser-test-password')
    page.locator('#adult').check();page.locator('#accept-terms').check()
    page.locator('#form').get_by_role('button').click()
    page.locator('#account-toolbar').wait_for(state='visible')
    assert page.locator('#remaining').inner_text()=='3'


def main():
    bindir=Path(os.environ.get('PG_BINDIR','/opt/homebrew/opt/postgresql@16/bin'))
    with tempfile.TemporaryDirectory(prefix='fortune-browser-') as directory:
        root=Path(directory);data=root/'pg';sock=root/'socket';sock.mkdir()
        subprocess.run([str(bindir/'initdb'),'-D',str(data),'-A','trust','-U','browser_test','--no-locale','-E','UTF8'],check=True,stdout=subprocess.DEVNULL)
        subprocess.run([str(bindir/'pg_ctl'),'-D',str(data),'-l',str(root/'pg.log'),'-o',f"-F -h '' -k {sock}",'-w','start'],check=True,stdout=subprocess.DEVNULL)
        with socket.socket() as socket_probe:
            socket_probe.bind(('127.0.0.1',0));port=socket_probe.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        env={**os.environ,'DATABASE_URL':'postgresql://browser_test@/postgres?'+urlencode({'host':str(sock)}),
             'PHONE_PEPPER':'browser-test-pepper-'+'x'*40,'ADMIN_API_KEY':'browser-test-admin-'+'x'*40,
             'CPF_HMAC_KEY':'browser-test-cpf-'+'x'*40,'CPF_ENCRYPTION_KEY':Fernet.generate_key().decode(),
             'PRIZES_ENABLED':'false','DEMO_UNLIMITED_SPINS':'false','COOKIE_SECURE':'false',
             'PUBLIC_ORIGIN':origin,'LEGACY_ACCOUNTS_ENABLED':'false','RATE_LIMIT_ENABLED':'false'}
        log=(root/'app.log').open('w')
        app=subprocess.Popen([sys.executable,'-m','uvicorn','api.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    if httpx.get(origin+'/health').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise RuntimeError('Disposable API failed to start')
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                context=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.set_viewport_size({'width':1440,'height':900});page.goto(origin)
                page.evaluate('document.fonts.ready')
                assert page.evaluate("document.fonts.check('24px ChunkFive')")
                assert 'ChunkFive' in page.locator('header b').evaluate('(el)=>getComputedStyle(el).fontFamily')
                page.get_by_role('button',name='ENTRAR OU CADASTRAR').click();page.get_by_role('button',name='CRIAR MINHA CONTA').click()
                bounds=page.locator('#registration').bounding_box();assert bounds['width']<=600 and bounds['height']<=860
                assert page.locator('#cpf').bounding_box()['x']<page.locator('#instagram').bounding_box()['x']
                page.screenshot(path='/tmp/fortune-registration-desktop.png')
                page.locator('#registration-close').click();page.set_viewport_size({'width':390,'height':844});signup(page,0)
                assert page.locator('#copy-referral-link').is_visible()
                assert page.locator('#my-referral-code').inner_text()=='@visual_0'
                assert 'siga' in page.locator('.follow-notice').inner_text()
                assert 'sem limite' in page.locator('#referral-total').inner_text()
                with httpx.Client(base_url=origin) as admin:
                    response=admin.post('/api/admin/codes',headers={'X-Admin-Key':env['ADMIN_API_KEY']},json={'code':'VISUAL2','spins':2,'max_redemptions':10,'starts_at':'2026-11-01T00:00:00Z','expires_at':'2026-12-05T23:59:59Z'})
                    assert response.status_code==201
                page.get_by_role('button',name='RESGATAR GIROS',exact=True).click();page.locator('#promo-code').fill('visual2');page.locator('#promo-form button').click()
                page.wait_for_function("document.getElementById('remaining').textContent==='5'")
                page.locator('#redeem-close').click();page.locator('#spin').click()
                page.wait_for_function("document.getElementById('remaining').textContent==='4' && !document.getElementById('spin').disabled")
                page.reload();page.locator('#account-toolbar').wait_for(state='visible');assert page.locator('#remaining').inner_text()=='4'
                context.grant_permissions(['clipboard-read','clipboard-write']);page.locator('#copy-referral-link').click();page.wait_for_function("document.getElementById('referral-status').textContent==='Link de indicação copiado!'");invite=page.evaluate('navigator.clipboard.readText()');assert invite==origin+'/?ref=%40visual_0'
                other=browser.new_context(viewport={'width':320,'height':760});friend=other.new_page();friend.goto(invite);friend.wait_for_function("document.getElementById('referral-input').value==='visual_0' && !document.getElementById('open-registration').disabled");signup(friend,1)
                page.locator('#refresh-referrals').click();page.wait_for_function("document.getElementById('remaining').textContent==='5'")
                for width in (320,390,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow at {width}'
                    page.locator('.prize-panel > summary').click() if not page.locator('.prize-panel').evaluate('(el)=>el.open') else None
                    assert page.locator('#prize-options li').count()>0
                    ends=page.locator('#prize-options strong').evaluate_all('(els)=>els.map(el=>el.getBoundingClientRect().right)')
                    assert max(ends)-min(ends)<1
                page.wait_for_function("document.querySelector('.machine').getBoundingClientRect().width>=440")
                page.screenshot(path='/tmp/fortune-game-desktop.png',full_page=True)
                page.get_by_role('button',name='MEU PERFIL',exact=True).click();page.locator('#profile-balance').wait_for(state='visible');assert page.locator('#wallet-history').count()==0;page.locator('#profile-close').click()
                page.get_by_role('button',name='SAIR',exact=True).click();page.locator('#account-toolbar').wait_for(state='hidden')
                page.locator('#spin').click();page.locator('#login-dialog').wait_for(state='visible');page.locator('#login-identifier').fill(cpf(0));page.locator('#login-password').fill('browser-test-password');page.locator('#login-form button').click();page.locator('#account-toolbar').wait_for(state='visible')
                adminpage=context.new_page();adminpage.on('pageerror',lambda error:errors.append(str(error)));adminpage.goto(origin+'/admin.html');adminpage.locator('#admin-key').fill(env['ADMIN_API_KEY']);adminpage.locator('#admin-form button').click();adminpage.locator('#dashboard').wait_for(state='visible')
                assert adminpage.locator('#account-users li').count()==2
                assert 'VISUAL2' in adminpage.locator('#promo-list').inner_text()
                adminpage.locator('#probability').fill('37.5')
                adminpage.get_by_role('button',name='Salvar porcentagem de ganho',exact=True).click()
                adminpage.wait_for_function("document.getElementById('probability-status').textContent==='Porcentagem salva com sucesso.'")
                saved=adminpage.request.get(origin+'/api/admin/settings',headers={'X-Admin-Key':env['ADMIN_API_KEY']}).json()
                assert saved['probability_percent']==37.5
                assert adminpage.locator('#create-start,#create-end').count()==0
                adminpage.locator('#create-code').fill('SEMDATA');adminpage.locator('#create-spins').fill('2');adminpage.locator('#create-limit').fill('10')
                adminpage.locator('#promo-create-form button').click()
                adminpage.wait_for_function("document.getElementById('status').textContent==='Código criado.'")
                items=adminpage.request.get(origin+'/api/admin/codes',headers={'X-Admin-Key':env['ADMIN_API_KEY']}).json()['items']
                assert next(item for item in items if item['code']=='SEMDATA')['expires_at'] is None
                adminpage.reload();adminpage.locator('#admin-key').fill(env['ADMIN_API_KEY']);adminpage.locator('#admin-form button').click();adminpage.locator('#dashboard').wait_for(state='visible')
                assert adminpage.locator('#probability').input_value()=='37.5'
                assert 'não concede prêmios reais' in adminpage.locator('#probability-mode').inner_text()
                assert not errors,errors
                for path in ('/termos','/privacidade'):
                    assert httpx.get(origin+path).status_code==200
                browser.close()
            print('Browser checks passed: signup, cookies/reload, referral, promo, spin, login/logout, profile, admin, legal pages and widths 320/390/1440. Disposable data removed.')
        finally:
            app.terminate();app.wait(timeout=10);log.close()
            subprocess.run([str(bindir/'pg_ctl'),'-D',str(data),'-m','immediate','-w','stop'],check=True,stdout=subprocess.DEVNULL)


if __name__=='__main__':
    main()
