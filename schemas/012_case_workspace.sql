-- RIGP case-first multiuser workspace
-- This layer stores analyst working state. It does not create or validate
-- analytical candidate cases and does not modify rigp.candidate_case.

create table if not exists rigp.case_workspace_state (
  case_id text primary key,
  case_ref text not null unique,
  candidate_id text null references rigp.candidate_case(candidate_id) on update cascade on delete set null,
  owner_user_id uuid not null default auth.uid(),
  workspace_status text not null default 'TRIAGE',
  title text,
  organization_id text,
  provider_id text,
  period_year integer,
  attention_level text,
  priority_score numeric,
  payload jsonb not null default '{}'::jsonb,
  updated_by uuid not null default auth.uid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint case_workspace_payload_object check (jsonb_typeof(payload) = 'object')
);

create index if not exists case_workspace_state_updated_idx
  on rigp.case_workspace_state(updated_at desc);
create index if not exists case_workspace_state_owner_idx
  on rigp.case_workspace_state(owner_user_id, workspace_status, updated_at desc);
create index if not exists case_workspace_state_candidate_idx
  on rigp.case_workspace_state(candidate_id)
  where candidate_id is not null;

create table if not exists rigp.case_workspace_event (
  event_id bigint generated always as identity primary key,
  case_id text not null references rigp.case_workspace_state(case_id) on delete cascade,
  actor_user_id uuid not null default auth.uid(),
  event_type text not null,
  detail jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  constraint case_workspace_event_detail_object check (jsonb_typeof(detail) = 'object')
);

create index if not exists case_workspace_event_case_idx
  on rigp.case_workspace_event(case_id, occurred_at desc);

alter table rigp.case_workspace_state enable row level security;
alter table rigp.case_workspace_event enable row level security;

revoke all on table rigp.case_workspace_state from anon;
revoke all on table rigp.case_workspace_event from anon;

grant usage on schema rigp to authenticated;
grant select, insert, update on table rigp.case_workspace_state to authenticated;
grant select, insert on table rigp.case_workspace_event to authenticated;
grant usage, select on sequence rigp.case_workspace_event_event_id_seq to authenticated;

-- Membership stays encapsulated behind the pre-existing authenticated-only session
-- function. authenticated has no direct SELECT on rigp.pilot_member by design.
drop policy if exists case_workspace_active_read on rigp.case_workspace_state;
create policy case_workspace_active_read
on rigp.case_workspace_state for select
to authenticated
using (
  (select public.rigp_ops_get_session()->>'user_id') = (select auth.uid())::text
);

drop policy if exists case_workspace_manage_insert on rigp.case_workspace_state;
create policy case_workspace_manage_insert
on rigp.case_workspace_state for insert
to authenticated
with check (
  updated_by = (select auth.uid())
  and (select public.rigp_ops_get_session()->>'role') in ('ADMIN','ANALYST')
);

drop policy if exists case_workspace_manage_update on rigp.case_workspace_state;
create policy case_workspace_manage_update
on rigp.case_workspace_state for update
to authenticated
using (
  (select public.rigp_ops_get_session()->>'role') in ('ADMIN','ANALYST')
)
with check (
  updated_by = (select auth.uid())
  and (select public.rigp_ops_get_session()->>'role') in ('ADMIN','ANALYST')
);

drop policy if exists case_workspace_event_active_read on rigp.case_workspace_event;
create policy case_workspace_event_active_read
on rigp.case_workspace_event for select
to authenticated
using (
  (select public.rigp_ops_get_session()->>'user_id') = (select auth.uid())::text
);

drop policy if exists case_workspace_event_manage_insert on rigp.case_workspace_event;
create policy case_workspace_event_manage_insert
on rigp.case_workspace_event for insert
to authenticated
with check (
  actor_user_id = (select auth.uid())
  and (select public.rigp_ops_get_session()->>'role') in ('ADMIN','ANALYST')
);

-- Public-schema facades keep the private rigp schema out of the browser Data API.
-- They run as the caller, so table grants and RLS remain effective.
create or replace function public.rigp_case_workspace_load()
returns jsonb
language sql
security invoker
set search_path = public, rigp, auth, pg_temp
as $$
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'case_id', s.case_id,
        'case_ref', s.case_ref,
        'owner_user_id', s.owner_user_id,
        'payload', s.payload,
        'updated_at', s.updated_at
      ) order by s.updated_at desc
    ),
    '[]'::jsonb
  )
  from rigp.case_workspace_state s;
