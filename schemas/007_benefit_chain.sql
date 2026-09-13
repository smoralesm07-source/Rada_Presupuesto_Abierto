-- RIGP · Cadena de beneficio / propiedad / control
-- Arquitectura objetivo para persistencia multiusuario.
-- Un vínculo confirmado NO implica participación en un ilícito ni beneficio ilícito.

create table if not exists benefit_entities (
    entity_id text primary key,
    entity_type text not null check (entity_type in ('PERSONA','SOCIEDAD','OTRO')),
    rut text,
    display_name text not null,
    normalized_name text,
    source_first_seen text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists benefit_relationships (
    relationship_id text primary key,
    provider_id text not null,
    related_entity_id text not null references benefit_entities(entity_id),
    role_type text not null check (role_type in ('CONTROL','REPRESENTACION','DIRECCION','RELACION_ECONOMICA','OTRO')),
    review_status text not null default 'POR_VERIFICAR' check (review_status in ('POR_VERIFICAR','VINCULO_CONFIRMADO','DESCARTADO')),
    valid_from date,
    valid_to date,
    temporal_relevance text check (temporal_relevance in ('COINCIDENTE','PARCIAL','FUERA_DE_PERIODO','NO_DETERMINADA')),
    analyst_note text,
    created_by text,
    created_at timestamptz not null default now(),
    updated_by text,
    updated_at timestamptz not null default now()
);

create table if not exists benefit_relationship_evidence (
    evidence_id text primary key,
    relationship_id text not null references benefit_relationships(relationship_id) on delete cascade,
    source_type text not null,
    source_name text not null,
    source_url text,
    document_ref text,
    document_date date,
    observed_at timestamptz not null default now(),
    evidence_note text,
    content_hash text,
    created_by text,
    created_at timestamptz not null default now()
);

create table if not exists benefit_source_checks (
    provider_id text not null,
    source_id text not null,
    status text not null default 'PENDIENTE' check (status in ('PENDIENTE','REVISADO_CON_ANTECEDENTES','REVISADO_SIN_ANTECEDENTES')),
    checked_by text,
    checked_at timestamptz,
    note text,
    primary key (provider_id, source_id)
);

create view if not exists benefit_confirmed_convergence as
select
    e.entity_id,
    e.entity_type,
    e.rut,
    e.display_name,
    count(distinct r.provider_id) as linked_providers,
    array_agg(distinct r.provider_id) as provider_ids,
    array_agg(distinct r.role_type) as role_types
from benefit_relationships r
join benefit_entities e on e.entity_id = r.related_entity_id
where r.review_status = 'VINCULO_CONFIRMADO'
group by e.entity_id, e.entity_type, e.rut, e.display_name
having count(distinct r.provider_id) >= 2;
