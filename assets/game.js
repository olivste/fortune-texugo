const CONFIG={API_BASE:window.FORTUNE_ASSETS?.apiBase||'',TICKET_URL:window.FORTUNE_ASSETS?.ticketUrl||''};
const $=id=>document.getElementById(id);
const ASSETS=window.FORTUNE_ASSETS||{};const icons=(ASSETS.symbols||[]).map(x=>x.src);
const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let accountsMode=false,csrfToken='';
let token='',left=3,busy=false,hasPrize=false,unlimited=false,requiresVerification=false,smsAvailable=false,ownReferralCode='',registeredPhone='';
const PENDING_KEY='fortune_pending_spin';
function pendingSpin(){
 try{
  const pending=JSON.parse(localStorage.getItem(PENDING_KEY)||'null');
  return pending?.session===token?pending:null;
 }catch{return null}
}
function prizeText(text, prize){
 return text.replaceAll('{prize}',prize.prize_name||'Copo Risca Faca');
}
function updateSpinButton(){
 $('spin').disabled=busy||hasPrize||requiresVerification||(!accountsMode&&(!token||(left<=0&&!unlimited&&!pendingSpin())));
}
function showPrize(prize,openPopup=true){
 if(!prize)return;
 if(accountsMode)$('referral-panel').hidden=true;
 hasPrize=true;
 if(pendingSpin())localStorage.removeItem(PENDING_KEY);
 updateSpinButton();
 showCount();
 $('winner').classList.remove('hidden');
 $('winner').textContent=prizeText(prize.redeemed_at?ASSETS.text.prizeRedeemed:ASSETS.text.prizeWon,prize)+prize.claim_code;
 $('prize-details').hidden=!!prize.redeemed_at;
 $('prize-details').textContent=ASSETS.text.winnerReopen;
 $('prize-close').textContent=ASSETS.text.closePopup;
 $('prize-brand').textContent=ASSETS.text.brand;
 $('prize-art').src=ASSETS.symbols.find(symbol=>symbol.id===(prize.prize_symbol||'copo'))?.src||ASSETS.mascot;
 $('prize-title').textContent=prizeText(ASSETS.text.winnerTitle,prize);
 $('prize-instructions').textContent=ASSETS.text.winnerInstructions;
 $('prize-code-label').textContent=ASSETS.text.winnerCodeLabel;
 $('prize-code').textContent=prize.claim_code;
 $('copy-prize-code').textContent=ASSETS.text.copyCode;
 $('copy-code-status').textContent='';
 const instagram=$('prize-instagram');
 instagram.textContent=ASSETS.text.winnerContactButton;
 // A missing or invalid profile never becomes a fabricated contact link.
 let profile;
 try{profile=new URL(ASSETS.instagramUrl)}catch{}
 const validProfile=profile?.protocol==='https:'&&['instagram.com','www.instagram.com'].includes(profile.hostname)&&profile.pathname!=='/';
 instagram.hidden=!validProfile;
 if(validProfile)instagram.href=profile.href;
 if(!prize.redeemed_at&&openPopup){
  if($('end-of-spins').open)$('end-of-spins').close();
  if(!$('prize-popup').open)$('prize-popup').showModal();
 }else if($('prize-popup').open)$('prize-popup').close();
}
function showEndOfSpins(){
 const popup=$('end-of-spins');
 const shouldOpen=!requiresVerification&&!unlimited&&left<=0&&!hasPrize&&!pendingSpin();
 $('end-brand').textContent=ASSETS.text.brand;
 $('end-mascot').src=ASSETS.mascot;
 $('end-kicker').textContent=ASSETS.text.popupKicker;
 $('end-event-label').textContent=ASSETS.text.popupEventLabel;
 $('end-event').textContent=ASSETS.text.event;
 $('end-title').textContent=ASSETS.text.noPrizeTitle;
 $('end-message').textContent=ASSETS.text.noPrizeMessage;
 $('end-ticket').textContent=ASSETS.text.ticketButton;
 $('end-ticket').href=CONFIG.TICKET_URL;
 $('end-close').textContent=ASSETS.text.closePopup;
 if(shouldOpen&&!popup.open)popup.showModal();
 else if(!shouldOpen&&popup.open)popup.close();
}
$('open-registration').onclick=()=>{if(!token&&!$('registration').open){$('registration-error').textContent='';$('registration').showModal()}};
$('registration-close').onclick=()=>$('registration').close();
$('end-close').onclick=()=>$('end-of-spins').close();
$('prize-close').onclick=()=>$('prize-popup').close();
$('prize-details').onclick=()=>{if(!$('prize-popup').open)$('prize-popup').showModal()};
$('copy-prize-code').onclick=async()=>{
 const button=$('copy-prize-code');button.disabled=true;
 try{
  await navigator.clipboard.writeText($('prize-code').textContent);
  $('copy-code-status').textContent=ASSETS.text.codeCopied;
 }catch{$('copy-code-status').textContent=ASSETS.text.codeCopyFailed}
 finally{button.disabled=false}
};
function showCount(){
 $('remaining').textContent=hasPrize?0:unlimited?'∞':left;
}
function escapeHTML(value){return String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;')}
function showParticipation(data){
 requiresVerification=data.verification_required===true&&data.phone_verified!==true&&!hasPrize&&!data.prize&&!data.won;
 smsAvailable=data.sms_available===true;
 $('verification-start').hidden=!token||!requiresVerification;
 $('sms-availability').textContent=smsAvailable?'':ASSETS.text.verificationUnavailable;
 $('send-phone-code').disabled=!smsAvailable;$('check-phone-code').disabled=!smsAvailable;
 if(!requiresVerification&&$('verification-dialog').open)$('verification-dialog').close();
 ownReferralCode=data.referral_code||ownReferralCode;
 $('referral-panel').hidden=!token||hasPrize||!!data.prize||data.won===true||!ownReferralCode||data.phone_verified!==true;
 $('my-referral-code').textContent=ownReferralCode;
 $('referral-counts').textContent=accountsMode?`${data.bonus_spins_earned||0} giros recebidos por indicação`:ASSETS.text.referralCounts.replace('{earned}',data.bonus_spins_earned||0).replace('{pending}',data.referrals_pending||0).replace('{limit}',data.referral_bonus_limit||20);
}
$('open-verification').onclick=()=>{if(requiresVerification){$('verification-phone').value=registeredPhone;$('verification-dialog').showModal()}};
$('verification-close').onclick=()=>$('verification-dialog').close();
$('send-code-form').onsubmit=async event=>{
 event.preventDefault();const button=$('send-phone-code');button.disabled=true;
 try{await call('verification/start',{session:token,phone:$('verification-phone').value});$('verification-status').textContent=ASSETS.text.verificationSent}
 catch(error){$('verification-status').textContent=error.message}
 finally{button.disabled=!smsAvailable}
};
$('check-code-form').onsubmit=async event=>{
 event.preventDefault();const button=$('check-phone-code');button.disabled=true;
 try{const data=await call('verification/check',{session:token,code:$('verification-code').value});left=data.spins_left;showState(data);updateSpinButton();$('verification-status').textContent='';$('verification-code').value='';msg(ASSETS.text.verificationSuccess)}
 catch(error){$('verification-status').textContent=error.message}
 finally{button.disabled=!smsAvailable}
};
async function refreshParticipant(){
 if(!token||busy)return;
 try{const response=await fetch(CONFIG.API_BASE+(accountsMode?'/api/account/me':'/api/session'),{headers:accountsMode?{}:{Authorization:'Bearer '+token},cache:'no-store'});if(!response.ok){if(accountsMode&&[401,403].includes(response.status))accountClear();return;}
 const data=await response.json();if(accountsMode)accountApply(data);else{left=data.spins_left;showState(data);showPrize(data.prize,false);updateSpinButton()}
 if(left>0&&$('end-of-spins').open)$('end-of-spins').close();
 }catch{}
}
async function copyReferral(){
 try{await navigator.clipboard.writeText(ownReferralCode);$('referral-status').textContent=ASSETS.text.referralCopied}
 catch{$('referral-status').textContent=ASSETS.text.referralCopyError}
}
$('copy-referral-code').onclick=copyReferral;
$('refresh-referrals').onclick=refreshParticipant;
window.addEventListener?.('focus',refreshParticipant);
if(typeof setInterval==='function')setInterval(()=>{if(document.visibilityState==='visible')refreshParticipant()},30000);
try{$('referral-input').value=(new URL(location.href).searchParams.get('ref')||'').toUpperCase()}catch{}
function showState(data){
 unlimited=data.demo&&data.unlimited_spins===true;
 showCount();
 if(unlimited){
  $('registration-copy').textContent=ASSETS.text.unlimitedNotice;
  $('form').querySelector('button').textContent=ASSETS.text.unlimitedButton;
 }
 $('stock').textContent=data.stock+' / '+(data.total_stock??5);
 if('current_prize' in data)$('current-prize').textContent=data.current_prize?ASSETS.text.currentPrizeLabel+data.current_prize.name:'';
 if(data.prize_options)$('prize-options').innerHTML=data.prize_options.map(item=>'<li><span>'+escapeHTML(item.name)+'</span><strong>'+Number(item.stock)+'</strong></li>').join('');
 $('mode').textContent=data.demo?ASSETS.text.demoMode:ASSETS.text.liveMode;
 $('prize-rules').textContent=data.demo?ASSETS.text.demoRules:ASSETS.text.liveRules.replaceAll('{chance}',((data.probability??0.02)*100).toLocaleString('pt-BR',{maximumFractionDigits:2}));
 $('notice').textContent=unlimited?ASSETS.text.unlimitedNotice:data.demo?ASSETS.text.demoNotice:ASSETS.text.liveNotice;
 showParticipation(data);
}
// Static previews must explicitly opt out; HTTP defaults to the same-origin API.
const configured=ASSETS.backendEnabled !== false && location.protocol.startsWith('http');
$('bulbs').innerHTML='<i></i>'.repeat(17);
const wildIcon=ASSETS.symbols?.find(symbol=>symbol.id==='wild')?.src;
const regularIcons=icons.filter(src=>src!==wildIcon);
$('reels').innerHTML=Array.from({length:3},(_,c)=>'<div class="reel">'+Array.from({length:3},(_,r)=>{
 const src=c===1&&wildIcon?wildIcon:regularIcons[(c*2+r)%regularIcons.length];
 return '<div class="symbol'+(src===wildIcon?' is-wild':'')+'">'+symbolHTML(src)+'</div>';
}).join('')+'</div>').join('');
if(CONFIG.TICKET_URL){$('ticket').href=CONFIG.TICKET_URL;$('ticket').textContent='GARANTIR INGRESSO'}
$('notice').textContent=configured?ASSETS.text.demoNotice:'Prévia local: sem gravação de dados e sem prêmios.';
const randomSymbol=()=>icons[Math.floor(Math.random()*icons.length)];
function symbolHTML(src){
 const symbol=(ASSETS.symbols||[]).find(s=>s.src===src);
 const label=(symbol?.name||'Símbolo').replace(/"/g,'');
 return '<img src="'+src+'" alt="'+label+'" loading="eager" draggable="false">';
}
const grid=()=>{
 const columns=Array.from({length:3},()=>Array.from({length:3},randomSymbol));
 if(new Set(columns.map(col=>col[1]).filter(src=>src!==wildIcon)).size<=1){
  columns[0][1]=regularIcons[0];columns[2][1]=regularIcons[1];
 }
 return columns;
};
for(const el of document.querySelectorAll('[data-text]')){const key=el.dataset.text;if(ASSETS.text?.[key])el.textContent=ASSETS.text[key]}
if(ASSETS.cabinetSkin&&$('cabinet-skin'))$('cabinet-skin').src=ASSETS.cabinetSkin;
if(ASSETS.cabinetHeader&&$('cabinet-art'))$('cabinet-art').src=ASSETS.cabinetHeader;
if(ASSETS.mascot&&$('mascot-art'))$('mascot-art').src=ASSETS.mascot;
if(ASSETS.background)document.documentElement.style.setProperty('--scene-image','url("'+ASSETS.background+'")');
function drawColumn(c,values){for(let r=0;r<3;r++){const cell=$('reels').children[c].children[r];cell.innerHTML=symbolHTML(values[r]);cell.classList.toggle('is-wild',values[r]===wildIcon)}}
function msg(s,celebrate=false){$('message').textContent=s;$('message').classList.toggle('celebrate',celebrate)}
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function call(fn,data){
 const r=await fetch(CONFIG.API_BASE+'/api/'+fn,{method:'POST',headers:{'Content-Type':'application/json',...(csrfToken?{'X-CSRF-Token':csrfToken}:{})},body:JSON.stringify(data)});
 const j=await r.json();if(!r.ok){if(r.status===401&&accountsMode&&typeof accountClear==='function')accountClear();throw Error(typeof j.detail==='string'?j.detail:'Confira os campos informados e tente novamente.')}return j;
}
async function restore(){
 if(accountsMode){
  const response=await fetch(CONFIG.API_BASE+'/api/account/me',{cache:'no-store'});
  if(response.status===401){accountClear();return}
  if(!response.ok)throw Error('Não foi possível recuperar sua conta');
  const data=await response.json();accountApply(data);showPrize(data.prize);showEndOfSpins();return;
 }
 const stored=localStorage.getItem('fortune_demo_session');if(!stored||!configured)return;
 const r=await fetch(CONFIG.API_BASE+'/api/session',{headers:{Authorization:'Bearer '+stored}});
 if(r.status===401){localStorage.removeItem('fortune_demo_session');localStorage.removeItem(PENDING_KEY);return}
 if(!r.ok)throw Error('Não foi possível recuperar a sessão. Recarregue para tentar novamente.');
 const d=await r.json();token=stored;left=d.spins_left;
 $('registration').close();$('registration').classList.add('hidden');$('registration-start').hidden=true;
 showState(d);showPrize(d.prize);updateSpinButton();
 msg(requiresVerification?ASSETS.text.verificationPending:hasPrize?ASSETS.text.winnerFinished:pendingSpin()?ASSETS.text.pendingSpin:(left||unlimited)?'Sua sessão foi recuperada!':'Seus giros acabaram!');
 showEndOfSpins();
}

async function initialize(){
 $('open-registration').disabled=true;
 if(!configured){$('open-registration').disabled=false;return}
 const button=$('form').querySelector('button');button.disabled=true;
 try{
  const response=await fetch(CONFIG.API_BASE+'/api/config',{cache:'no-store'});
  if(!response.ok)throw Error('API indisponível. Recarregue a página para tentar novamente.');
  const config=await response.json();accountsMode=config.accounts_enabled===true;if(accountsMode){if(typeof accountSetup!=='function')await new Promise(resolve=>window.addEventListener('fortune:accounts-ready',resolve,{once:true}));accountSetup(config)}showState(config);
  await restore();button.disabled=false;$('open-registration').disabled=false;
 }catch(error){msg('API indisponível. Recarregue a página para tentar novamente.')}
}
initialize();

function confetti(){
 if(reduced)return;
 for(let i=0;i<75;i++){const el=document.createElement('i');el.className='confetti';
 el.style.setProperty('--left',Math.random()*100+'vw');
 el.style.setProperty('--duration',(2+Math.random()*2.5)+'s');
 el.style.setProperty('--drift',(Math.random()-.5)*250+'px');
 el.style.setProperty('--rotation',Math.random()*360+'deg');
 el.style.setProperty('--color',['#f3cb6b','#fff1bb','#c12435','#69bf6b'][i%4]);
 document.body.append(el);el.addEventListener('animationend',()=>el.remove())}
}
async function animateReels(finalGrid){
 const columns=Array.from($('reels').children);
 if(reduced||!columns[0].animate){finalGrid.forEach((values,c)=>drawColumn(c,values));return}
 const height=columns[0].children[0].getBoundingClientRect().height;
 const gap=parseFloat(getComputedStyle(columns[0]).rowGap)||0;
 const cell=src=>'<div class="symbol'+(src===wildIcon?' is-wild':'')+'">'+symbolHTML(src)+'</div>';
 await Promise.all(columns.map(async(column,c)=>{
  const initial=column.innerHTML;
  const randomCount=16+c*4;
  const randomCells=Array.from({length:randomCount},()=>cell(randomSymbol())).join('');
  const ending=finalGrid[c].map(cell).join('');
  column.style.height=(height*3+gap*2)+'px';column.style.display='block';
  column.innerHTML='<div class="reel-strip">'+initial+randomCells+ending+'</div>';
  column.classList.add('is-spinning');
  const strip=column.firstElementChild;strip.style.gap=gap+'px';strip.style.setProperty('--rolling-cell-height',height+'px');
  const distance=(3+randomCount)*(height+gap);
  const animation=strip.animate([
   {transform:'translateY(0)',offset:0},
   {transform:'translateY(-'+(distance+10)+'px)',offset:.92},
   {transform:'translateY(-'+distance+'px)',offset:1}
  ],{duration:1250+c*360,easing:'cubic-bezier(.16,.7,.2,1)',fill:'forwards'});
  try{await animation.finished}
  finally{
   column.innerHTML=ending;column.style.height='';column.style.display='';
   column.classList.remove('is-spinning');column.classList.add('stopped');
  }
  await sleep(180);column.classList.remove('stopped');
 }));
}
function registrationError(text){$('registration-error').textContent=text;msg(text)}
$('form').onsubmit=async e=>{
 e.preventDefault();$('registration-error').textContent='';
 const name=$('name').value.trim(),phone=$('phone').value.replace(/\D/g,'');
 if(name.length<2||!/^(?:55)?[1-9]\d{9,10}$/.test(phone))return registrationError('Informe nome e WhatsApp válido com DDD');
 const btn=$('form').querySelector('button');btn.disabled=true;
 try{
  if(configured){registeredPhone=phone;const d=await call('register',{name,phone,referral_code:$('referral-input').value.trim().toUpperCase()});token=d.session;localStorage.setItem('fortune_demo_session',token);left=d.spins_left;showState(d)}
  else{token='local-demo';left=3}
  $('registration').close();$('registration').classList.add('hidden');$('registration-start').hidden=true;showCount();updateSpinButton();msg(requiresVerification?ASSETS.text.verificationPending:'Seus giros estão liberados!');if(requiresVerification){$('verification-phone').value=registeredPhone;$('verification-dialog').showModal()}else $('spin').focus?.();
 }catch(err){registrationError(err.message)}finally{btn.disabled=false}
};
$('spin').onclick=async()=>{
 if(accountsMode&&!token)return accountOpenLogin();
 if(accountsMode&&!busy&&!hasPrize&&left<=0&&!pendingSpin()){msg('Você não possui giros. Acesse RESGATAR GIROS.');return accountOpenRedeem()}
 if(busy||hasPrize||requiresVerification||!token||(left<=0&&!unlimited&&!pendingSpin()))return;
 busy=true;$('spin').disabled=true;if($('end-of-spins').open)$('end-of-spins').close();msg('O texugo está girando...');
 try{
  let pending;
  if(configured){
   pending=pendingSpin()||{session:token,request_id:crypto.randomUUID()};
   localStorage.setItem(PENDING_KEY,JSON.stringify(pending));
  }
  const request=configured?call('spin',pending):Promise.resolve({grid:grid(),spins_left:left-1,stock:5,won:false,demo:true});
  const result=await request;
  if(configured)localStorage.removeItem(PENDING_KEY);
  left=result.spins_left;showCount();
  const visualGrid=(result.grid||grid()).map(col=>col.map(v=>icons.includes(v)?v:(ASSETS.symbols.find(s=>s.id===v)?.src||icons[0])));
  await animateReels(visualGrid);
  left=result.spins_left;showState(result);
  if(result.won){
   showPrize(result);
   $('reels').closest('.machine').classList.add('win');confetti();msg(prizeText(ASSETS.text.winMessage,result),true);
   setTimeout(()=>$('reels').closest('.machine').classList.remove('win'),2300);
  }else msg(result.demo?'Giro de demonstração, sem premiação.':left?'Não foi dessa vez!':'Seus giros acabaram!');
  showEndOfSpins();
 }catch(err){msg(err.message)}
 finally{busy=false;updateSpinButton()}
};
