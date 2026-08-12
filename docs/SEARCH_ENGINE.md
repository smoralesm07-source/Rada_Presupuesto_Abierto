# Motor de búsqueda — Radar Presupuesto Abierto

## Propósito

El buscador está diseñado para localizar hechos presupuestarios con trazabilidad suficiente para pasar desde una consulta exploratoria a una hipótesis de investigación. No reemplaza la fuente oficial: cada resultado conserva el año/snapshot, IDs canónicos y atributos de origen.

## Cobertura de fuentes

El `source_discovery` audita el portal oficial y prueba los archivos bulk anuales canónicos. La cobertura se registra en `docs/data/source_catalog.json`; años no confirmados se tratan como brechas, nunca como cero transacciones.

## Dos motores complementarios

### 1. DuckDB + Parquet — búsqueda estructurada y análisis masivo

Filtros disponibles:
- texto libre sobre proveedor/receptor, institución, área y descripciones presupuestarias;
- RUT normalizado;
- `organization_id` y `provider_id`;
- año y mes;
- monto devengado mínimo/máximo;
- Orden de Compra exacta;
- código BIP;
- ubicación geográfica;
- prefijo de clasificador presupuestario `subtítulo.item.asignación`.

Este es el motor preferido para rangos, agregaciones, perfiles y detección de anomalías.

### 2. SQLite FTS5 — recuperación textual rápida

Indexa:
- beneficiario/receptor;
- RUT;
- institución/servicio/área;
- subtítulo, ítem, asignación y programa presupuestario;
- número de documento;
- Orden de Compra;
- BIP;
- ubicación geográfica.

Usa tokenización Unicode y eliminación de diacríticos para mejorar la recuperación de nombres.

## Esquema bulk observado

Además de los campos previstos por el diccionario técnico, el archivo de producción 2026 contiene atributos enriquecidos como `beneficiario`, `moneda`, `monto`, `monto_original`, `devengo`, `devengo_original`, `honorario`, `proveedor`, `sector`, `region`, `persona`, `intraestado`, `deuda_flotante` y `dias_de_pago`.

El normalizador traduce variantes de nombre a un contrato estable, por ejemplo:

| Bulk | Canónico |
|---|---|
| `beneficiario` | `rut_beneficiario` |
| `moneda` | `moneda_presupuestaria` |
| `monto` | `monto_pago` |
| `monto_original` | `monto_pago_original` |
| `devengo` | `monto_devengado` |
| `devengo_original` | `monto_devengado_original` |

Los campos adicionales no reconocidos se preservan como texto en vez de ser descartados. Esto permite absorber futuras extensiones del dataset sin romper el pipeline.

## Búsqueda auditada desde GitHub

Workflow: **Search Presupuesto Abierto** (`.github/workflows/search.yml`).

Desde Actions → Search Presupuesto Abierto → Run workflow se puede consultar un año con filtros. La corrida:

1. confirma la fuente bulk oficial;
2. descarga el snapshot;
3. normaliza a Parquet;
4. ejecuta la consulta;
5. genera `result.csv`, `result.json` y `query_metadata.json`;
6. publica esos archivos como artifact temporal.

`query_metadata.json` contiene la URL fuente, año, parámetros exactos, fecha de ejecución y número de resultados. Así una búsqueda puede ser reproducida y auditada.

## Principios AML / integridad

- Una coincidencia de búsqueda es un **hecho recuperado**, no una señal de riesgo.
- Una señal estadística es una **priorización**, no una irregularidad acreditada.
- La ausencia de Orden de Compra no genera una bandera automática.
- Relaciones societarias, familiares o flujos privados no se infieren desde Presupuesto Abierto.
- En la futura integración, evidencia CGR/ChileCompra/otras fuentes se añadirá como capa separada.

## Próximas extensiones previstas

- búsqueda histórica multi-año optimizada mediante índice persistente;
- ranking BM25 combinado con filtros estructurados;
- búsqueda por similitud de proveedor/nombre para resolver variaciones nominales;
- perfiles de relación organismo–proveedor;
- comparación contra pares institucionales y presupuestarios;
- ficha de señal con transacciones soporte y consultas recomendadas.
