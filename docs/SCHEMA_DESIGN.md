# Schema Design — Radar Presupuesto Abierto v0.1

## Cambio respecto del esquema inicial

El esquema original se conserva como arquitectura objetivo, pero se corrige para evitar mezclar hechos presupuestarios con relaciones no observadas. La regla obligatoria es:

`SOURCE_FACT -> NORMALIZED_FACT -> DERIVED_FEATURE -> RISK_SIGNAL -> EXTERNAL_EVIDENCE / INFERENCE`

Una señal no es un hallazgo de ilegalidad y una coocurrencia no es una relación societaria, familiar ni financiera.

## Soporte de la fuente

La documentación oficial de Presupuesto Abierto soporta como campos de la extracción SIGFE, entre otros: período, mes, partida, capítulo, área, subtítulo, RUT y nombre de beneficiario, número/tipo/fecha de documento, Orden de Compra, fecha de ingreso, fecha de recepción conforme, moneda, monto devengado, fecha/monto de pago, folio, ítem, asignación, código BIP, ubicación geográfica y programa presupuestario. La disponibilidad puede variar por sistema/institución/año.

Fuentes metodológicas:
- https://presupuestoabierto.gob.cl/about-data
- https://api.presupuestoabierto.gob.cl/files/Integracion_Portal_Ciudadano_2.5.pdf
- https://presupuestoabierto.gob.cl/status
- https://presupuestoabierto.gob.cl/providers

## Nivel 0 — SOURCE_SNAPSHOT

Representa el archivo exacto descargado: `snapshot_id`, `source_url`, `year`, `sha256`, `bytes`, `downloaded_at`, metadatos HTTP y licencia. No se versiona el bulk dentro de Git para evitar repositorios gigantes.

## Nivel 1 — Canonical facts

### ORGANIZATIONS
ID preferido: `ORG-PA-{PARTIDA}-{CAPITULO}-{AREA}`. No se inventa RUT institucional cuando la fuente no lo entrega. Campos: jerarquía institucional, first/last seen, cobertura transaccional/agregada y fuente.

### PROVIDERS
ID preferido: `PRV-RUT-{RUT}`; fallback determinístico por nombre solo cuando no existe RUT. Se separa identidad de métricas derivadas. No incorpora accionistas, representantes o parentescos sin evidencia externa.

### TRANSACTIONS
Conserva el máximo detalle disponible: periodo/mes, jerarquía institucional y presupuestaria, beneficiario/receptor, documento y fechas, OC, moneda, devengo/pago, folio, BIP, ubicación geográfica, programa y trazabilidad. `record_class=SOURCE_FACT`.

El `transaction_id` es hash determinístico de claves de origen y no pretende sustituir el folio SIGFE.

## Nivel 2 — Derived analytical features

Se calculan fuera del hecho fuente: monto robusto frente a pares, concentración HHI, cadencia, diversidad presupuestaria, expansión a organismos, estacionalidad, concentración geográfica y completitud documental. La ausencia de OC es descriptiva y nunca una anomalía automática.

## Nivel 3 — RISK_SIGNALS

Objeto central: `signal_id`, `signal_type`, IDs de transacción/organismo/proveedor, periodo, valor observado/esperado, desviación, severidad, confianza, explicación, hipótesis y chequeos recomendados. `record_class=DERIVED_SIGNAL`.

Señales v0.1:
1. `AMOUNT_OUTLIER`
2. `POTENTIAL_FRAGMENTATION`
3. `YEAR_END_SPIKE`
4. `EXACT_DUPLICATE_CANDIDATE`

## Nivel 4 — EVIDENCE y relaciones futuras

`EVIDENCE` registra fuente, URL, entidad, fundamento de relación, confianza e indicador de inferencia. `ENTITY_RELATIONSHIP_EDGES` solo se puebla con una base explícita: `SAME_PUBLIC_BUYER`, `SAME_PURCHASE_ORDER`, `SAME_BIP`, `SAME_BUDGET_CATEGORY`, `SAME_TEMPORAL_PATTERN` o, con fuentes futuras, representantes/direcciones/hallazgos CGR.

## Elementos retirados del núcleo v0.1

- `CASH_FLOW_TRACE` proveedor→proveedor: Presupuesto Abierto no observa transferencias privadas posteriores al pago estatal.
- `probabilidad_tbml`: no sustentable con la fuente aislada.
- `PERSON_PERSON_RELATIONSHIPS` y `PERSON_PROVIDER_RELATIONSHIPS`: requieren evidencia externa.
- atributos como político/sancionado/servidor público no se infieren desde Presupuesto Abierto.

## Integración futura con Radar CGR

Se realizará por IDs canónicos, RUT, nombre normalizado, periodo, montos, OC/BIP y `evidence_links`. Ambos radares permanecerán operativamente separados hasta medir cobertura, errores y valor analítico propio.
