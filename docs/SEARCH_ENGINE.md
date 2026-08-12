# Motor de búsqueda — Radar Presupuesto Abierto

## Objetivo

Recuperar hechos presupuestarios con suficiente trazabilidad para pasar desde una consulta exploratoria a una hipótesis de investigación. Cada resultado conserva el snapshot/año, identificadores canónicos y atributos originales relevantes.

## Cobertura histórica

`source_discovery` audita los archivos bulk oficiales antes de consultarlos. El workflow **Search Presupuesto Abierto** acepta un año, una lista de años o un rango como `2016-2026`.

Para una búsqueda histórica amplia, cada año se procesa secuencialmente:

`download -> checksum -> normalize -> query -> append result -> delete temporary bulk`

Así es posible consultar toda la serie sin mantener simultáneamente un warehouse histórico en el runner ni requerir un servidor externo.

## Identidad

El buscador distingue:

- `beneficiario_source_id`: clave original de la fuente;
- `beneficiario_id_type`: `RUT`, `HASH_SHA1`, `SOURCE_ID` o `MISSING`;
- `recipient_id`: receptor general;
- `rut_beneficiario`: solo RUT chileno con dígito verificador válido;
- `provider_id`: solo cuando la fuente marca rol proveedor;
- identidades `HASH_SHA1`: se conservan como claves pseudónimas, nunca como RUT.

## Motor estructurado: DuckDB + Parquet

Filtros implementados:

- texto libre, tokenizado e insensible a acentos, sobre receptor, institución, área, gasto, documento, OC, BIP, sector y región;
- RUT validado e identificador original/tipo de identidad;
- `organization_id`, `recipient_id`, `provider_id`;
- partida, capítulo y área;
- año(s), mes y fecha desde/hasta;
- monto devengado mínimo/máximo y monto pagado mínimo/máximo;
- moneda;
- Orden de Compra exacta o presencia/ausencia de OC;
- BIP exacto o presencia/ausencia de BIP;
- presencia/ausencia de RUT válido;
- ubicación, región y sector;
- clasificador presupuestario `subtítulo.item.asignación`;
- número y tipo de documento;
- solo proveedores, personas u honorarios;
- intraestado, deuda flotante y registro agregado;
- días de pago mínimos/máximos.

Los filtros se parametrizan; los valores introducidos por el usuario no se interpolan directamente como SQL.

## Motor textual: SQLite FTS5

La corrida analítica crea un índice de búsqueda rápida sobre transacción, organización, receptor, proveedor, RUT, identificador de fuente, beneficiario, institución, área, clasificador, documento, OC, BIP, sector y región. La tokenización Unicode elimina diacríticos y BM25 ordena las coincidencias por relevancia.

## Workflow de consulta

En **Actions -> Search Presupuesto Abierto -> Run workflow**:

1. indicar `years`: `2026`, `2024 2025 2026` o `2016-2026`;
2. ingresar texto libre si corresponde;
3. opcionalmente pasar filtros JSON;
4. definir límite global de resultados.

Ejemplos de `filters_json`:

```json
{"provider_only": true, "min_amount": 100000000, "has_purchase_order": true}
```

```json
{"rut": "96875230-8", "date_from": "2024-01-01", "date_to": "2026-12-31"}
```

```json
{"region": "Metropolitana", "sector": "Salud", "min_payment_days": 60}
```

```json
{"partida": "08", "has_bip": true, "aggregated_only": false}
```

La corrida entrega como artifact:

- `result.csv`
- `result.json`
- `query_metadata.json`

La metadata registra años solicitados, URLs fuente, checksum SHA-256, filas normalizadas por año, parámetros exactos, brechas de cobertura y cantidad de coincidencias. Esto hace la consulta reproducible y auditable.

## Principios AML / integridad

- coincidencia de búsqueda = hecho recuperado, no señal de riesgo;
- señal estadística = priorización, no irregularidad acreditada;
- ausencia de OC ≠ anomalía automática;
- receptor ≠ proveedor;
- identidad SHA1 ≠ RUT;
- relaciones societarias/familiares y flujos privados requieren otras fuentes.
