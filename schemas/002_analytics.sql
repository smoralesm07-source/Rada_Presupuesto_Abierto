CREATE TABLE IF NOT EXISTS risk_signals (
  signal_id TEXT PRIMARY KEY, signal_type TEXT NOT NULL, transaction_id TEXT, organization_id TEXT, provider_id TEXT,
  periodo INTEGER, mes INTEGER, observed_value NUMERIC, expected_value NUMERIC, deviation NUMERIC,
  severity TEXT, confidence TEXT, why_flagged TEXT, investigation_hypothesis TEXT, recommended_checks JSON,
  record_class TEXT NOT NULL DEFAULT 'DERIVED_SIGNAL', detected_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY, source_system TEXT NOT NULL, source_url TEXT, entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL, relationship_basis TEXT, confidence NUMERIC, is_inferred BOOLEAN NOT NULL DEFAULT FALSE, captured_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS entity_relationship_edges (
  edge_id TEXT PRIMARY KEY, source_entity_id TEXT NOT NULL, target_entity_id TEXT NOT NULL,
  relationship_basis TEXT NOT NULL, source_system TEXT NOT NULL, evidence_id TEXT, confidence NUMERIC,
  is_inferred BOOLEAN NOT NULL DEFAULT FALSE, first_seen DATE, last_seen DATE
);
