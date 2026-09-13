-- RIGP · Persistencia futura para resolución de propiedad/control e identidad.
-- PostgreSQL / Supabase oriented. Pilot UI currently persists locally.

create table if not exists ownership_identity_links (
  ownership_link_id text primary key,
  provider_id text not null,
  entity_name text not null,
  entity_type text not null check (entity_type in ('PERSONA','SOCIEDAD')),
  entity_rut text,
  identity_status text not null default 'CANDIDATO_POR_NOMBRE'
    check (identity_status in ('RUT_CONFIRMADO','IDENTIDAD_DOCUMENTADA_SIN_RUT','CANDIDATO_POR_NOMBRE','DESCARTADO')),
  relationship_role text not null
    check (relationship_role in ('CONTROL','REPRESENTACION','DIRECCION','RELACION_ECONOMICA','OTRO')),
  source_type text,
  source_name text not null,
  source_url text,
  source_ref text,
  valid_from date,
  valid_to date,
  temporal_relevance text not null default 'NO_DETERMINADA'
    check (temporal_relevance in ('COINCIDENTE','PARCIAL','FUERA_DE_PERIODO','NO_DETERMINADA')),
  review_status text not null default 'POR_VERIFICAR'
    check (review_status in ('POR_VERIFICAR','VINCULO_CONFIRMADO','DESCARTADO')),
  note text,
  created_by text,
  reviewed_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_ownership_identity_provider on ownership_identity_links(provider_id);
create index if not exists idx_ownership_identity_rut on ownership_identity_links(entity_rut) where entity_rut is not null;
create index if not exists idx_ownership_identity_status on ownership_identity_links(identity_status, review_status);
create index if not exists idx_ownership_identity_temporal on ownership_identity_links(temporal_relevance);

-- Convergencia transversal segura: sólo RUT confirmado + vínculo confirmado + vigencia útil.
create or replace view ownership_confirmed_convergence as
select
  entity_rut,
  min(entity_name) as representative_name,
  count(distinct provider_id) as provider_count,
  array_agg(distinct provider_id order by provider_id) as provider_ids,
  array_agg(distinct relationship_role order by relationship_role) as roles
from ownership_identity_links
where identity_status = 'RUT_CONFIRMADO'
  and review_status = 'VINCULO_CONFIRMADO'
  and temporal_relevance in ('COINCIDENTE','PARCIAL')
  and entity_rut is not null
  and entity_rut <> ''
group by entity_rut
having count(distinct provider_id) >= 2;

create or replace view ownership_resolution_current as
select
  provider_id,
  count(*) filter (where review_status='VINCULO_CONFIRMADO') as confirmed_links,
  count(*) filter (where review_status='VINCULO_CONFIRMADO' and entity_type='PERSONA') as confirmed_people,
  count(*) filter (where review_status='VINCULO_CONFIRMADO' and identity_status='RUT_CONFIRMADO') as rut_confirmed_links,
  count(*) filter (
    where review_status='VINCULO_CONFIRMADO'
      and temporal_relevance in ('COINCIDENTE','PARCIAL')
      and relationship_role in ('CONTROL','REPRESENTACION','DIRECCION')
  ) as current_control_or_representation,
  max(updated_at) as last_updated_at
from ownership_identity_links
group by provider_id;

comment on table ownership_identity_links is 'Vínculos documentados de propiedad, control, administración, representación u otra relación privada. Coincidencia nominal por sí sola no confirma identidad.';
comment on view ownership_confirmed_convergence is 'Convergencia automática entre receptores sólo para RUT confirmado; evita fusionar homónimos sin identificador fuerte.';
