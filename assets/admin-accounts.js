/* Uses the existing in-memory admin key; never puts secrets in URLs or storage. */
function adminTextList(id,rows,formatter){$(id).replaceChildren();for(const row of rows){const li=document.createElement('li');li.textContent=formatter(row);$(id).append(li)}}
async function loadAccountsAdmin(){
 const [codes,users,referrals,audit,signals,retention]=await Promise.all(['codes','users?q='+encodeURIComponent($('user-search').value),'referrals','audit','suspicious','retention'].map(path=>adminRequest(path)));
 $('code-metrics').textContent=`${codes.metrics.total} códigos · ${codes.metrics.active} ativos · ${codes.metrics.expired} expirados · ${codes.metrics.redemptions} resgates · ${codes.metrics.spins} giros distribuídos`;
 $('promo-list').replaceChildren();
 const localDate=value=>{if(!value)return '';const d=new Date(value);return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16)};
 for(const item of codes.items){
  const form=document.createElement('form');form.className='catalog-item';
  const title=document.createElement('h3');title.textContent=`${item.code} · ${item.redeemed_count} resgates · ${item.remaining} restantes`;form.append(title);
  const spins=labeledInput(form,'Giros por resgate','number',item.spins,'promo-'+item.id+'-spins');spins.min=1;spins.max=1000;spins.required=true;
  const limit=labeledInput(form,'Máximo de resgates','number',item.max_redemptions,'promo-'+item.id+'-limit');limit.min=Math.max(1,item.redeemed_count);limit.max=1000000;limit.required=true;
  const start=labeledInput(form,'Início (horário local)','datetime-local',localDate(item.starts_at),'promo-'+item.id+'-start');start.required=true;
  const end=labeledInput(form,'Expiração (horário local)','datetime-local',localDate(item.expires_at),'promo-'+item.id+'-end');end.required=false;end.title='Deixe vazio para não expirar';
  const desc=labeledInput(form,'Descrição interna','text',item.description,'promo-'+item.id+'-desc');desc.maxLength=200;
  const label=document.createElement('label');label.className='checkbox';const active=document.createElement('input');active.type='checkbox';active.checked=item.active;label.append(active,document.createTextNode(' Ativo'));form.append(label);
  const save=document.createElement('button');save.textContent='Salvar código';save.type='submit';
  const history=document.createElement('button');history.type='button';history.textContent='Ver resgates';history.onclick=()=>run(async()=>{$('admin-history').textContent=JSON.stringify(await adminRequest('codes/'+item.id+'/redemptions'),null,2);$('admin-history').scrollIntoView({block:'nearest'})});form.append(save,history);
  form.onsubmit=event=>{event.preventDefault();run(async()=>{await adminRequest('codes/'+item.id,{code:item.code,version:item.version,spins:Number(spins.value),max_redemptions:Number(limit.value),starts_at:new Date(start.value).toISOString(),expires_at:end.value?new Date(end.value).toISOString():null,active:active.checked,description:desc.value},'PUT');await loadAccountsAdmin();$('status').textContent='Código atualizado.'})};
  $('promo-list').append(form);
 }
 $('account-users').replaceChildren();
 for(const user of users){const li=document.createElement('li');const text=document.createElement('span');text.textContent=`#${user.id} ${user.name} · @${user.instagram} · CPF ${user.cpf_masked} · cadastro ${new Date(user.created_at).toLocaleString('pt-BR')} · ${user.status} · saldo ${user.spins_left} · ${user.spins_played} giros realizados · ${user.referral_spins} por indicação · ${user.promo_spins} por códigos `;
 const pick=document.createElement('button');pick.type='button';pick.textContent='Selecionar / histórico';pick.onclick=()=>run(async()=>{$('manage-user').value=user.id;$('admin-history').textContent=JSON.stringify(await adminRequest('users/'+user.id+'/history'),null,2)});li.append(text,pick);$('account-users').append(li)}
 adminTextList('account-referrals',referrals,row=>`@${row.referred} → @${row.referrer} · ${row.status}${row.reason?' · '+row.reason:''}`);
 $('admin-audit').textContent=JSON.stringify(audit,null,2);$('suspicious-signals').textContent=JSON.stringify(signals,null,2);$('retention-report').textContent=JSON.stringify(retention,null,2);
}
$('promo-create-form').onsubmit=event=>{event.preventDefault();run(async()=>{await adminRequest('codes',{code:$('create-code').value.trim(),spins:Number($('create-spins').value),max_redemptions:Number($('create-limit').value),active:$('create-active').checked,description:$('create-description').value});$('promo-create-form').reset();await loadAccountsAdmin();$('status').textContent='Código criado.'})};
$('users-search-form').onsubmit=event=>{event.preventDefault();run(loadAccountsAdmin)};
let pendingAdminAdjustment=null;
$('adjust-balance-form').onsubmit=event=>{event.preventDefault();run(async()=>{const user=Number($('manage-user').value);const amount=Number($('adjust-amount').value);const reason=$('adjust-reason').value.trim();const signature=JSON.stringify([user,amount,reason]);if(!pendingAdminAdjustment||pendingAdminAdjustment.signature!==signature)pendingAdminAdjustment={signature,operation_id:crypto.randomUUID()};await adminRequest('users/'+user+'/balance',{amount,reason,operation_id:pendingAdminAdjustment.operation_id});pendingAdminAdjustment=null;await loadAccountsAdmin();$('status').textContent='Saldo ajustado e auditado.'})};
$('account-status-form').onsubmit=event=>{event.preventDefault();run(async()=>{await adminRequest('users/'+Number($('manage-user').value)+'/status',{status:$('manage-status').value,reason:$('status-reason').value},'PUT');await loadAccountsAdmin();$('status').textContent='Status atualizado.'})};
$('export-redemptions').onclick=()=>run(async()=>{const response=await fetch('/api/admin/code-redemptions.csv',{headers:{'X-Admin-Key':adminKey},cache:'no-store'});if(!response.ok)throw Error('Falha ao exportar');const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download='resgates.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('status').textContent='Exportação preparada.'});
$('run-retention').onclick=()=>run(async()=>{const data=await adminRequest('retention/run',{});await loadAccountsAdmin();$('status').textContent=data.due?'Rotina executada. Confira as cópias externas no relatório.':'Prazo de eliminação ainda não atingido.'});
$('backup-review-form').onsubmit=event=>{event.preventDefault();run(async()=>{await adminRequest('retention/backup-review',{evidence:$('backup-evidence').value});$('backup-review-form').reset();await loadAccountsAdmin();$('status').textContent='Conferência operacional registrada.'})};
