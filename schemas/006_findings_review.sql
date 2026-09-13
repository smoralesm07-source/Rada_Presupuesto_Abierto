-- RIGP findings review v1
-- Persists human validation as a separate, auditable layer.

CREATE TABLE IF NOT EXISTS investigative_findings (
  finding_id TEXT PRIMARY KEY,
  organization_id TEXT,
  provider_id TEXT,
  period_year INTEGER,
  finding_family TEXT NOT NULL,
  attention_level TEXT NOT NULL CHECK (attention_level IN (
    'ATENCION_INMEDIATA','REVISION_PRIORITARIA','SEGUIMIENTO'
  )),
  max_priority_score NUMERIC NOT NULL DEFAULT 0 CHECK (
    max_priority_score >= 0 AND max_priority_score <= 100
  ),
  methodology_version TEXT NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source_payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS finding_reviews (
  review_id BIGSERIAL PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES investigative_findings(finding_id),
  review_status TEXT NOT NULL CHECK (review_status IN (
    'PENDIENTE','EN_REVISION','EXPLICADO','PROFUNDIZAR','ESCALADO'
  )),
  reviewer_id TEXT,
  rationale TEXT,
  evidence_checked JSONB NOT NULL DEFAULT '[]'::jsonb,
  useful_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
  low_value_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  supersedes_review_id BIGINT REFERENCES finding_reviews(review_id)
);

CREATE INDEX IF NOT EXISTS ix_finding_reviews_finding_created
  ON finding_reviews(finding_id, created_at DESC);

CREATE VIEW finding_review_current AS
SELECT *
FROM (
  SELECT r.*,
         row_number() OVER (
           PARTITION BY r.finding_id
           ORDER BY r.created_at DESC, r.review_id DESC
         ) AS rn
  FROM finding_reviews r
) x
WHERE rn = 1;

COMMENT ON TABLE finding_reviews IS
  'Validación humana trazable de hallazgos RIGP; conserva historial y no altera la evidencia ni el resultado original del motor.';
