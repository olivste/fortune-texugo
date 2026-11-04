const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

async function browser(fetch, stored = {}, assets = {}, clipboard, href = 'https://riscabet.online/') {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', disabled: false, textContent: '', children: [], open: false,
      showModal() { this.open = true; },
      close() { this.open = false; },
      classList: {add() {}, remove() {}, toggle() {}},
      style: {setProperty() {}},
      querySelector: () => element('submit'),
      closest: () => element('machine'),
    });
    return elements.get(id);
  };
  element('spin').disabled = true;
  element('reels').children = Array.from({length: 3}, () => ({
    children: Array.from({length: 3}, () => ({classList: {toggle(name, value) {this[name] = value;}}})),
    classList: {add() {}, remove() {}},
  }));
  const storage = new Map(Object.entries(stored));
  let ids = 0;
  const context = vm.createContext({
    window: {matchMedia: () => ({matches: true})},
    document: {getElementById: element, querySelectorAll: () => [], documentElement: element('root')},
    location: {protocol: 'https:', href},
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    crypto: {randomUUID: () => `request-${++ids}`},
    navigator: clipboard ? {clipboard: {writeText: clipboard}} : {},
    URL, fetch, setTimeout: () => 0, console,
  });
  vm.runInContext(fs.readFileSync('assets/content.js', 'utf8'), context);
  Object.assign(context.window.FORTUNE_ASSETS, assets);
  vm.runInContext(fs.readFileSync('assets/game.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  return {element, storage};
}
const response = body => ({ok: true, json: async () => body});
const state = {stock: 5, demo: false};
const grid = [['ficha','copo','carta'], ['carta','copo','ficha'], ['texugo','copo','ficha']];

test('lost spin response retries the same request ID and clears it after success', async () => {
  const requests = [];
  const page = await browser(async (url, options) => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/register')) return response({...state, session: 'test-session', spins_left: 3});
    if (url.endsWith('/spin')) {
      requests.push(JSON.parse(options.body));
      if (requests.length === 1) throw new TypeError('Network failure');
      return response({...state, stock: 4, won: true, spins_left: 2, claim_code: 'A'.repeat(32), grid});
    }
    throw Error(url);
  });
  page.element('name').value = 'Ana';
  page.element('phone').value = '27999999999';
  await page.element('form').onsubmit({preventDefault() {}});
  await page.element('spin').onclick();
  assert.ok(page.storage.has('fortune_pending_spin'));
  await page.element('spin').onclick();
  assert.deepEqual(requests[0], requests[1]);
  assert.equal(page.storage.has('fortune_pending_spin'), false);
  assert.equal(page.element('remaining').textContent, 0);
  assert.match(page.element('winner').textContent, /A{32}/);
  assert.equal(page.element('prize-popup').open, true);
  assert.match(page.element('prize-title').textContent, /Parabéns/);
  assert.match(page.element('prize-instructions').textContent, /Tire um print.*@risca.faca/);
  assert.equal(page.element('prize-code').textContent, 'A'.repeat(32));
  page.element('prize-close').onclick();
  assert.equal(page.element('prize-popup').open, false);
  page.element('prize-details').onclick();
  assert.equal(page.element('prize-popup').open, true);
});

test('reload recovers a winning final spin and blocks further spins', async () => {
  let replayed;
  const pending = {session: 'test-session', request_id: 'pending-final-spin'};
  const prize = {claim_code: 'B'.repeat(32), redeemed_at: null};
  const page = await browser(async (url, options) => {
    if (url.endsWith('/config')) return response({...state, stock: 4});
    if (url.endsWith('/session')) return response({...state, stock: 4, spins_left: 0, prize});
    if (url.endsWith('/spin')) {
      replayed = JSON.parse(options.body);
      return response({...state, stock: 4, spins_left: 0, won: true, ...prize, grid});
    }
    throw Error(url);
  }, {fortune_demo_session: 'test-session', fortune_pending_spin: JSON.stringify(pending)});
  assert.equal(page.element('spin').disabled, true);
  assert.match(page.element('winner').textContent, /B{32}/);
  await page.element('spin').onclick();
  assert.equal(replayed, undefined);
  assert.equal(page.storage.has('fortune_pending_spin'), false);
  assert.equal(page.element('spin').disabled, true);
});

