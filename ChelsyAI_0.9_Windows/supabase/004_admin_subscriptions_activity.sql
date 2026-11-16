-- Chelsy AI 0.9.3 — migration 004: subscriptions, account activity, admin audit.
-- Additive and idempotent: creates new tables only, never changes or deletes existing rows or users.
--
-- Who can do what:
--   * a signed-in user (role authenticated) may READ only their own subscriptions and activity;
--   * nobody writes these tables from the website, Desktop, Windows Client or Android;
--   * only Chelsy Host (server side, with the project's secret key that never leaves the host)
--     grants subscriptions, records activity and writes the admin audit log.

create table if not exists public.chelsy_subscriptions (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  plan        text not null check (plan in ('start', 'plus', 'pro', 'team')),
  status      text not null default 'active' check (status in ('active', 'revoked')),
  starts_at   timestamptz not null default now(),
  ends_at     timestamptz,
  granted_by  uuid,
  note        text check (note is null or char_length(note) <= 500),
  created_at  timestamptz not null default now(),
  revoked_at  timestamptz,
  constraint chelsy_subscriptions_period check (ends_at is null or ends_at > starts_at)
);
create index if not exists chelsy_subscriptions_user_idx on public.chelsy_subscriptions (user_id, status, ends_at);

create table if not exists public.chelsy_activity (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  kind        text not null check (char_length(kind) between 1 and 40),
  detail      text check (detail is null or char_length(detail) <= 300),
  device      text check (device is null or char_length(device) <= 40),
  created_at  timestamptz not null default now()
);
create index if not exists chelsy_activity_user_idx on public.chelsy_activity (user_id, created_at desc);
create index if not exists chelsy_activity_time_idx on public.chelsy_activity (created_at desc);

create table if not exists public.chelsy_admin_audit (
  id          bigint generated always as identity primary key,
  admin_id    uuid not null,
  action      text not null check (char_length(action) between 1 and 60),
  target_id   uuid,
  details     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists chelsy_admin_audit_time_idx on public.chelsy_admin_audit (created_at desc);

alter table public.chelsy_subscriptions enable row level security;
alter table public.chelsy_activity enable row level security;
alter table public.chelsy_admin_audit enable row level security;

-- Clients may only read their own rows; no client write paths at all.
revoke all on public.chelsy_subscriptions, public.chelsy_activity, public.chelsy_admin_audit from anon, authenticated;
grant select on public.chelsy_subscriptions, public.chelsy_activity to authenticated;

drop policy if exists chelsy_subscriptions_select_own on public.chelsy_subscriptions;
create policy chelsy_subscriptions_select_own on public.chelsy_subscriptions for select to authenticated
  using (user_id = auth.uid());
drop policy if exists chelsy_activity_select_own on public.chelsy_activity;
create policy chelsy_activity_select_own on public.chelsy_activity for select to authenticated
  using (user_id = auth.uid());
-- chelsy_admin_audit: RLS on and no policy => invisible to every client role.

-- The caller's current plan ('start' when nothing active). No parameter: nobody can ask about others.
create or replace function public.chelsy_my_plan()
returns text
language sql
stable
security definer
set search_path = public
as $$
  select coalesce((
    select s.plan
      from public.chelsy_subscriptions s
     where s.user_id = auth.uid()
       and s.status = 'active'
       and s.starts_at <= now()
       and (s.ends_at is null or s.ends_at > now())
     order by array_position(array['start','plus','pro','team'], s.plan) desc, s.ends_at desc nulls first
     limit 1), 'start')
$$;
revoke all on function public.chelsy_my_plan() from public;
grant execute on function public.chelsy_my_plan() to authenticated;
