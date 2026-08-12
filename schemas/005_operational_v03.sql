-- Radar Presupuesto Abierto v0.3 operational
-- Separates physical source-row identity from documentary/economic fingerprint and
-- materializes explainable investigation prioritization.

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS source_row_number BIGINT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transaction_fingerprint TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_source_row
  ON transactions(source_file, source_row_number)
  WHERE source_file IS NOT NULL AND source_row_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_transactions_fingerprint
  ON transactions(transaction_fingerprint);

CREATE TABLE IF NOT EXISTS investigation_queue (
  signal_id TEXT PRIMARY KEY,
  investigation_priority_score NUMERIC NOT NULL CHECK (
    investigation_priority_score >= 0 AND investigation_priority_score <= 100
  ),
  priority_tier TEXT NOT NULL CHECK (priority_tier IN ('P1','P2','P3')),
  severity_component NUMERIC NOT NULL DEFAULT 0,
  signal_component NUMERIC NOT NULL DEFAULT 0,
  cooccurrence_component NUMERIC NOT NULL DEFAULT 0,
  external_evidence_component NUMERIC NOT NULL DEFAULT 0,
  actionability_component NUMERIC NOT NULL DEFAULT 0,
  materiality_component NUMERIC NOT NULL DEFAULT 0,
  priority_explanation TEXT NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE investigation_queue IS
  'Prioridad investigativa explicable; no representa probabilidad de delito ni de LA/FT.';
