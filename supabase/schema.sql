create extension if not exists pgcrypto;
create table public.fortune_config(id int primary key default 1 check(id=1),authorized boolean not null default false,authorization_reference text,prize_probability numeric not null default 0.02 check(prize_probability between 0 and 1),stock int not null default 5 check(stock between 0 and 5),constraint auth_ref check(not authorized or length(trim(coalesce(authorization_reference,'')))>0));
insert into public.fortune_config(id) values(1) on conflict do nothing;
create table public.fortune_players(id uuid primary key default gen_random_uuid(),name text not null,phone_hash text not null unique,phone_last4 text not null,session_hash text not null unique,spins_left int not null default 3 check(spins_left between 0 and 3),created_at timestamptz default now());
create table public.fortune_spins(id uuid primary key default gen_random_uuid(),player_id uuid not null references public.fortune_players(id),won boolean not null,demo boolean not null,grid jsonb not null,created_at timestamptz default now());
create table public.fortune_prizes(id uuid primary key default gen_random_uuid(),player_id uuid not null unique references public.fortune_players(id),claim_code text not null unique,redeemed_at timestamptz,created_at timestamptz default now());
create table public.fortune_admins(user_id uuid primary key references auth.users(id));
alter table public.fortune_config enable row level security;
alter table public.fortune_players enable row level security;
alter table public.fortune_spins enable row level security;
alter table public.fortune_prizes enable row level security;
alter table public.fortune_admins enable row level security;
revoke all on public.fortune_config,public.fortune_players,public.fortune_spins,public.fortune_prizes,public.fortune_admins from anon,authenticated;
create or replace function public.fortune_do_spin(p_session_hash text,p_grid jsonb,p_roll double precision) returns jsonb language plpgsql security definer set search_path=public as $$
declare p public.fortune_players%rowtype;c public.fortune_config%rowtype;won boolean:=false;code text;demo boolean;
begin
select * into p from public.fortune_players where session_hash=p_session_hash for update;
if not found then raise exception 'Sessão inválida';end if;
if p.spins_left<=0 then raise exception 'Seus giros acabaram';end if;
select * into c from public.fortune_config where id=1 for update;
demo:=not c.authorized;
if c.authorized and c.stock>0 and p_roll<c.prize_probability and not exists(select 1 from public.fortune_prizes where player_id=p.id) then
won:=true;code:=upper(encode(gen_random_bytes(8),'hex'));
insert into public.fortune_prizes(player_id,claim_code) values(p.id,code);
update public.fortune_config set stock=stock-1 where id=1;
end if;
update public.fortune_players set spins_left=spins_left-1 where id=p.id;
insert into public.fortune_spins(player_id,won,demo,grid) values(p.id,won,demo,p_grid);
return jsonb_build_object('won',won,'demo',demo,'claim_code',code,'spins_left',p.spins_left-1,'stock',c.stock-(case when won then 1 else 0 end),'grid',p_grid);
end $$;
revoke all on function public.fortune_do_spin(text,jsonb,double precision) from public,anon,authenticated;