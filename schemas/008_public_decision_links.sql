-- RIGP · Actores de la decisión pública y cruces con el lado receptor
-- Persistencia objetivo multiusuario. Ningún rol o vínculo implica irregularidad por sí mismo.

create table if not exists public_process_actors (
    actor_id text primary key,
    provider_id text not null,
    service_id text not null,
    process_ref text,
    person_name text not null,
    role_type text not null check (role_type in (
        'REQUIRENTE','EVALUADOR','ADJUDICADOR','FIRMANTE',
        'ADMIN_CONTRATO','RECEPCION','AUTORIZA_PAGO','CONTACTO','OTRO'
    )),
    review_status text not null default 'POR_VERIFICAR'
        check (review_status in ('POR_VERIFICAR','ROL_CONFIRMADO','DESCARTADO')),
    source_type text,
    source_name text not null,
    source_url text,
    document_date date,
    valid_from date,
    valid_to date,
    analyst_note text,
    created_by text,
    created_at timestamptz not null default now(),
    updated_by text,
    updated_at timestamptz not null default now()
);

create table if not exists cross_side_relationships (
    cross_id text primary key,
    provider_id text not null,
    benefit_entity_id text references benefit_entities(entity_id),
    public_actor_id text not null references public_process_actors(actor_id),
    relationship_type text not null check (relationship_type in (
        'MISMA_PERSONA','RELACION_SOCIETARIA','RELACION_LABORAL',
        'PARENTESCO','REPRESENTACION','OTRO'
    )),
    review_status text not null default 'POR_VERIFICAR'
        check (review_status in ('POR_VERIFICAR','VINCULO_CONFIRMADO','DESCARTADO')),
    evidence_source text not null,
    evidence_url text,
    document_ref text,
    document_date date,
    temporal_relevance text check (temporal_relevance in (
        'COINCIDENTE','PARCIAL','FUERA_DE_PERIODO','NO_DETERMINADA'
    )),
    analyst_note text,
    created_by text,
    created_at timestamptz not null default now(),
    updated_by text,
    updated_at timestamptz not null default now()
);

-- Evidencia sobre disposición/captura del valor económico. Se mantiene separada
-- de la mera propiedad/control para no confundir vínculo societario con beneficio final.
create table if not exists benefit_value_evidence (
    value_evidence_id text primary key,
    provider_id text not null,
    benefit_entity_id text references benefit_entities(entity_id),
    evidence_type text not null check (evidence_type in (
        'DISTRIBUCION_UTILIDADES','TRANSFERENCIA_POSTERIOR','PAGO_RELACIONADO',
        'ADQUISICION_ACTIVO','CONTROL_DISPOSICION','OTRO'
    )),
    review_status text not null default 'POR_VERIFICAR'
        check (review_status in ('POR_VERIFICAR','EVIDENCIA_CONFIRMADA','DESCARTADA')),
    amount_clp numeric,
    event_date date,
    source_name text not null,
    source_url text,
    document_ref text,
    evidence_note text,
    created_by text,
    created_at timestamptz not null default now(),
    updated_by text,
    updated_at timestamptz not null default now()
);

create view if not exists confirmed_cross_side_links as
select
    c.cross_id,
    c.provider_id,
    c.benefit_entity_id,
    e.display_name as private_entity_name,
    e.entity_type as private_entity_type,
    c.public_actor_id,
    a.person_name as public_actor_name,
    a.service_id,
    a.process_ref,
    a.role_type as public_role,
    c.relationship_type,
    c.temporal_relevance,
    c.evidence_source
from cross_side_relationships c
join benefit_entities e on e.entity_id = c.benefit_entity_id
join public_process_actors a on a.actor_id = c.public_actor_id
where c.review_status = 'VINCULO_CONFIRMADO'
  and a.review_status = 'ROL_CONFIRMADO'
  and c.temporal_relevance in ('COINCIDENTE','PARCIAL');

-- Esta vista identifica entidades con evidencia confirmada de disposición/captura
-- del valor. No determina ilicitud: esa evaluación permanece fuera del score técnico.
create view if not exists documented_value_recipients as
select
    v.provider_id,
    v.benefit_entity_id,
    e.display_name,
    e.entity_type,
    count(*) as confirmed_value_events,
    sum(coalesce(v.amount_clp,0)) as documented_amount_clp,
    min(v.event_date) as first_event_date,
    max(v.event_date) as last_event_date
from benefit_value_evidence v
join benefit_entities e on e.entity_id = v.benefit_entity_id
where v.review_status = 'EVIDENCIA_CONFIRMADA'
group by v.provider_id, v.benefit_entity_id, e.display_name, e.entity_type;
