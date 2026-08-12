-- Radar Presupuesto Abierto v0.2
-- PostgreSQL-ready lineage/evidence boundary. No external relation is treated as fact without evidence.

CREATE TABLE IF NOT EXISTS source_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  source_system TEXT NOT NULL DEFAULT 'PRESUPUESTO_ABIERTO',
  source_url TEXT NOT NULL,
  source_year INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  bytes BIGINT,
  downloaded_at TIMESTAMPTZ NOT NULL,
  normalization_version TEXT,
  UNIQUE (source_url, sha256)
);

CREATE TABLE IF NOT EXISTS risk_signals (
  signal_id TEXT PRIMARY KEY,
  signal_type TEXT NOT NULL,
  transaction_id TEXT,
  organization_id TEXT,
  recipient_id TEXT,
  provider_id TEXT,
  period_year INTEGER,
  period_month INTEGER,
  observed_value NUMERIC,
  expected_value NUMERIC,
  deviation NUMERIC,
  severity TEXT,
  confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  why_flagged TEXT NOT NULL,
  investigation_hypothesis TEXT,
  recommended_checks JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  source_system TEXT NOT NULL,
  source_url TEXT,
  source_record_id TEXT,
  relationship_basis TEXT,
  confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
  payload JSONB,
  observed_at TIMESTAMPTZ,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS entity_relationship_edges (
  edge_id TEXT PRIMARY KEY,
  source_entity_type TEXT NOT NULL,
  source_entity_id TEXT NOT NULL,
  target_entity_type TEXT NOT NULL,
  target_entity_id TEXT NOT NULL,
  relationship_basis TEXT NOT NULL,
  evidence_id TEXT REFERENCES evidence(evidence_id),
  confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  is_inferred BOOLEAN NOT NULL DEFAULT TRUE,
  first_seen DATE,
  last_seen DATE
);

-- Reservado para una integración futura con Radar CGR u otras fuentes.
CREATE TABLE IF NOT EXISTS evidence_links (
  evidence_link_id TEXT PRIMARY KEY,
  local_entity_type TEXT NOT NULL,
  local_entity_id TEXT NOT NULL,
  external_system TEXT NOT NULL,
  external_entity_id TEXT NOT NULL,
  match_basis JSONB NOT NULL,
  confidence NUMERIC NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  status TEXT NOT NULL DEFAULT 'CANDIDATE',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
