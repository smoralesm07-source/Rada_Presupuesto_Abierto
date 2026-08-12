CREATE TABLE IF NOT EXISTS organizations (
  organization_id TEXT PRIMARY KEY,
  partida TEXT, nombre_partida TEXT, capitulo TEXT, nombre_capitulo TEXT,
  area TEXT, nombre_area TEXT, first_seen DATE, last_seen DATE,
  data_coverage_type TEXT, source_system TEXT NOT NULL DEFAULT 'PRESUPUESTO_ABIERTO'
);
CREATE TABLE IF NOT EXISTS providers (
  provider_id TEXT PRIMARY KEY, rut TEXT, nombre TEXT, nombre_normalizado TEXT,
  first_seen DATE, last_seen DATE, source_system TEXT NOT NULL DEFAULT 'PRESUPUESTO_ABIERTO'
);
CREATE TABLE IF NOT EXISTS transactions (
  transaction_id TEXT PRIMARY KEY, periodo INTEGER, mes INTEGER,
  organization_id TEXT REFERENCES organizations(organization_id), provider_id TEXT REFERENCES providers(provider_id),
  subtitulo TEXT, nombre_subtitulo TEXT, item TEXT, nombre_item TEXT, asignacion TEXT, nombre_asignacion TEXT,
  numero_documento TEXT, fecha_documento DATE, tipo_documento TEXT, orden_compra TEXT,
  fecha_ingreso DATE, fecha_recepcion_conforme DATE, moneda_presupuestaria TEXT, monto_devengado NUMERIC,
  fecha_pago DATE, monto_pago NUMERIC, folio TEXT, codigo_bip TEXT, nombre_bip TEXT,
  codigo_ubicacion_geografica TEXT, nombre_ubicacion_geografica TEXT,
  codigo_programa_presupuestario TEXT, nombre_programa_presupuestario TEXT,
  record_class TEXT NOT NULL DEFAULT 'SOURCE_FACT', source_url TEXT, source_file TEXT
);
