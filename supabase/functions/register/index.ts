import {createClient} from 'npm:@supabase/supabase-js@2';
const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'authorization,apikey,content-type','Content-Type':'application/json'};
async function hash(s:string){const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s));return Array.from(new Uint8Array(b)).map(x=>x.toString(16).padStart(2,'0')).join('')}
Deno.serve(async req=>{if(req.method==='OPTIONS')return new Response('',{headers});try{
if(req.method!=='POST')throw Error('Método inválido');
const {name,phone}=await req.json();const n=String(name||'').trim().slice(0,80);let p=String(phone||'').replace(/\D/g,'');if(p.startsWith('55')&&p.length>=12)p=p.slice(2);
if(n.length<2||!/^[1-9]\d{9,10}$/.test(p))throw Error('Nome ou WhatsApp inválido');
const url=Deno.env.get('SUPABASE_URL')!,key=Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,pepper=Deno.env.get('PHONE_PEPPER');if(!pepper)throw Error('Servidor não configurado');
const db=createClient(url,key),phone_hash=await hash(pepper+':'+p),token=crypto.randomUUID()+crypto.randomUUID();
const {error}=await db.from('fortune_players').insert({name:n,phone_hash,phone_last4:p.slice(-4),session_hash:await hash(token)});
if(error)throw Error(error.code==='23505'?'Este WhatsApp já participou.':'Cadastro indisponível');
const {data:c}=await db.from('fortune_config').select('authorized,stock').eq('id',1).single();
return new Response(JSON.stringify({session:token,spins_left:3,demo:!c?.authorized,stock:c?.stock??5}),{headers});
}catch(e){return new Response(JSON.stringify({error:String((e as Error).message)}),{status:400,headers})}});