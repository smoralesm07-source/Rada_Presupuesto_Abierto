-- RIGP · Personas del lado de la decisión pública y cruces documentados
-- Arquitectura objetivo para persistencia multiusuario.
-- Un rol o vínculo confirmado acredita solamente la relación documentada.

create table if not exists decision_actors (
    actor_id text primary key,
    provider_id text not null,
    organization_id text not null,
    process_ref text,
    display_name text not null,
    role_type text not null check (role_type in (
        'REQUIRENTE','EVALUADOR','ADJUDICADOR','FIRMANTE','ADMIN_CONTRATO',
        'RECEPCION','AUTORIZA_PAGO','CONTACTO','OTRO'
    )),
    review_status text not null default 'POR_VERIFICAR'
        check (review_status in ('POR_VERIFICAR','ROL_CONFIRMADO','DESCARTADO')),
    valid_from date,
    valid_to date,
    analyst_note text,
    created_by text,
    created_at timestamptz not null default now(),
    updated_by text,
    updated_at timestamptz not null default now()
);

create table if not exists decision_actor_evidence (
    evidence_id text primary key,
    actor_id text not null references decision_actors(actor_id) on delete cascade,
    source_type text not null,
    source_name text not null,
    source_url text,
    document_ref text,
    document_date date,
    evidence_note text,
    content_hash text,
    created_by text,
    created_at timestamptz not null default now()
);

create table if not exists cross_side_relationships (
    cross_id text primary key,
    provider_id text not null,
    benefit_entity_id text references benefit_entities(entity_id),
    decision_actor_id text not null references decision_actors(actor_id),
    relationship_type text not null check (relationship_type in (
        'MISMA_PERSONA','RELACION_SOCIETARIA','RELACION_LABORAL','PARENTESCO',
        'REPRESENTACION','OTRO'
    )),
    review_status text not null default 'POR_VERIFICAR'
        check (review_status in ('POR_VERIFICAR','VINCULO_CONFIRMADO','DESCARTADO')),
    valid_from date,
    valid_to date,
    temporal_relevance text check (temporal_relevance in (
        'COINCIDENTE','PARCIAL','FUERA_DE_PERIODO','NO_DETERMINADA'
    )),
    analyst_note text,
    created_by text,
    created_at timestamptz not null default now(),
    updated_by text,
    updated_at timestamptz not null default now()
);

create table if not exists cross_side_evidence (
    evidence_id text primary key,
    cross_id text not null references cross_side_relationships(cross_id) on delete cascade,
    source_type text not null,
    source_name text not null,
    source_url text,
    document_ref text,
    document_date date,
    evidence_note text,
    content_hash text,
    created_by text,
    created_at timestamptz not null default now()
);

create view if not exists confirmed_cross_side_links as
select
    c.cross_id,
    c.provider_id,
    c.benefit_entity_id,
    b.display_name as benefit_entity_name,
    b.entity_type as benefit_entity_type,
    c.decision_actor_id,
    d.display_name as public_actor_name,
    d.organization_id,
    d.process_ref,
    d.role_type as public_role,
    c.relationship_type,
    c.temporal_relevance
from cross_side_relationships c
join decision_actors d on d.actor_id = c.decision_actor_id
left join benefit_entities b on b.entity_id = c.benefit_entity_id
where c.review_status = 'VINCULO_CONFIRMADO'
  and d.review_status = 'ROL_CONFIRMADO';
