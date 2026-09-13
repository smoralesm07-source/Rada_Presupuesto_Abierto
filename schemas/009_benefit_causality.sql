-- RIGP · Persistencia futura de antecedente externo y nexo causal del beneficio
-- PostgreSQL / Supabase oriented. Pilot UI currently persists locally in browser.

create table if not exists integrity_basis_evidence (
  basis_id text primary key,
  provider_id text not null,
  service_id text,
  process_ref text,
  evidence_type text not null check (evidence_type in ('CGR','ADMIN','JUDICIAL','CONTRACT','AUDIT','OTHER')),
  source_name text not null,
  source_url text,
  document_ref text,
  event_date date,
  summary text not null,
  review_status text not null default 'POR_VERIFICAR' check (review_status in ('POR_VERIFICAR','EVIDENCIA_CONFIRMADA','DESCARTADA')),
  created_by text,
  reviewed_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_integrity_basis_provider on integrity_basis_evidence(provider_id);
create index if not exists idx_integrity_basis_status on integrity_basis_evidence(review_status);

create table if not exists benefit_causal_links (
  causal_id text primary key,
  provider_id text not null,
  basis_id text not null references integrity_basis_evidence(basis_id),
  value_evidence_id text not null,
  entity_name text not null,
  entity_type text not null default 'ENTIDAD',
  evidence_type text,
  source_name text not null,
  source_url text,
  document_ref text,
  note text not null,
  review_status text not null default 'POR_VERIFICAR' check (review_status in ('POR_VERIFICAR','NEXO_DOCUMENTADO','DESCARTADO')),
  created_by text,
  reviewed_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_benefit_causal_provider on benefit_causal_links(provider_id);
create index if not exists idx_benefit_causal_entity on benefit_causal_links(entity_name);
create index if not exists idx_benefit_causal_status on benefit_causal_links(review_status);

create or replace view benefit_causality_current as
select
  c.causal_id,
  c.provider_id,
  c.entity_name,
  c.entity_type,
  c.value_evidence_id,
  c.review_status as causal_status,
  c.source_name as causal_source,
  c.document_ref as causal_document_ref,
  c.note as causal_note,
  b.basis_id,
  b.evidence_type as basis_type,
  b.source_name as basis_source,
  b.document_ref as basis_document_ref,
  b.event_date as basis_event_date,
  b.summary as basis_summary,
  b.review_status as basis_status,
  c.updated_at
from benefit_causal_links c
join integrity_basis_evidence b on b.basis_id = c.basis_id;

comment on table integrity_basis_evidence is 'Antecedentes externos verificables asociados a un receptor priorizado. EVIDENCIA_CONFIRMADA acredita existencia/contenido del documento, no delito ni responsabilidad.';
comment on table benefit_causal_links is 'Nexos documentales entre un antecedente externo y una evidencia económica de beneficio. NEXO_DOCUMENTADO no equivale a calificación jurídica de ilicitud.';
