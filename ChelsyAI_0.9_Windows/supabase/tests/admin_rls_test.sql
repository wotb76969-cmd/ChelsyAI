-- Real-database checks for 004: clients can only read their own subscription/activity,
-- cannot write anything, cannot see the admin audit; chelsy_my_plan() picks the right plan.
\set ON_ERROR_STOP 1
insert into auth.users(id,email) values
  ('11111111-1111-4111-8111-111111111111','alice@example.org'),
  ('22222222-2222-4222-8222-222222222222','bob@example.org')
on conflict do nothing;

-- Host (table owner / service role) grants plans and records activity.
insert into public.chelsy_subscriptions(user_id, plan, starts_at, ends_at, note) values
  ('11111111-1111-4111-8111-111111111111', 'plus', now(), now() + interval '30 days', 'тест'),
  ('11111111-1111-4111-8111-111111111111', 'pro',  now(), now() + interval '1 hour', 'истекает скоро'),
  ('22222222-2222-4222-8222-222222222222', 'pro',  now() - interval '2 days', now() - interval '1 second', 'уже истекла');
insert into public.chelsy_activity(user_id, kind, detail, device) values
  ('11111111-1111-4111-8111-111111111111', 'chat', 'local · 120 симв.', 'android'),
  ('22222222-2222-4222-8222-222222222222', 'login', null, 'windows');
insert into public.chelsy_admin_audit(admin_id, action, target_id) values
  ('11111111-1111-4111-8111-111111111111', 'grant', '22222222-2222-4222-8222-222222222222');

set role authenticated;
select set_config('request.jwt.claim.sub','11111111-1111-4111-8111-111111111111', false);
do $$ begin
  if (select count(*) from public.chelsy_subscriptions) <> 2 then raise exception 'alice must see exactly her 2 subscriptions'; end if;
  if (select count(*) from public.chelsy_activity) <> 1 then raise exception 'alice must see only her activity'; end if;
  if public.chelsy_my_plan() <> 'pro' then raise exception 'alice plan should be pro (highest active), got %', public.chelsy_my_plan(); end if;
end $$;
do $$ declare failed boolean := false; begin
  begin perform 1 from public.chelsy_admin_audit; exception when insufficient_privilege then failed := true; end;
  if not failed then raise exception 'admin audit must be unreadable for clients'; end if;
end $$;
do $$ declare failed boolean := false; begin
  begin
    insert into public.chelsy_subscriptions(user_id, plan) values ('11111111-1111-4111-8111-111111111111', 'team');
  exception when insufficient_privilege then failed := true; end;
  if not failed then raise exception 'a client granted itself a subscription'; end if;
end $$;
do $$ declare failed boolean := false; begin
  begin update public.chelsy_subscriptions set ends_at = null; exception when insufficient_privilege then failed := true; end;
  if not failed then raise exception 'a client extended a subscription'; end if;
end $$;
do $$ declare failed boolean := false; begin
  begin insert into public.chelsy_activity(user_id, kind) values ('11111111-1111-4111-8111-111111111111', 'fake');
  exception when insufficient_privilege then failed := true; end;
  if not failed then raise exception 'a client wrote activity'; end if;
end $$;

select set_config('request.jwt.claim.sub','22222222-2222-4222-8222-222222222222', false);
do $$ begin
  if (select count(*) from public.chelsy_subscriptions) <> 1 then raise exception 'bob must see only his subscription'; end if;
  if public.chelsy_my_plan() <> 'start' then raise exception 'expired plan must fall back to start'; end if;
end $$;

set role anon;
select set_config('request.jwt.claim.sub','', false);
do $$ declare failed boolean := false; begin
  begin perform 1 from public.chelsy_subscriptions; exception when insufficient_privilege then failed := true; end;
  if not failed then raise exception 'anon must not read subscriptions'; end if;
end $$;
reset role;
select 'admin RLS checks: OK' as result;
