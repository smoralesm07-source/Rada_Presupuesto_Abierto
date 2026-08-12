# Schema Design — Radar Presupuesto Abierto v0.1.2

## Regla de arquitectura

El esquema inicial se conserva como visión de largo plazo, pero el núcleo se ajusta a lo que Presupuesto Abierto observa realmente:

`SOURCE_SNAPSHOT -> SOURCE_FACT -> NORMALIZED_FACT -> DERIVED_FEATURE -> RISK_SIGNAL -> EXTERNAL_EVIDENCE / INFERENCE`

Una señal no es un hallazgo de ilegalidad. Una coocurrencia no es una relación societaria, familiar ni financiera. Un identificador de fuente no se transforma en RUT si no supera validación formal.

## Hallazgo de modelamiento en el bulk actual

El archivo de producción contiene `beneficiario` como **clave de identidad de fuente**. En muchos registros corresponde a un RUT chileno; en otros, especialmente personas naturales, puede ser un identificador SHA1 pseudonimizado de 40 caracteres. El bulk también incorpora banderas explícitas como `proveedor`, `persona`, `honorario`, `intraestado`, `deuda_flotante` y `agregado`.

Por ello el modelo separa **receptor/beneficiario** de **proveedor**.

## Nivel 0 — SOURCE_SNAPSHOT

Representa el archivo exacto descargado: `snapshot_id`, `source_url`, `year`, `sha256`, `bytes`, `downloaded_at`, metadatos HTTP y versión de normalización. Los bulk no se versionan en Git.

## Nivel 1 — Entidades canónicas

### ORGANIZATIONS

`organization_id = ORG-PA-{PARTIDA}-{CAPITULO}-{AREA}` cuando existe jerarquía presupuestaria. No se inventa RUT institucional.

### RECIPIENTS

Es la entidad general que recibe/devenga/paga gasto en la fuente. Campos principales:

- `recipient_id`
- `beneficiario_source_id`
- `beneficiario_id_type`: `RUT`, `HASH_SHA1`, `SOURCE_ID` o `MISSING`
- `rut`: solo si formato y dígito verificador son válidos
- nombre y nombre normalizado
- banderas de fuente: persona, proveedor, honorario, intraestado, deuda flotante, agregado
- first/last seen

IDs:
- `RCV-RUT-{RUT}` para RUT válido;
- `RCV-SHA1-{HASH}` para identidad pseudónima publicada por la fuente;
- fallback determinístico para otras claves.

### PROVIDERS

Proveedor es un **rol/subconjunto de receptor**, no sinónimo de beneficiario. Solo se crea `provider_id` cuando el bulk marca `proveedor=1`.

IDs:
- `PRV-RUT-{RUT}` si el proveedor tiene RUT válido;
- `PRV-SHA1-{HASH}` cuando la propia fuente identifica pseudónimamente a un receptor que además tiene rol proveedor;
- fallback determinístico si existe otra clave de fuente.

Esto evita convertir remuneraciones, honorarios u otros receptores en empresas proveedoras.

### TRANSACTIONS

Conserva el máximo detalle disponible: periodo/mes, jerarquía institucional y presupuestaria, `recipient_id`, `provider_id` nullable, clave de beneficiario original, RUT validado, nombre, documentos y fechas, OC, moneda, monto original, pago/devengo normalizado, folio, BIP, ubicación, programa, sector, región, días de pago y banderas de fuente.

`transaction_id` es un hash determinístico de claves de origen; no pretende sustituir folios SIGFE.

## Nivel 2 — Variables derivadas

Se calculan fuera del hecho fuente: monto robusto frente a pares, concentración HHI, cadencia, diversidad presupuestaria, expansión institucional, estacionalidad, concentración geográfica y completitud documental.

Existen perfiles separados:
- `recipient_profiles`
- `provider_profiles`
- `organization_profiles`

La ausencia de OC es descriptiva y nunca una anomalía automática.

## Nivel 3 — RISK_SIGNALS

Objeto central:

`signal_id, signal_type, transaction_id, organization_id, recipient_id, provider_id, periodo, observed_value, expected_value, deviation, severity, confidence, why_flagged, investigation_hypothesis, recommended_checks`

Señales v0.1:
1. `AMOUNT_OUTLIER`: solo cola alta respecto del grupo comparable.
2. `POTENTIAL_FRAGMENTATION`: solo receptores marcados como proveedor.
3. `YEAR_END_SPIKE`: estacionalidad institucional, sujeto a comparación histórica.
4. `EXACT_DUPLICATE_CANDIDATE`: candidato documental, no duplicidad acreditada.

## Nivel 4 — EVIDENCE y relaciones futuras

`EVIDENCE` registra fuente, URL, entidad, fundamento de relación, confianza e indicador de inferencia. `ENTITY_RELATIONSHIP_EDGES` solo se puebla con una base explícita como `SAME_PUBLIC_BUYER`, `SAME_PURCHASE_ORDER`, `SAME_BIP`, `SAME_BUDGET_CATEGORY`, `SAME_TEMPORAL_PATTERN` o evidencia futura de otras fuentes.

## Elementos fuera del núcleo Presupuesto Abierto

- `CASH_FLOW_TRACE` proveedor→proveedor.
- probabilidad TBML derivada solo del gasto estatal.
- relaciones familiares/societarias sin fuente externa.
- PEP, sancionado o servidor público inferidos desde nombres.

## Preparación para Radar CGR

La integración futura utilizará IDs canónicos, RUT validado, nombre normalizado, período, montos, OC/BIP y `evidence_links`. Los pipelines permanecen independientes durante la fase de evaluación específica.
