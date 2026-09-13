-- RIGP case management v1
--
-- El expediente como objeto persistente, con responsable, ciclo de vida,
-- evidencia fechada y una bitácora de decisiones que sólo crece. Reemplaza el
-- estado disperso en el navegador, que no tenía identidad, ni cadena de
-- custodia, ni forma de traspasar el trabajo a un revisor.
--
-- El contrato es el mismo que aplican `src/radar_presupuesto/case_model.py` y el
-- front: un expediente exportado desde el navegador puede cargarse aquí sin
-- transformación.

CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN (
    'ABIERTO','EN_REVISION','EN_ESPERA_DOCUMENTO','ESCALADO',
    'CERRADO_EXPLICADO','CERRADO_SIN_MERITO'
  )),
  owner TEXT,
  organization_id TEXT NOT NULL,
  organization_name TEXT,
  provider_id TEXT,
  provider_name TEXT,
  period_year INTEGER,
  finding_id TEXT,
  -- Los dos ejes viajan separados a propósito: mezclarlos fue lo que produjo
  -- una cola encabezada por una factura de combustible.
  review_priority_score NUMERIC NOT NULL DEFAULT 0
    CHECK (review_priority_score BETWEEN 0 AND 100),
  laft_compatibility_score NUMERIC NOT NULL DEFAULT 0
    CHECK (laft_compatibility_score BETWEEN 0 AND 100),
  opacity_level TEXT NOT NULL DEFAULT 'TRAZABLE'
    CHECK (opacity_level IN ('TRAZABLE','PARCIAL','OPACA')),
  hypothesis_typology TEXT,
  hypothesis_statement TEXT,
  source_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
  verification_chain JSONB NOT NULL DEFAULT '[]'::jsonb,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  content_sha256 TEXT
);

CREATE TABLE IF NOT EXISTS case_entities (
  case_entity_id BIGSERIAL PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  entity_id TEXT NOT NULL,
  entity_name TEXT,
  rut TEXT,
  role TEXT NOT NULL,
  identity_status TEXT NOT NULL DEFAULT 'UNRESOLVED'
    CHECK (identity_status IN ('RESOLVED','UNRESOLVED')),
  -- Todo vínculo nace CANDIDATE y sólo un analista puede confirmarlo.
  link_status TEXT NOT NULL DEFAULT 'CANDIDATE'
    CHECK (link_status IN ('CANDIDATE','CONFIRMED','DISCARDED')),
  source TEXT,
  added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (case_id, entity_id, role)
);

CREATE TABLE IF NOT EXISTS case_evidence (
  evidence_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN (
    'DOCUMENTO_OFICIAL','REGISTRO_PUBLICO','PUBLICACION_PRENSA',
    'CAPTURA_SISTEMA','ANALISIS_PROPIO','RESPUESTA_TRANSPARENCIA'
  )),
  title TEXT NOT NULL CHECK (length(trim(title)) > 0),
  source_url TEXT,
  captured_at TIMESTAMPTZ NOT NULL,
  sha256 TEXT,
  note TEXT,
  added_by TEXT,
  added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS case_notes (
  note_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  author TEXT,
  text TEXT NOT NULL CHECK (length(trim(text)) > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Bitácora append-only. Es la cadena de custodia del expediente: sin ella no hay
-- forma de saber quién concluyó qué, ni de sostener el trabajo ante un tercero.
CREATE TABLE IF NOT EXISTS case_decisions (
  decision_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
  actor TEXT,
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  -- Cerrar exige motivo: ese motivo es el insumo de recalibración del score.
  rationale TEXT NOT NULL CHECK (
    to_state NOT IN ('CERRADO_EXPLICADO','CERRADO_SIN_MERITO')
    OR length(trim(rationale)) > 0
  ),
  decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cases_state ON cases(state);
CREATE INDEX IF NOT EXISTS idx_cases_owner ON cases(owner);
CREATE INDEX IF NOT EXISTS idx_cases_focus ON cases(organization_id, provider_id, period_year);
CREATE INDEX IF NOT EXISTS idx_case_decisions_case ON case_decisions(case_id, decided_at);
CREATE INDEX IF NOT EXISTS idx_case_entities_entity ON case_entities(entity_id);

-- Lo que el analista cerró y por qué. Alimenta la recalibración del score y hoy
-- se perdía por completo al limpiar el navegador.
CREATE OR REPLACE VIEW case_outcomes AS
SELECT c.case_id,
       c.organization_id,
       c.provider_id,
       c.period_year,
       c.review_priority_score,
       c.laft_compatibility_score,
       c.hypothesis_typology,
       c.state,
       d.rationale AS closing_rationale,
       d.decided_at AS closed_at,
       d.actor AS closed_by
FROM cases c
LEFT JOIN LATERAL (
  SELECT rationale, decided_at, actor
  FROM case_decisions
  WHERE case_id = c.case_id
    AND to_state IN ('CERRADO_EXPLICADO','CERRADO_SIN_MERITO')
  ORDER BY decided_at DESC
  LIMIT 1
) d ON TRUE;
