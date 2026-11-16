-- Rollback of 004. Removes ONLY the tables and function added by 004 (and their rows).
-- Users, messages, memories and conversations are not touched.
drop function if exists public.chelsy_my_plan();
drop table if exists public.chelsy_admin_audit;
drop table if exists public.chelsy_activity;
drop table if exists public.chelsy_subscriptions;
