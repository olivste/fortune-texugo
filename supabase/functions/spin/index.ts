import {createClient} from 'npm:@supabase/supabase-js@2';
const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'authorization,apikey,content-type','Content-Type':'application/json'};
async function hash(s:string){const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s));return Array.from(new Uint8Array(b)).map(x=>x.toString(16).padStart(2,'0')).join('')}
const icons=['🍌','⚜️','🦡','💎','🃏','🍒'];
function random(n:number){const limit=2**32-(2**32%n);let x:number;do{x=crypto.getRandomValues(new Uint32Array(1))[0]}while(x>=limit);return x%n}
Deno.serve(async req=>{if(req.method==='OPTIONS')return new Response('',{headers});try{
if(req.method!=='POST')throw Error('Método inválido');const {session}=await req.json();if(typeof session!=='string'||session.length<60)throw Error('Sessão inválida');
const grid=Array.from({length:3},()=>Array.from({length:3},()=>icons[random(icons.length)]));
const roll=crypto.getRandomValues(new Uint32Array(1))[0]/2**32;
const db=createClient(Deno.env.get('SUPABASE_URL')!,Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);
const {data,error}=await db.rpc('fortune_do_spin',{p_session_hash:await hash(session),p_grid:grid,p_roll:roll});
if(error)throw Error(error.message);return new Response(JSON.stringify(data),{headers});
}catch(e){return new Response(JSON.stringify({error:String((e as Error).message)}),{status:400,headers})}});