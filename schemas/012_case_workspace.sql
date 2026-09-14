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

-- All active pilot members may read the shared workspace.
drop policy if exists case_workspace_active_read on rigp.case_workspace_state;
create policy case_workspace_active_read
on rigp.case_workspace_state for select
to authenticated
using (
  exists (
    select 1 from rigp.pilot_member pm
    where pm.user_id = (select auth.uid()) and pm.active
  )
);

-- Only active members explicitly allowed to manage cases may write.
drop policy if exists case_workspace_manage_insert on rigp.case_workspace_state;
create policy case_workspace_manage_insert
on rigp.case_workspace_state for insert
to authenticated
with check (
  updated_by = (select auth.uid())
  and exists (
    select 1 from rigp.pilot_member pm
    where pm.user_id = (select auth.uid())
      and pm.active
      and pm.can_manage_cases
  )
);

drop policy if exists case_workspace_manage_update on rigp.case_workspace_state;
create policy case_workspace_manage_update
on rigp.case_workspace_state for update
to authenticated
using (
  exists (
    select 1 from rigp.pilot_member pm
    where pm.user_id = (select auth.uid())
      and pm.active
      and pm.can_manage_cases
  )
)
with check (
  updated_by = (select auth.uid())
  and exists (
    select 1 from rigp.pilot_member pm
    where pm.user_id = (select auth.uid())
      and pm.active
      and pm.can_manage_cases
  )
);

drop policy if exists case_workspace_event_active_read on rigp.case_workspace_event;
create policy case_workspace_event_active_read
on rigp.case_workspace_event for select
to authenticated
using (
  exists (
    select 1 from rigp.pilot_member pm
    where pm.user_id = (select auth.uid()) and pm.active
  )
);

drop policy if exists case_workspace_event_manage_insert on rigp.case_workspace_event;
create policy case_workspace_event_manage_insert
on rigp.case_workspace_event for insert
to authenticated
with check (
  actor_user_id = (select auth.uid())
  and exists (
    select 1 from rigp.pilot_member pm
    where pm.user_id = (select auth.uid())
      and pm.active
      and pm.can_manage_cases
  )
);

comment on table rigp.case_workspace_state is
  'Shared case-first analyst workspace. Working state only; it does not establish an analytical candidate or wrongdoing.';
comment on table rigp.case_workspace_event is
  'Append-only analyst workspace audit trail written by authenticated case managers.';
