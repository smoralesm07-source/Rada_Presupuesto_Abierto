-- RIGP case model v1
-- El expediente reemplaza al hallazgo aislado como unidad principal de trabajo.
-- Diseñado para PostgreSQL/Supabase. La UI estática puede usar el mismo contrato
-- en almacenamiento local durante el piloto, pero producción debe persistir aquí.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS rigp_cases (
  case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_ref TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'TRIAGE' CHECK (status IN (
    'TRIAGE','EN_REVISION','PROFUNDIZAR','EXPLICADO','ESCALADO','CERRADO'
  )),
  priority_score NUMERIC NOT NULL DEFAULT 0 CHECK (
    priority_score >= 0 AND priority_score <= 100
  ),
  attention_level TEXT NOT NULL DEFAULT 'SEGUIMIENTO' CHECK (attention_level IN (
    'ATENCION_INMEDIATA','REVISION_PRIORITARIA','SEGUIMIENTO'
  )),
  hypothesis TEXT,
  scope TEXT,
  conclusion TEXT,
  organization_id TEXT,
  provider_id TEXT,
  period_year INTEGER,
  assigned_to TEXT,
  created_by TEXT,
  methodology_version TEXT NOT NULL DEFAULT 'RIGP-CASE-v1',
  source_context JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rigp_case_findings (
  case_id UUID NOT NULL REFERENCES rigp_cases(case_id) ON DELETE CASCADE,
  finding_id TEXT NOT NULL,
  relation_role TEXT NOT NULL DEFAULT 'ORIGEN' CHECK (relation_role IN (
    'ORIGEN','RELACIONADO','CONTEXTO'
  )),
  added_by TEXT,
  added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (case_id, finding_id)
);

CREATE TABLE IF NOT EXISTS rigp_case_evidence (
  evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES rigp_cases(case_id) ON DELETE CASCADE,
  evidence_kind TEXT NOT NULL CHECK (evidence_kind IN (
    'PRESUPUESTO','CONTRATACION','PAGO','ENTIDAD','PROPIEDAD','ACTOR',
    'CGR','SII','OSINT','RED','OTRO'
  )),
  verification_status TEXT NOT NULL DEFAULT 'CANDIDATA' CHECK (verification_status IN (
    'CANDIDATA','VERIFICADA','DESCARTADA','NO_DISPONIBLE'
  )),
  source_type TEXT,
  source_ref TEXT,
  summary TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rigp_case_notes (
  note_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES rigp_cases(case_id) ON DELETE CASCADE,
  note_type TEXT NOT NULL DEFAULT 'ANALISIS' CHECK (note_type IN (
    'ANALISIS','HIPOTESIS','PENDIENTE','DECISION','CONCLUSION'
  )),
  body TEXT NOT NULL,
  author_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rigp_case_events (
  event_id BIGSERIAL PRIMARY KEY,
  case_id UUID NOT NULL REFERENCES rigp_cases(case_id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  actor_id TEXT,
  event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_rigp_cases_status_priority
  ON rigp_cases(status, priority_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_rigp_cases_org_provider
  ON rigp_cases(organization_id, provider_id, period_year);
CREATE INDEX IF NOT EXISTS ix_rigp_case_findings_finding
  ON rigp_case_findings(finding_id);
CREATE INDEX IF NOT EXISTS ix_rigp_case_evidence_case_status
  ON rigp_case_evidence(case_id, verification_status, evidence_kind);
CREATE INDEX IF NOT EXISTS ix_rigp_case_events_case_created
  ON rigp_case_events(case_id, created_at DESC);

CREATE OR REPLACE VIEW rigp_case_summary AS
SELECT
  c.*,
  count(DISTINCT cf.finding_id) AS finding_count,
  count(DISTINCT e.evidence_id) AS evidence_count,
  count(DISTINCT e.evidence_id) FILTER (WHERE e.verification_status='VERIFICADA') AS verified_evidence_count,
  max(ev.created_at) AS last_event_at
FROM rigp_cases c
LEFT JOIN rigp_case_findings cf ON cf.case_id=c.case_id
LEFT JOIN rigp_case_evidence e ON e.case_id=c.case_id
LEFT JOIN rigp_case_events ev ON ev.case_id=c.case_id
GROUP BY c.case_id;

COMMENT ON TABLE rigp_cases IS
  'Expediente persistente RIGP. Un expediente organiza hallazgos, evidencia, actores, hipótesis, revisión y conclusión; no equivale a una imputación ni acredita delito.';
COMMENT ON TABLE rigp_case_evidence IS
  'Evidencia candidata o verificada asociada al expediente. El estado CANDIDATA nunca debe presentarse como hecho confirmado.';
