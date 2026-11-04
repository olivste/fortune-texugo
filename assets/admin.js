'use strict';
const $ = id => document.getElementById(id);
let adminKey = '';
let settings = null;
let busy = false;
const symbols = window.FORTUNE_ASSETS.symbols.filter(symbol => symbol.id !== 'wild');
async function adminRequest(path, data, method = 'POST') {
  const response = await fetch('/api/admin/' + path, {
    method: data ? method : 'GET',
    headers: {'X-Admin-Key': adminKey, ...(data ? {'Content-Type': 'application/json'} : {})},
    cache: 'no-store',
    ...(data ? {body: JSON.stringify(data)} : {}),
  });
  if (!response.ok) {
    const body = await response.json();
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Confira os campos: chance de 0 a 100% (até duas casas decimais), nome e quantidade inteira de 0 a 10000.');
  }
  return response.json();
}
function fillSymbols(select, value = 'copo') {
  for (const symbol of symbols) {
    const option = document.createElement('option');
    option.value = symbol.id; option.textContent = symbol.name;
    select.append(option);
  }
  select.value = value;
}
function chancePreview() {
  const chance = Number($('probability').value);
  const threeSpins = (1 - (1 - chance / 100) ** 3) * 100;
  $('chance-preview').textContent = Number.isFinite(chance) && chance >= 0 && chance <= 100
    ? `Com a chance base, em três giros a chance de ganhar ao menos uma vez é ${threeSpins.toLocaleString('pt-BR', {maximumFractionDigits: 2})}%, enquanto houver estoque.` : '';
}
function effectiveChances(){
  $('effective-chances').replaceChildren();
  if(!settings)return;
  const base=Number($('probability').value);
  if(!Number.isFinite(base)||base<0||base>100)return;
  for(const item of settings.items){
    const row=document.createElement('p');
    row.textContent=`${item.name}: ${Math.min(100,base*item.chance_multiplier).toLocaleString('pt-BR',{maximumFractionDigits:2})}% por giro${!item.active?' · pausado':item.stock<=0?' · esgotado':''}`;
    $('effective-chances').append(row);
  }
}
function labeledInput(form, labelText, type, value, id) {
  const label = document.createElement('label'); label.textContent = labelText; label.htmlFor = id;
  const input = document.createElement(type === 'select' ? 'select' : 'input');
  input.id = id;
  if (type !== 'select') { input.type = type; input.value = value; }
  form.append(label, input);
  return input;
}
function renderSettings(data) {
  settings = data;
  $('probability').value = data.probability_percent;
  chancePreview();effectiveChances();
  $('probability-current').textContent='Porcentagem base salva: '+Number(data.probability_percent).toLocaleString('pt-BR')+'%';
  $('probability-mode').textContent=data.demo?'Modo demonstração: não concede prêmios reais, mesmo com 100%.':'Premiação ativa: a porcentagem será aplicada enquanto houver estoque.';
  $('new-priority').value = Math.min(10000, Math.max(0, ...data.items.map(item => item.priority)) + 1);
  $('prize-types').replaceChildren();
  for (const item of data.items) {
    const form = document.createElement('form'); form.className = 'catalog-item';
    const summary = document.createElement('p');
    summary.textContent = `${item.stock} disponível(is) · ${item.total_quantity - item.stock} concedido(s) · ${item.active ? 'Ativo' : 'Pausado'}`;
    form.append(summary);
    const name = labeledInput(form, 'Nome do prêmio', 'text', item.name, `item-${item.id}-name`);
    name.required = true; name.minLength = 2; name.maxLength = 80;
    const symbol = labeledInput(form, 'Símbolo nos rolos', 'select', '', `item-${item.id}-symbol`);
    fillSymbols(symbol, item.symbol);
    const priority = labeledInput(form, 'Ordem na sequência (menor primeiro)', 'number', item.priority, `item-${item.id}-priority`);
    priority.required = true; priority.min = 1; priority.max = 10000; priority.step = 1;
    const multiplier = labeledInput(form, 'Multiplicador da chance base (1 = normal, 2 = dobro)', 'number', item.chance_multiplier, `item-${item.id}-multiplier`);
    multiplier.required = true; multiplier.min = 1; multiplier.max = 100; multiplier.step = 1;
    const chance = document.createElement('p');
    const updateChance = () => {
      const percent = Math.min(100, settings.probability_percent * Number(multiplier.value));
      chance.textContent = `Chance deste prêmio quando entrar em jogo: ${percent.toLocaleString('pt-BR', {maximumFractionDigits: 2})}% por giro elegível (máximo 100%).`;
    };
    multiplier.addEventListener('input', updateChance); updateChance(); form.append(chance);
    const quantity = labeledInput(form, 'Quantidade total (inclui concedidos)', 'number', item.total_quantity, `item-${item.id}-quantity`);
    quantity.required = true; quantity.min = item.total_quantity - item.stock; quantity.max = 10000; quantity.step = 1;
    const checkboxLabel = document.createElement('label'); checkboxLabel.className = 'checkbox';
    const active = document.createElement('input'); active.type = 'checkbox'; active.checked = item.active;
    checkboxLabel.append(active, document.createTextNode(' Disponível para sorteio'));
    const save = document.createElement('button'); save.type = 'submit'; save.textContent = 'Salvar prêmio';
    form.append(checkboxLabel, save);
    form.addEventListener('submit', event => {
      event.preventDefault();
      run(async () => {
        await adminRequest('prize-types/' + item.id, {version: settings.version, name: name.value.trim(), symbol: symbol.value, total_quantity: Number(quantity.value), priority: Number(priority.value), chance_multiplier: Number(multiplier.value), active: active.checked}, 'PUT');
        await loadDashboard();
        $('status').textContent = 'Prêmio atualizado.';
      });
    });
    $('prize-types').append(form);
  }
}
async function loadDashboard() {
  const [stats, prizes, config, participants] = await Promise.all([
    adminRequest('stats'), adminRequest('prizes'), adminRequest('settings'), adminRequest('participants'),
  ]);
  $('players').textContent = stats.players;
  $('spins').textContent = stats.spins;
  $('stock').textContent = stats.stock;
  $('mode').textContent = stats.demo ? 'Demonstração · sem prêmios reais' : 'Promoção ativa';
  $('prizes').replaceChildren();
  if (!prizes.length) { const item = document.createElement('li'); item.textContent = 'Nenhum prêmio concedido.'; $('prizes').append(item); }
  for (const prize of prizes) {
    const item = document.createElement('li');
    item.textContent = `${prize.prize_name} · ${prize.name} · telefone final ${prize.phone_last4} · ${prize.claim_code} · ${prize.redeemed_at ? 'Retirado' : 'Aguardando retirada'}`;
    $('prizes').append(item);
  }
  $('participants').replaceChildren();
  for(const participant of participants){const item=document.createElement('li');item.textContent=`#${participant.id} · ${participant.name} · final ${participant.phone_last4} · ${participant.phone_verified_at ? 'Confirmado ('+participant.verification_method+')' : 'Aguardando confirmação'} · ${participant.bonus_spins_earned} bônus`;$('participants').append(item)}
  renderSettings(config);
  await loadAccountsAdmin();
  $('dashboard').hidden = false;
  $('admin-form').hidden = true;
}
async function run(action) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => { button.disabled = true; });
  $('status').textContent = 'Aguarde…';
  try { await action(); }
  catch (error) { $('status').textContent = error instanceof TypeError ? 'Falha de conexão. Atualize o painel antes de repetir a operação.' : error.message; }
  finally { busy = false; document.querySelectorAll('button').forEach(button => { button.disabled = false; }); }
}
$('admin-form').addEventListener('submit', event => {
  event.preventDefault();
  if (busy) return;
  adminKey = $('admin-key').value; $('admin-key').value = '';
  run(async () => { await loadDashboard(); $('status').textContent = 'Painel atualizado.'; });
});
$('refresh').onclick = () => run(async () => { await loadDashboard(); $('status').textContent = 'Painel atualizado.'; });
$('logout').onclick = () => {
  adminKey = ''; settings = null;
  $('dashboard').hidden = true; $('admin-form').hidden = false;
  $('prize-types').replaceChildren(); $('prizes').replaceChildren(); $('participants').replaceChildren(); $('verify-phone-form').reset();
  for(const id of ['promo-list','account-users','account-referrals','admin-history','admin-audit','suspicious-signals','retention-report','code-metrics'])$(id).replaceChildren();
  $('status').textContent = 'Sessão encerrada.';
};
$('probability').addEventListener('input',()=>{chancePreview();effectiveChances();$('probability-status').textContent='Alteração ainda não salva.'});
$('probability-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    await adminRequest('settings', {version: settings.version, probability_percent: $('probability').value}, 'PUT');
    await loadDashboard(); $('status').textContent = 'Porcentagem de ganho atualizada.';$('probability-status').textContent='Porcentagem salva com sucesso.';
  });
});
fillSymbols($('new-symbol'));
$('new-prize-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    await adminRequest('prize-types', {version: settings.version, name: $('new-name').value.trim(), symbol: $('new-symbol').value, total_quantity: Number($('new-quantity').value), priority: Number($('new-priority').value), chance_multiplier: Number($('new-multiplier').value), active: $('new-active').checked});
    $('new-prize-form').reset();
    await loadDashboard(); $('status').textContent = 'Prêmio adicionado.';
  });
});
$('redeem-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    await adminRequest('redeem', {claim_code: $('claim-code').value.trim()});
    $('redeem-form').reset();
    await loadDashboard(); $('status').textContent = 'Retirada confirmada.';
  });
});

$('verify-phone-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{await adminRequest('verify-phone',{player_id:Number($('verify-player').value),phone:$('verify-phone').value,checked:$('verify-checked').checked,note:$('verify-note').value.trim()});$('verify-phone-form').reset();await loadDashboard();$('status').textContent='Telefone confirmado. Indicações elegíveis foram creditadas.'})});