$$;

revoke all on function public.rigp_case_workspace_load() from public;
revoke all on function public.rigp_case_workspace_load() from anon;
grant execute on function public.rigp_case_workspace_load() to authenticated;

create or replace function public.rigp_case_workspace_sync(
  p_cases jsonb,
  p_reason text default 'SYNC',
  p_repository_version text default null
)
returns jsonb
language plpgsql
security invoker
set search_path = public, rigp, auth, pg_temp
as $$
declare
  v_uid uuid := auth.uid();
  v_item jsonb;
  v_count integer := 0;
  v_case_id text;
  v_case_ref text;
  v_event_type text;
begin
  if v_uid is null then
    raise exception 'authentication required' using errcode='28000';
  end if;

  perform public.rigp_ops_get_session();

  if jsonb_typeof(coalesce(p_cases,'[]'::jsonb)) <> 'array' then
    raise exception 'p_cases must be a JSON array' using errcode='22023';
  end if;

  v_event_type := left(
    upper(regexp_replace(coalesce(nullif(p_reason,''),'SYNC'),'[^A-Za-z0-9_-]+','_','g')),
    80
  );

  for v_item in select value from jsonb_array_elements(coalesce(p_cases,'[]'::jsonb))
  loop
    v_case_id := nullif(v_item->>'case_id','');
    v_case_ref := nullif(v_item->>'case_ref','');
    if v_case_id is null or v_case_ref is null then
      raise exception 'case_id and case_ref are required' using errcode='22023';
    end if;

    insert into rigp.case_workspace_state(
      case_id,case_ref,candidate_id,owner_user_id,workspace_status,title,
      organization_id,provider_id,period_year,attention_level,priority_score,
      payload,updated_by,updated_at
    ) values (
      v_case_id,
      v_case_ref,
      nullif(v_item#>>'{source_context,candidate_id}',''),
      v_uid,
      coalesce(nullif(v_item->>'status',''),'TRIAGE'),
      nullif(v_item->>'title',''),
      nullif(v_item->>'organization_id',''),
      nullif(v_item->>'provider_id',''),
      case when (v_item->>'period_year') ~ '^[0-9]{4}$' then (v_item->>'period_year')::integer else null end,
      nullif(v_item->>'attention_level',''),
      case when (v_item->>'priority_score') ~ '^-?[0-9]+([.][0-9]+)?$' then (v_item->>'priority_score')::numeric else null end,
      v_item,
      v_uid,
      now()
    )
    on conflict (case_id) do update set
      case_ref = excluded.case_ref,
      candidate_id = coalesce(excluded.candidate_id, rigp.case_workspace_state.candidate_id),
      workspace_status = excluded.workspace_status,
      title = excluded.title,
      organization_id = excluded.organization_id,
      provider_id = excluded.provider_id,
      period_year = excluded.period_year,
      attention_level = excluded.attention_level,
      priority_score = excluded.priority_score,
      payload = excluded.payload,
      updated_by = v_uid,
      updated_at = now();

    insert into rigp.case_workspace_event(case_id,actor_user_id,event_type,detail)
    values (
      v_case_id,
      v_uid,
      v_event_type,
      jsonb_build_object(
        'case_ref',v_case_ref,
        'status',v_item->>'status',
        'repository_version',p_repository_version
      )
    );

    v_count := v_count + 1;
  end loop;

  return jsonb_build_object('synced',v_count,'synced_at',now());
end;
$$;

revoke all on function public.rigp_case_workspace_sync(jsonb,text,text) from public;
revoke all on function public.rigp_case_workspace_sync(jsonb,text,text) from anon;
grant execute on function public.rigp_case_workspace_sync(jsonb,text,text) to authenticated;

comment on table rigp.case_workspace_state is
  'Shared case-first analyst workspace. Working state only; it does not establish an analytical candidate or wrongdoing.';
comment on table rigp.case_workspace_event is
  'Append-only analyst workspace audit trail written by authenticated case managers.';
comment on function public.rigp_case_workspace_load() is
  'Authenticated SECURITY INVOKER facade for reading the RIGP case-first workspace under RLS.';
comment on function public.rigp_case_workspace_sync(jsonb,text,text) is
  'Authenticated SECURITY INVOKER facade for atomic case workspace state + audit events under RLS.';