test('API outage blocks registration rather than granting local promotional spins', async () => {
  const page = await browser(async () => { throw new TypeError('Offline'); });
  assert.equal(page.element('submit').disabled, true);
  assert.equal(page.element('spin').disabled, true);
  assert.match(page.element('message').textContent, /API indisponível/);
});


test('ticket invitation appears only after all three losing spins', async () => {
  let spins = 3;
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/register')) return response({...state, session: 'test-session', spins_left: 3});
    if (url.endsWith('/spin')) return response({...state, spins_left: --spins, won: false, grid});
    throw Error(url);
  });
  page.element('name').value = 'Ana';
  page.element('phone').value = '27999999999';
  await page.element('form').onsubmit({preventDefault() {}});
  for (let i = 0; i < 3; i++) {
    await page.element('spin').onclick();
    assert.equal(!page.element('end-of-spins').open, i < 2);
  }
  assert.match(page.element('end-message').textContent, /mais prêmios no dia da Calourada/);
  assert.equal(page.element('end-ticket').href, 'https://www.guicheweb.com.br/64-calourada-da-engenharia-ufes_56060');
  page.element('end-close').onclick();
  assert.equal(page.element('end-of-spins').open, false);
});

test('a winner on an earlier spin does not see the losing invitation at the end', async () => {
  let spins = 3;
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/register')) return response({...state, session: 'test-session', spins_left: 3});
    if (url.endsWith('/spin')) return response({...state, spins_left: --spins, won: spins === 2, claim_code: 'C'.repeat(32), grid});
    throw Error(url);
  });
  page.element('name').value = 'Ana';
  page.element('phone').value = '27999999999';
  await page.element('form').onsubmit({preventDefault() {}});
  for (let i = 0; i < 3; i++) await page.element('spin').onclick();
  assert.equal(!page.element('end-of-spins').open, true);
  assert.match(page.element('winner').textContent, /C{32}/);
});

test('restoring a completed session shows the invitation only for non-winners without pending spins', async () => {
  for (const [prize, pending] of [[null, false], [null, true], [{claim_code: 'D'.repeat(32)}, false]]) {
    const stored = {fortune_demo_session: 'test-session'};
    if (pending) stored.fortune_pending_spin = JSON.stringify({session: 'test-session', request_id: 'pending'});
    const page = await browser(async url => {
      if (url.endsWith('/config')) return response(state);
      if (url.endsWith('/session')) return response({...state, spins_left: 0, prize});
      throw Error(url);
    }, stored);
    assert.equal(!page.element('end-of-spins').open, Boolean(prize || pending));
  }
});

test('unlimited demo restores an exhausted session and keeps spinning without the ending popup', async () => {
  let spins = 0;
  const demo = {stock: 5, demo: true, unlimited_spins: true};
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(demo);
    if (url.endsWith('/session')) return response({...demo, spins_left: 0, prize: null});
    if (url.endsWith('/spin')) {
      spins++;
      return response({...demo, spins_left: 3, won: false, grid});
    }
    throw Error(url);
  }, {fortune_demo_session: 'test-session'});
  assert.equal(page.element('spin').disabled, false);
  for (let i = 0; i < 5; i++) await page.element('spin').onclick();
  assert.equal(spins, 5);
  assert.equal(page.element('remaining').textContent, '∞');
  assert.equal(page.element('end-of-spins').open, false);
  assert.equal(page.element('spin').disabled, false);
});


test('restored prize shows contact instructions, while redeemed prizes do not reopen the popup', async () => {
  for (const redeemed of [false, true]) {
    const page = await browser(async url => {
      if (url.endsWith('/config')) return response(state);
      if (url.endsWith('/session')) return response({...state, spins_left: 0,
        prize: {claim_code: 'E'.repeat(32), redeemed_at: redeemed ? '2026-11-03T12:00:00Z' : null}});
      throw Error(url);
    }, {fortune_demo_session: 'test-session'}, {instagramUrl: 'https://www.instagram.com/fortune_test_profile/'});
    assert.equal(page.element('prize-popup').open, !redeemed);
    assert.equal(page.element('prize-details').hidden, redeemed);
    assert.equal(page.element('prize-instagram').href, 'https://www.instagram.com/fortune_test_profile/');
    assert.equal(page.element('prize-instagram').hidden, false);
    assert.equal(page.element('prize-code').textContent, 'E'.repeat(32));
  }
});

