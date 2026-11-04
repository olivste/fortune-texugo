/* Account screens extend the existing game; authentication is always checked by the API. */
let accountConfig={};
function accountPrefillReferral(){try{$('referral-input').value=normalInstagram(new URL(location.href).searchParams.get('ref')||'')}catch{}}
function accountApply(data){
 csrfToken=data.csrf_token||csrfToken;token='account:'+data.user.id;left=data.spins_left;hasPrize=!!data.prize;
 $('registration').close();$('registration').classList.remove('hidden');$('registration-start').hidden=true;
 $('account-toolbar').hidden=false;$('account-name').textContent=data.user.name+' · @'+data.user.instagram;
 showState(data);showPrize(data.prize,false);updateSpinButton();
 $('referral-total').textContent=`${data.referrals_total} pessoas indicadas · convites sem limite`;
 if($('message').textContent==='Cadastre-se para liberar os giros!')msg(data.prize?ASSETS.text.winnerFinished:data.spins_left?'Seus giros estão disponíveis!':'Você não possui giros. Convide amigos ou resgate um código.');
 $('profile-summary').textContent=`${data.user.name} · @${data.user.instagram}`;
 $('profile-balance').textContent=`Giros disponíveis: ${data.spins_left}`;
}
function accountClear(){
 token='';csrfToken='';left=0;hasPrize=false;requiresVerification=false;
 $('account-toolbar').hidden=true;$('referral-panel').hidden=true;$('registration-start').hidden=false;
 $('winner').classList.add('hidden');$('prize-details').hidden=true;
 for(const id of ['profile-dialog','redeem-dialog','prize-popup','end-of-spins'])if($(id).open)$(id).close();
 $('profile-summary').textContent='';$('profile-balance').textContent='';for(const id of ['prize-code','winner','my-referral-code','referral-counts','referral-total','account-name'])$(id).textContent='';for(const id of ['form','login-form','promo-form'])$(id).reset();accountPrefillReferral();updateSpinButton();showCount();
}
function accountOpenLogin(){if(!$('login-dialog').open)$('login-dialog').showModal()}
function accountOpenRedeem(){if(!token)return accountOpenLogin();if(!$('redeem-dialog').open)$('redeem-dialog').showModal()}
function validCPF(value){
 const cpf=value.replace(/\D/g,'');if(!/^\d{11}$/.test(cpf)||/^(\d)\1{10}$/.test(cpf))return false;
 for(const size of [9,10]){let sum=0;for(let i=0;i<size;i++)sum+=Number(cpf[i])*(size+1-i);let digit=sum*10%11;if(digit===10)digit=0;if(digit!==Number(cpf[size]))return false}return true;
}
function normalInstagram(value){return value.trim().replace(/^@+/,'').toLowerCase()}
function accountSetup(config){
 accountConfig=config;
 localStorage.removeItem('fortune_demo_session');
 $('registration-title').textContent='CRIE SUA CONTA';$('registration-copy').textContent='Cadastro gratuito para maiores de 18 anos. Você recebe três giros.';
 $('form').querySelector('button').textContent='CRIAR CONTA';$('notice').textContent='Sem depósitos, apostas em dinheiro ou compra de giros.';
 $('open-registration').textContent='ENTRAR OU CADASTRAR';$('open-registration').onclick=accountOpenLogin;
 $('referral-panel').querySelector('h2').textContent='MINHAS INDICAÇÕES';
 $('referral-panel').querySelector('p').textContent='Cada amigo que se cadastrar com seu @ vale 1 giro para você. Convide quantos quiser!';
 $('copy-referral-code').textContent='COPIAR @';
 accountPrefillReferral();
 $('form').onsubmit=async event=>{
  event.preventDefault();$('registration-error').textContent='';
  const cpf=$('cpf').value;if(!validCPF(cpf))return registrationError('CPF inválido. Confira os dígitos.');
  const instagram=normalInstagram($('instagram').value);const referral=normalInstagram($('referral-input').value);
  if(!/^[a-z0-9_](?:[a-z0-9_.]{0,28}[a-z0-9_])?$/.test(instagram)||instagram.includes('..'))return registrationError('Instagram inválido.');
  if(referral===instagram)return registrationError('Você não pode indicar a si mesmo.');
  if($('password').value!==$('password-confirmation').value)return registrationError('As senhas não conferem.');
  const button=$('form').querySelector('button');button.disabled=true;
  try{
   const data=await call('account/register',{name:$('name').value.trim(),cpf,instagram,password:$('password').value,password_confirmation:$('password-confirmation').value,
    referral_instagram:referral,terms_accepted:$('accept-terms').checked,adult:$('adult').checked,terms_version:config.terms_version,privacy_version:config.privacy_version});
   accountApply(data);$('form').reset();msg('Conta criada! Seus três giros estão disponíveis.');
  }catch(error){registrationError(error.message)}finally{button.disabled=false}
 };
}
$('login-close').onclick=()=>$('login-dialog').close();
$('login-signup').onclick=()=>{$('login-dialog').close();$('registration').classList.remove('hidden');$('registration').showModal()};
$('login-form').onsubmit=async event=>{
 event.preventDefault();const button=$('login-form').querySelector('button');button.disabled=true;$('login-error').textContent='';
 try{const identifier=$('login-identifier').value.trim();const data=await call('account/login',{...(/^[\d.\-\s]+$/.test(identifier)?{cpf:identifier}:{instagram:normalInstagram(identifier)}),password:$('login-password').value});
 accountApply(data);$('login-dialog').close();$('login-form').reset();msg('Você entrou!');showEndOfSpins();
 }catch(error){$('login-error').textContent=error.message}finally{button.disabled=false}
};
$('account-logout').onclick=async()=>{if(busy)return;try{await call('account/logout',{});accountClear();msg('Você saiu da conta.')}catch(error){msg(error.message)}};
$('open-redeem').onclick=accountOpenRedeem;$('redeem-close').onclick=()=>$('redeem-dialog').close();
let pendingRedemption=null;
$('promo-form').onsubmit=async event=>{
 event.preventDefault();const code=$('promo-code').value.trim().toUpperCase();const button=$('promo-form').querySelector('button');button.disabled=true;
 if(!pendingRedemption||pendingRedemption.code!==code)pendingRedemption={code,operation_id:crypto.randomUUID()};
 try{const data=await call('account/redeem',pendingRedemption);accountApply(data);$('promo-status').textContent=data.message||'Resgate confirmado. Saldo atualizado.';pendingRedemption=null;if($('end-of-spins').open)$('end-of-spins').close()}
 catch(error){$('promo-status').textContent=error.message}finally{button.disabled=false}
};
$('profile-close').onclick=()=>$('profile-dialog').close();
$('open-profile').onclick=()=>{if(!token)return accountOpenLogin();$('profile-balance').textContent=`Giros disponíveis: ${hasPrize?0:left}`;$('profile-dialog').showModal()};

window.dispatchEvent(new Event('fortune:accounts-ready'));
