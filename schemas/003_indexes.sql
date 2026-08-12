CREATE INDEX IF NOT EXISTS idx_transactions_org_period ON transactions(organization_id, periodo, mes);
CREATE INDEX IF NOT EXISTS idx_transactions_provider_period ON transactions(provider_id, periodo, mes);
CREATE INDEX IF NOT EXISTS idx_transactions_risk_keys ON transactions(orden_compra, codigo_bip, numero_documento);
CREATE INDEX IF NOT EXISTS idx_signals_entity ON risk_signals(organization_id, provider_id, signal_type, severity);