test('custom prize name, symbol, stock and configured chance reach the public interface', async () => {
  const campaign = {...state, total_stock: 8, stock: 8, probability: 0.2,
    prize_options: [{name: 'Pulseira de entrada no bar', stock: 3}]};
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(campaign);
    if (url.endsWith('/register')) return response({...campaign, session: 'test-session', spins_left: 3});
    if (url.endsWith('/spin')) return response({...campaign, stock: 7, spins_left: 2, won: true,
      prize_name: 'Pulseira de entrada no bar', prize_symbol: 'texugo', claim_code: 'F'.repeat(32), grid});
    throw Error(url);
  });
  page.element('name').value = 'Ana'; page.element('phone').value = '27999999999';
  await page.element('form').onsubmit({preventDefault() {}});
  await page.element('spin').onclick();
  assert.match(page.element('prize-title').textContent, /Pulseira de entrada no bar/);
  assert.equal(page.element('prize-art').src, 'assets/simbolos/texugo.svg');
  assert.equal(page.element('stock').textContent, '7 / 8');
  assert.match(page.element('prize-rules').textContent, /20%/);
});


test('copy button copies the exact code and a winner cannot request another spin', async () => {
  let copied, spins = 0;
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/session')) return response({...state, spins_left: 0,
      prize: {claim_code: 'ana27900000000', redeemed_at: null}});
    if (url.endsWith('/spin')) spins++;
    throw Error(url);
  }, {fortune_demo_session: 'test-session'}, {}, async value => { copied = value; });
  await page.element('copy-prize-code').onclick();
  assert.equal(copied, 'ana27900000000');
  assert.equal(page.element('copy-code-status').textContent, 'Código copiado!');
  assert.equal(page.element('spin').disabled, true);
  await page.element('spin').onclick();
  assert.equal(spins, 0);
});

test('clipboard failures leave the code available for manual copying', async () => {
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/session')) return response({...state, spins_left: 0,
      prize: {claim_code: 'ana27900000000', redeemed_at: null}});
    throw Error(url);
  }, {fortune_demo_session: 'test-session'});
  await page.element('copy-prize-code').onclick();
  assert.match(page.element('copy-code-status').textContent, /Selecione o código/);
  assert.equal(page.element('prize-code').textContent, 'ana27900000000');
  assert.equal(page.element('copy-prize-code').disabled, false);
});

test('a reset session clears the old token and pending spin, allowing a fresh registration', async () => {
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/api/session')) return {ok: false, status: 401};
    if (url.endsWith('/register')) return response({...state, session: 'new-session', spins_left: 3});
    throw Error(url);
  }, {fortune_demo_session: 'old-session', fortune_pending_spin: JSON.stringify({session: 'old-session', request_id: 'old-spin'})});
  assert.equal(page.storage.has('fortune_demo_session'), false);
  assert.equal(page.storage.has('fortune_pending_spin'), false);
  page.element('name').value = 'Ana';page.element('phone').value = '27900000000';
  await page.element('form').onsubmit({preventDefault() {}});
  assert.equal(page.storage.get('fortune_demo_session'), 'new-session');
  assert.equal(page.element('spin').disabled, false);
});


test('WILD from the server is rendered as the Riquelme wildcard in all three cells', async () => {
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/session')) return response({...state, spins_left: 3, prize: null});
    if (url.endsWith('/spin')) return response({...state, spins_left: 0, won: true,
      claim_code: 'ana27900000000', grid: [['ficha','copo','carta'],['wild','wild','wild'],['carta','copo','ficha']]});
    throw Error(url);
  }, {fortune_demo_session: 'test-session'});
  await page.element('spin').onclick();
  for (const cell of page.element('reels').children[1].children) {
    assert.match(cell.innerHTML, /assets\/simbolos\/wild.svg/);
    assert.equal(cell.classList['is-wild'], true);
  }
  assert.equal(page.element('spin').disabled, true);
});


test('registration opens in a dialog and disappears after a successful signup', async () => {
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/register')) return response({...state, session: 'new-session', spins_left: 3});
    throw Error(url);
  });
  assert.equal(page.element('open-registration').disabled, false);
  page.element('open-registration').onclick();
  assert.equal(page.element('registration').open, true);
  page.element('registration-close').onclick();
  assert.equal(page.element('registration').open, false);
  page.element('open-registration').onclick();
  page.element('name').value = 'Ana';page.element('phone').value = '27900000000';
  await page.element('form').onsubmit({preventDefault() {}});
  assert.equal(page.element('registration').open, false);
  assert.equal(page.element('registration-start').hidden, true);
  assert.equal(page.element('spin').disabled, false);
});


