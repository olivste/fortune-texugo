import {createClient} from 'npm:@supabase/supabase-js@2';
const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'authorization,apikey,content-type','Content-Type':'application/json'};
Deno.serve(async req=>{if(req.method==='OPTIONS')return new Response('',{headers});try{
if(req.method!=='POST')throw Error('Método inválido');
const jwt=req.headers.get('Authorization')?.replace(/^Bearer /,'');if(!jwt)throw Error('Não autorizado');
const url=Deno.env.get('SUPABASE_URL')!,anon=Deno.env.get('SUPABASE_ANON_KEY')!,service=Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const {data:{user},error}=await createClient(url,anon).auth.getUser(jwt);if(error||!user)throw Error('Login inválido');
const db=createClient(url,service);const {data:admin}=await db.from('fortune_admins').select('user_id').eq('user_id',user.id).maybeSingle();if(!admin)throw Error('Acesso negado');
const {action,code}=await req.json();
if(action==='stats'){const [{data:config},{count:players},{count:spins},{data:prizes}]=await Promise.all([db.from('fortune_config').select('*').eq('id',1).single(),db.from('fortune_players').select('*',{count:'exact',head:true}),db.from('fortune_spins').select('*',{count:'exact',head:true}),db.from('fortune_prizes').select('claim_code,redeemed_at,created_at')]);return new Response(JSON.stringify({config,players,spins,prizes}),{headers})}
if(action==='redeem'){if(!/^[A-F0-9]{16}$/.test(String(code||'')))throw Error('Código inválido');const {data,error}=await db.from('fortune_prizes').update({redeemed_at:new Date().toISOString()}).eq('claim_code',code).is('redeemed_at',null).select('id').maybeSingle();if(error||!data)throw Error('Código inexistente ou já utilizado');return new Response(JSON.stringify({ok:true}),{headers})}
throw Error('Ação inválida');
}catch(e){return new Response(JSON.stringify({error:String((e as Error).message)}),{status:403,headers})}});