test('signup errors stay visible inside the registration dialog', async () => {
  const page = await browser(async url => {
    if (url.endsWith('/config')) return response(state);
    if (url.endsWith('/register')) return {ok: false, status: 409, json: async () => ({detail: 'Este WhatsApp já foi cadastrado'})};
    throw Error(url);
  });
  page.element('open-registration').onclick();
  page.element('name').value = 'Ana';page.element('phone').value = '27900000000';
  await page.element('form').onsubmit({preventDefault() {}});
  assert.equal(page.element('registration').open, true);
  assert.equal(page.element('registration-error').textContent, 'Este WhatsApp já foi cadastrado');
  assert.equal(page.element('spin').disabled, true);
});

test('unverified signup opens SMS dialog and cannot spin or trigger losing popup', async()=>{
 let spins=0;
 const page=await browser(async url=>{
  if(url.endsWith('/config'))return response({...state,verification_required:true,sms_available:true});
  if(url.endsWith('/register'))return response({...state,session:'test-session',spins_left:0,verification_required:true,phone_verified:false,sms_available:true});
  if(url.endsWith('/verification/start'))return response({sent:true});
  if(url.endsWith('/verification/check'))return response({...state,spins_left:3,max_spins:3,verification_required:true,phone_verified:true,sms_available:true,referral_code:'A'.repeat(16)});
  if(url.endsWith('/spin'))spins++;
  throw Error(url);
 });
 page.element('name').value='Ana';page.element('phone').value='27999999999';
 await page.element('form').onsubmit({preventDefault(){}});
 assert.equal(page.element('verification-dialog').open,true);
 assert.equal(page.element('spin').disabled,true);
 assert.equal(page.element('end-of-spins').open,false);
 await page.element('spin').onclick();assert.equal(spins,0);
 await page.element('send-code-form').onsubmit({preventDefault(){}});
 assert.match(page.element('verification-status').textContent,/Código enviado/);
 page.element('verification-code').value='123456';
 await page.element('check-code-form').onsubmit({preventDefault(){}});
 assert.equal(page.element('verification-dialog').open,false);
 assert.equal(page.element('spin').disabled,false);
 assert.equal(page.element('referral-panel').hidden,false);
});

test('confirmed referral can refresh exhausted credits and copy personal code',async()=>{
 let reads=0;let copied;
 const verified={...state,verification_required:true,phone_verified:true,referral_code:'B'.repeat(16),referral_bonus_limit:20};
 const page=await browser(async url=>{
  if(url.endsWith('/config'))return response(state);
  if(url.endsWith('/session')){reads++;return response({...verified,spins_left:reads===1?0:1,max_spins:reads===1?3:4,bonus_spins_earned:reads===1?0:1})}
  throw Error(url);
 },{fortune_demo_session:'test-session'},{},async value=>copied=value);
 assert.equal(page.element('end-of-spins').open,true);
 await page.element('copy-referral-code').onclick();assert.equal(copied,'B'.repeat(16));
 await page.element('refresh-referrals').onclick();
 assert.equal(page.element('remaining').textContent,1);
 assert.equal(page.element('spin').disabled,false);
 assert.equal(page.element('end-of-spins').open,false);
});


test('referral link copies the current domain and only the invitation parameter',async()=>{
 let copied;
 const page=await browser(async url=>{
  if(url.endsWith('/config'))return response(state);
  if(url.endsWith('/session'))return response({...state,spins_left:3,phone_verified:true,referral_code:'@ana.silva'});
  throw Error(url);
 },{fortune_demo_session:'test-session'},{},async value=>copied=value,'https://riscabet.online/?other=private#profile');
 await page.element('copy-referral-link').onclick();
 assert.equal(copied,'https://riscabet.online/?ref=%40ana.silva');
 assert.match(page.element('referral-status').textContent,/Link de indicação copiado/);
});

test('referral link stays available to copy manually if clipboard is unavailable',async()=>{
 const page=await browser(async url=>{
  if(url.endsWith('/config'))return response(state);
  if(url.endsWith('/session'))return response({...state,spins_left:3,phone_verified:true,referral_code:'@ana.silva'});
  throw Error(url);
 },{fortune_demo_session:'test-session'});
 await page.element('copy-referral-link').onclick();
 assert.match(page.element('referral-status').textContent,/https:\/\/riscabet.online\/\?ref=%40ana.silva/);
});
