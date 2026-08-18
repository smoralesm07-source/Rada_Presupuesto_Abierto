from __future__ import annotations

"""Vista de ejecución y pagos del Estado a terceros.

Este módulo construye un único artefacto compacto (``spend_view_v1.json``)
que alimenta el módulo web ``docs/ejecucion.html``: ritmo de ejecución,
concentración territorial, concentración por comprador, proveedores atípicos,
proveedores nuevos con adjudicación material y patrones de calendario y
documentación.

Tres reglas gobiernan el diseño:

1. **Gasto no es riesgo.** El volumen de pagos mide exposición y tamaño del
   Estado en un territorio, no irregularidad. La atipicidad se construye
   siempre como desviación respecto de pares comparables.
2. **Ausencia no es cero.** Región no informada, orden de compra ausente o
   días de pago nulos se reportan como cobertura faltante, nunca como valor 0.
3. **Todo puntaje es explicable.** El score de proveedor es una suma de
   contribuciones nombradas, con su peso y su métrica de respaldo, para que
   un analista pueda descartarlo con un documento.

La fuente (pagos de Presupuesto Abierto) no publica el presupuesto vigente por
organismo, de modo que aquí *ejecución* significa flujo observado
(devengado/pagado) y su ritmo intra-anual, no porcentaje de avance sobre la
Ley de Presupuestos.
"""

import argparse
import glob
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from .regions import region_meta, region_reference

SCHEMA = "PRESUPUESTO_SPEND_VIEW_V1"
DEFAULT_OUTPUT = "docs/data/spend_view_v1.json"
DEFAULT_CONFIG = "config/spend_view.yaml"

DEFAULTS: dict[str, dict[str, Any]] = {
    "materiality": {
        "provider_min_amount_clp": 20_000_000,
        "provider_min_transactions": 2,
        "round_amount_multiple_clp": 1_000_000,
    },
    "concentration": {
        "buyer_share_watch": 0.45,
        "buyer_share_alert": 0.65,
        "client_dependency_share": 0.95,
    },
    "new_entrants": {"cohort_quantile": 0.95, "min_amount_clp": 50_000_000},
    "calendar": {"december_share_watch": 0.40, "december_share_alert": 0.60},
    "documentation": {"missing_purchase_order_share": 0.80},
    "payment_speed": {"fast_payment_days": 2, "national_median_floor_days": 15},
    "output": {
        "top_regions": 20,
        "top_budget_lines": 14,
        "top_organizations": 30,
        "top_providers": 60,
        "top_anomalous_providers": 60,
        "top_new_providers": 40,
    },
}


def load_view_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, dict[str, Any]]:
    """Combina los umbrales por defecto con el YAML del repositorio."""
    merged = {section: dict(values) for section, values in DEFAULTS.items()}
    p = Path(path)
    if not p.exists():
        return merged
    try:
        import yaml

        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # configuración inválida no debe romper la corrida
        return merged
    for section, values in (raw or {}).items():
        if isinstance(values, dict):
            merged.setdefault(section, {}).update(values)
    return merged


def _cols(con: duckdb.DuckDBPyConnection, view: str) -> set[str]:
    return {str(row[0]) for row in con.execute(f"DESCRIBE {view}").fetchall()}


def _rows(con: duckdb.DuckDBPyConnection, query: str) -> list[dict[str, Any]]:
    cur = con.execute(query)
    names = [x[0] for x in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _one(con: duckdb.DuckDBPyConnection, query: str) -> dict[str, Any]:
    rows = _rows(con, query)
    return rows[0] if rows else {}


def _num(value: Any) -> float | None:
    """Convierte a float sólo si el valor es finito; NaN/Inf se pierden en JSON."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _round(value: Any, digits: int = 4) -> float | None:
    out = _num(value)
    return None if out is None else round(out, digits)


def _share(part: Any, total: Any, digits: int = 6) -> float | None:
    """Participación con denominador explícito: sin total no hay share."""
    numerator, denominator = _num(part), _num(total)
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, digits)


def _text_expr(cols: set[str], name: str, fallback: str = "NULL") -> str:
    return f"nullif(trim(cast({name} as varchar)),'')" if name in cols else fallback


def _double_expr(cols: set[str], name: str, fallback: str = "NULL") -> str:
    return f"try_cast({name} AS DOUBLE)" if name in cols else fallback


def _int_expr(cols: set[str], name: str, fallback: str = "NULL") -> str:
    return f"try_cast({name} AS BIGINT)" if name in cols else fallback


def _bool_expr(cols: set[str], name: str, fallback: str = "FALSE") -> str:
    return f"coalesce(try_cast({name} AS BOOLEAN),FALSE)" if name in cols else fallback


def _prepare_transactions(con: duckdb.DuckDBPyConnection, parquet_glob: str) -> dict[str, Any]:
    """Crea la vista ``tx`` con las columnas analíticas ya tipadas.

    La fuente cambia de columnas entre años, así que cada expresión se resuelve
    contra el esquema real: lo ausente queda NULL y se reporta como brecha de
    cobertura, no como cero.
    """
    con.execute(
        f"CREATE OR REPLACE VIEW facts AS "
        f"SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)"
    )
    cols = _cols(con, "facts")

    region_source = _text_expr(cols, "region")
    geo_code = _text_expr(cols, "codigo_ubicacion_geografica")
    if region_source == "NULL" and geo_code == "NULL":
        raw_region = "NULL"
    elif region_source == "NULL":
        raw_region = f"nullif(left({geo_code},2),'')"
    elif geo_code == "NULL":
        raw_region = region_source
    else:
        raw_region = f"coalesce({region_source}, nullif(left({geo_code},2),''))"

    provider_flag = _bool_expr(cols, "is_provider")
    provider_id = _text_expr(cols, "provider_id")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW tx AS
        SELECT {_text_expr(cols, 'transaction_id')} AS transaction_id,
               {_text_expr(cols, 'organization_id')} AS organization_id,
               {provider_id} AS provider_id,
               {_text_expr(cols, 'recipient_id')} AS recipient_id,
               {_text_expr(cols, 'entity_id')} AS entity_id,
               {_text_expr(cols, 'rut_beneficiario')} AS rut,
               {_text_expr(cols, 'nombre_beneficiario')} AS beneficiary_name,
               {_int_expr(cols, 'periodo')} AS periodo,
               {_int_expr(cols, 'mes')} AS mes,
               {_double_expr(cols, 'monto_devengado')} AS devengado,
               {_double_expr(cols, 'monto_pago')} AS pagado,
               {_double_expr(cols, 'dias_de_pago')} AS dias_pago,
               {_text_expr(cols, 'orden_compra')} AS orden_compra,
               {_text_expr(cols, 'codigo_bip')} AS codigo_bip,
               {_text_expr(cols, 'subtitulo')} AS subtitulo,
               {_text_expr(cols, 'nombre_subtitulo')} AS nombre_subtitulo,
               {_text_expr(cols, 'nombre_partida')} AS nombre_partida,
               {_text_expr(cols, 'nombre_capitulo')} AS nombre_capitulo,
               {_text_expr(cols, 'nombre_area')} AS nombre_area,
               {_text_expr(cols, 'sector')} AS sector,
               {provider_flag} AS is_provider,
               {_bool_expr(cols, 'is_person')} AS is_person,
               {_bool_expr(cols, 'is_honorarium')} AS is_honorarium,
               {_bool_expr(cols, 'is_intra_state')} AS is_intra_state,
               {_bool_expr(cols, 'is_floating_debt')} AS is_floating_debt,
               {_bool_expr(cols, 'is_aggregated')} AS is_aggregated,
               {raw_region} AS raw_region
        FROM facts
        """
    )

    raw_values = [row[0] for row in con.execute("SELECT DISTINCT raw_region FROM tx").fetchall()]
    mapping = []
    for raw in raw_values:
        meta = region_meta(raw)
        mapping.append(
            {
                "raw_region": raw,
                "region_code": meta["region_code"],
                "region_name": meta["region_name"],
                "region_abbr": meta["region_abbr"],
                "macrozone": meta["macrozone"],
                "geo_order": meta["geo_order"],
            }
        )
    con.execute(
        "CREATE OR REPLACE TABLE region_map(raw_region VARCHAR, region_code VARCHAR, "
        "region_name VARCHAR, region_abbr VARCHAR, macrozone VARCHAR, geo_order BIGINT)"
    )
    if mapping:
        con.executemany(
            "INSERT INTO region_map VALUES (?,?,?,?,?,?)",
            [
                (
                    m["raw_region"],
                    m["region_code"],
                    m["region_name"],
                    m["region_abbr"],
                    m["macrozone"],
                    int(m["geo_order"]),
                )
                for m in mapping
            ],
        )

    con.execute(
        """
        CREATE OR REPLACE VIEW txr AS
        SELECT t.*,
               coalesce(m.region_code,'UNKNOWN') AS region_code,
               coalesce(m.region_name,'Sin región informada') AS region_name,
               coalesce(m.region_abbr,'SR') AS region_abbr,
               coalesce(m.macrozone,'UNKNOWN') AS macrozone,
               coalesce(m.geo_order,99) AS geo_order,
               (t.is_provider AND coalesce(t.provider_id,'')<>'' AND NOT t.is_aggregated) AS is_provider_payment
        FROM tx t
        LEFT JOIN region_map m ON t.raw_region IS NOT DISTINCT FROM m.raw_region
        """
    )
    return {"fact_columns": sorted(cols), "distinct_raw_regions": len(raw_values)}


def _prepare_providers(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> None:
    """Perfil por proveedor: monto, dispersión de compradores y comportamiento."""
    multiple = float(cfg["materiality"]["round_amount_multiple_clp"])
    fast_days = float(cfg["payment_speed"]["fast_payment_days"])
    con.execute(
        f"""
        CREATE OR REPLACE TABLE prov AS
        SELECT provider_id,
               any_value(beneficiary_name) AS provider_name,
               any_value(rut) AS rut,
               any_value(entity_id) AS entity_id,
               bool_or(is_person) AS is_person,
               bool_or(is_honorarium) AS is_honorarium,
               count(*)::BIGINT AS transactions,
               coalesce(sum(devengado),0)::DOUBLE AS amount,
               coalesce(sum(pagado),0)::DOUBLE AS paid,
               count(DISTINCT organization_id)::BIGINT AS organizations,
               count(DISTINCT region_code) FILTER (WHERE region_code<>'UNKNOWN')::BIGINT AS regions,
               min(periodo)::BIGINT AS first_year,
               max(periodo)::BIGINT AS last_year,
               count(DISTINCT periodo)::BIGINT AS years_active,
               count(DISTINCT (periodo*100+coalesce(mes,0)))::BIGINT AS months_active,
               min(periodo*100+coalesce(mes,0))::BIGINT AS first_period,
               coalesce(sum(devengado) FILTER (WHERE mes=12),0)::DOUBLE AS december_amount,
               count(*) FILTER (WHERE orden_compra IS NULL)::BIGINT AS tx_without_oc,
               count(*) FILTER (WHERE devengado IS NOT NULL AND devengado>=({multiple})
                                  AND devengado % ({multiple}) = 0)::BIGINT AS tx_round_amount,
               median(dias_pago) AS days_to_pay_median,
               count(*) FILTER (WHERE dias_pago IS NOT NULL AND dias_pago<={fast_days})::BIGINT AS tx_fast_paid,
               count(*) FILTER (WHERE dias_pago IS NOT NULL)::BIGINT AS tx_with_days,
               count(*) FILTER (WHERE is_floating_debt)::BIGINT AS tx_floating_debt,
               max(devengado) AS max_transaction_amount,
               any_value(region_code) AS main_region_code
        FROM txr
        WHERE is_provider_payment
        GROUP BY 1
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE prov_org AS
        SELECT provider_id, organization_id,
               any_value(coalesce(nombre_area,nombre_capitulo,nombre_partida)) AS organization_name,
               coalesce(sum(devengado),0)::DOUBLE AS amount,
               count(*)::BIGINT AS transactions
        FROM txr
        WHERE is_provider_payment
        GROUP BY 1,2
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE org_provider_total AS
        SELECT organization_id, sum(amount)::DOUBLE AS provider_amount,
               count(*)::BIGINT AS providers
        FROM prov_org GROUP BY 1
        """
    )
    # Dos concentraciones distintas y complementarias: cuánto depende el
    # proveedor de un comprador, y cuánto depende el comprador del proveedor.
    con.execute(
        """
        CREATE OR REPLACE TABLE prov_concentration AS
        WITH ranked AS (
          SELECT po.provider_id, po.organization_id, po.organization_name, po.amount,
                 t.provider_amount AS org_provider_amount, t.providers AS org_providers,
                 sum(po.amount) OVER (PARTITION BY po.provider_id) AS provider_amount,
                 CASE WHEN t.provider_amount>0 THEN po.amount/t.provider_amount END AS share_of_buyer
          FROM prov_org po
          LEFT JOIN org_provider_total t USING(organization_id)
        )
        SELECT provider_id,
               arg_max(organization_id, amount) AS top_client_id,
               arg_max(organization_name, amount) AS top_client_name,
               max(CASE WHEN provider_amount>0 THEN amount/provider_amount END) AS top_client_share,
               max(share_of_buyer) AS max_share_of_buyer,
               arg_max(organization_name, coalesce(share_of_buyer,0)) AS max_share_of_buyer_name,
               arg_max(org_providers, coalesce(share_of_buyer,0)) AS max_share_of_buyer_providers,
               sum(power(CASE WHEN provider_amount>0 THEN amount/provider_amount ELSE 0 END,2)) AS client_hhi
        FROM ranked
        GROUP BY 1
        """
    )


def _prepare_signals(con: duckdb.DuckDBPyConnection, prioritized_path: str) -> bool:
    """Adjunta la cola priorizada existente sin recalcular señales.

    El módulo no crea señales nuevas: reutiliza ``prioritized_signals.parquet``
    para que la vista de gasto y la cola de investigación no puedan divergir.
    """
    available = Path(prioritized_path).exists()
    if available:
        con.execute(
            f"CREATE OR REPLACE VIEW priority AS "
            f"SELECT * FROM read_parquet('{prioritized_path}', union_by_name=true)"
        )
        pcols = _cols(con, "priority")
        con.execute(
            f"""
            CREATE OR REPLACE VIEW sig AS
            SELECT {_text_expr(pcols, 'signal_id')} AS signal_id,
                   {_text_expr(pcols, 'signal_type')} AS signal_type,
                   {_text_expr(pcols, 'transaction_id')} AS transaction_id,
                   {_text_expr(pcols, 'organization_id')} AS organization_id,
                   {_text_expr(pcols, 'provider_id')} AS provider_id,
                   {_text_expr(pcols, 'priority_tier')} AS priority_tier,
                   upper(coalesce({_text_expr(pcols, 'severity')},'')) AS severity,
                   {_double_expr(pcols, 'investigation_priority_score')} AS priority_score,
                   coalesce({_int_expr(pcols, 'cgr_match_count')},0) AS cgr_match_count,
                   {_int_expr(pcols, 'periodo')} AS periodo
            FROM priority
            """
        )
    else:
        con.execute(
            "CREATE OR REPLACE VIEW sig AS SELECT NULL::VARCHAR signal_id, NULL::VARCHAR signal_type, "
            "NULL::VARCHAR transaction_id, NULL::VARCHAR organization_id, NULL::VARCHAR provider_id, "
            "NULL::VARCHAR priority_tier, ''::VARCHAR severity, NULL::DOUBLE priority_score, "
            "0::BIGINT cgr_match_count, NULL::BIGINT periodo WHERE FALSE"
        )

    con.execute(
        """
        CREATE OR REPLACE TABLE prov_signals AS
        SELECT provider_id,
               count(*)::BIGINT AS signals,
               count(*) FILTER (WHERE priority_tier='P1')::BIGINT AS p1_signals,
               count(*) FILTER (WHERE severity='HIGH')::BIGINT AS high_signals,
               max(priority_score) AS max_priority_score,
               max(cgr_match_count)::BIGINT AS cgr_match_count,
               list(DISTINCT signal_type) AS signal_types
        FROM sig WHERE coalesce(provider_id,'')<>''
        GROUP BY 1
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE org_signals AS
        SELECT organization_id,
               count(*)::BIGINT AS signals,
               count(*) FILTER (WHERE priority_tier='P1')::BIGINT AS p1_signals,
               count(*) FILTER (WHERE signal_type='POTENTIAL_FRAGMENTATION')::BIGINT AS fragmentation_signals,
               count(*) FILTER (WHERE signal_type='EXACT_DUPLICATE_CANDIDATE')::BIGINT AS duplicate_signals,
               count(*) FILTER (WHERE signal_type='PROVIDER_CONCENTRATION')::BIGINT AS concentration_signals,
               count(*) FILTER (WHERE signal_type='YEAR_END_SPIKE')::BIGINT AS year_end_signals,
               count(*) FILTER (WHERE cgr_match_count>0)::BIGINT AS cgr_linked_signals,
               max(priority_score) AS max_priority_score
        FROM sig WHERE coalesce(organization_id,'')<>''
        GROUP BY 1
        """
    )
    return available


def _national_totals(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> dict[str, Any]:
    multiple = float(cfg["materiality"]["round_amount_multiple_clp"])
    fast_days = float(cfg["payment_speed"]["fast_payment_days"])
    row = _one(
        con,
        f"""
        SELECT count(*)::BIGINT AS transactions,
               coalesce(sum(devengado),0)::DOUBLE AS devengado,
               coalesce(sum(pagado),0)::DOUBLE AS pagado,
               count(DISTINCT organization_id)::BIGINT AS organizations,
               count(DISTINCT recipient_id)::BIGINT AS recipients,
               count(DISTINCT provider_id) FILTER (WHERE is_provider_payment)::BIGINT AS providers,
               min(periodo)::BIGINT AS first_year,
               max(periodo)::BIGINT AS last_year,
               count(DISTINCT periodo)::BIGINT AS years,
               coalesce(sum(devengado) FILTER (WHERE is_provider_payment),0)::DOUBLE AS provider_devengado,
               count(*) FILTER (WHERE is_provider_payment)::BIGINT AS provider_transactions,
               coalesce(sum(devengado) FILTER (WHERE is_person),0)::DOUBLE AS person_devengado,
               coalesce(sum(devengado) FILTER (WHERE is_honorarium),0)::DOUBLE AS honorarium_devengado,
               coalesce(sum(devengado) FILTER (WHERE is_intra_state),0)::DOUBLE AS intra_state_devengado,
               coalesce(sum(devengado) FILTER (WHERE is_floating_debt),0)::DOUBLE AS floating_debt_devengado,
               coalesce(sum(devengado) FILTER (WHERE mes=12),0)::DOUBLE AS december_devengado,
               coalesce(sum(devengado) FILTER (WHERE region_code<>'UNKNOWN'),0)::DOUBLE AS region_known_devengado,
               count(*) FILTER (WHERE orden_compra IS NOT NULL)::BIGINT AS tx_with_oc,
               count(*) FILTER (WHERE is_provider_payment AND orden_compra IS NULL)::BIGINT AS provider_tx_without_oc,
               count(*) FILTER (WHERE is_provider_payment AND devengado>=({multiple})
                                  AND devengado % ({multiple}) = 0)::BIGINT AS provider_tx_round,
               count(*) FILTER (WHERE dias_pago IS NOT NULL)::BIGINT AS tx_with_days,
               median(dias_pago) AS days_to_pay_median,
               count(*) FILTER (WHERE dias_pago IS NOT NULL AND dias_pago<={fast_days})::BIGINT AS tx_fast_paid,
               count(*) FILTER (WHERE dias_pago>=120)::BIGINT AS tx_slow_paid
        FROM txr
        """
    )
    return row


def _execution_blocks(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Ritmo de ejecución: serie mensual, cierre de año y curva acumulada."""
    monthly = _rows(
        con,
        """
        SELECT periodo, mes,
               count(*)::BIGINT AS transactions,
               coalesce(sum(devengado),0)::DOUBLE AS devengado,
               coalesce(sum(pagado),0)::DOUBLE AS pagado,
               coalesce(sum(devengado) FILTER (WHERE is_provider_payment),0)::DOUBLE AS provider_devengado,
               count(DISTINCT provider_id) FILTER (WHERE is_provider_payment)::BIGINT AS providers,
               median(dias_pago) AS days_to_pay_median
        FROM txr
        WHERE periodo IS NOT NULL AND mes BETWEEN 1 AND 12
        GROUP BY 1,2
        ORDER BY 1,2
        """
    )
    by_year_totals: dict[int, float] = {}
    for row in monthly:
        year = int(row["periodo"])
        by_year_totals[year] = by_year_totals.get(year, 0.0) + (_num(row["devengado"]) or 0.0)
    cumulative: dict[int, float] = {}
    for row in monthly:
        year = int(row["periodo"])
        cumulative[year] = cumulative.get(year, 0.0) + (_num(row["devengado"]) or 0.0)
        row["month_label"] = f"{year}-{int(row['mes']):02d}"
        row["share_of_year"] = _share(row["devengado"], by_year_totals.get(year))
        row["cumulative_devengado"] = round(cumulative[year], 2)
        row["cumulative_share_of_year"] = _share(cumulative[year], by_year_totals.get(year))
        row["days_to_pay_median"] = _round(row["days_to_pay_median"], 2)

    by_year = _rows(
        con,
        """
        SELECT periodo,
               count(*)::BIGINT AS transactions,
               coalesce(sum(devengado),0)::DOUBLE AS devengado,
               coalesce(sum(pagado),0)::DOUBLE AS pagado,
               count(DISTINCT organization_id)::BIGINT AS organizations,
               count(DISTINCT provider_id) FILTER (WHERE is_provider_payment)::BIGINT AS providers,
               coalesce(sum(devengado) FILTER (WHERE mes=12),0)::DOUBLE AS december_devengado,
               coalesce(sum(devengado) FILTER (WHERE mes>=10),0)::DOUBLE AS q4_devengado,
               coalesce(sum(devengado) FILTER (WHERE is_provider_payment),0)::DOUBLE AS provider_devengado,
               median(dias_pago) AS days_to_pay_median
        FROM txr WHERE periodo IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """
    )
    for row in by_year:
        row["december_share"] = _share(row["december_devengado"], row["devengado"])
        row["q4_share"] = _share(row["q4_devengado"], row["devengado"])
        row["payment_ratio"] = _share(row["pagado"], row["devengado"])
        row["days_to_pay_median"] = _round(row["days_to_pay_median"], 2)
        row["expected_uniform_december_share"] = 1 / 12
    return {"monthly": monthly, "by_year": by_year}


def _gini(values: list[float]) -> float | None:
    """Gini sobre montos regionales: 0 = reparto plano, 1 = todo en una región."""
    clean = sorted(v for v in (_num(x) or 0.0 for x in values) if v > 0)
    n = len(clean)
    total = sum(clean)
    if n < 2 or total <= 0:
        return None
    weighted = sum((i + 1) * v for i, v in enumerate(clean))
    return round((2 * weighted) / (n * total) - (n + 1) / n, 6)


def _lorenz(values: list[float]) -> list[dict[str, float]]:
    clean = sorted(v for v in (_num(x) or 0.0 for x in values) if v > 0)
    total = sum(clean)
    if not clean or total <= 0:
        return []
    curve = [{"population_share": 0.0, "amount_share": 0.0}]
    running = 0.0
    for index, value in enumerate(clean, start=1):
        running += value
        curve.append(
            {
                "population_share": round(index / len(clean), 6),
                "amount_share": round(running / total, 6),
            }
        )
    return curve


def _regional_blocks(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> dict[str, Any]:
    """Concentración territorial del gasto y de la atipicidad."""
    rows = _rows(
        con,
        """
        WITH base AS (
          SELECT region_code, region_name, region_abbr, macrozone, geo_order,
                 count(*)::BIGINT AS transactions,
                 coalesce(sum(devengado),0)::DOUBLE AS devengado,
                 coalesce(sum(pagado),0)::DOUBLE AS pagado,
                 coalesce(sum(devengado) FILTER (WHERE is_provider_payment),0)::DOUBLE AS provider_devengado,
                 count(DISTINCT organization_id)::BIGINT AS organizations,
                 count(DISTINCT provider_id) FILTER (WHERE is_provider_payment)::BIGINT AS providers,
                 count(DISTINCT recipient_id)::BIGINT AS recipients,
                 coalesce(sum(devengado) FILTER (WHERE mes=12),0)::DOUBLE AS december_devengado,
                 count(*) FILTER (WHERE is_provider_payment AND orden_compra IS NULL)::BIGINT AS provider_tx_without_oc,
                 count(*) FILTER (WHERE is_provider_payment)::BIGINT AS provider_transactions,
                 median(dias_pago) AS days_to_pay_median
          FROM txr GROUP BY 1,2,3,4,5
        )
        SELECT * FROM base ORDER BY geo_order
        """
    )
    # La concentración intrarregional se calcula aparte para no arrastrar el
    # detalle proveedor×región a la consulta principal.
    conc = {
        str(r["region_code"]): r
        for r in _rows(
            con,
            """
            WITH prov_region AS (
              SELECT region_code, provider_id, any_value(beneficiary_name) AS provider_name,
                     sum(devengado) AS amount
              FROM txr WHERE is_provider_payment GROUP BY 1,2
            ), totals AS (
              SELECT region_code, sum(amount) AS total FROM prov_region GROUP BY 1
            )
            SELECT p.region_code,
                   sum(power(p.amount/nullif(t.total,0),2)) AS provider_hhi,
                   arg_max(p.provider_name, p.amount) AS top_provider_name,
                   arg_max(p.provider_id, p.amount) AS top_provider_id,
                   max(p.amount)/nullif(t.total,0) AS top_provider_share,
                   count(*)::BIGINT AS providers_with_spend
            FROM prov_region p JOIN totals t USING(region_code)
            GROUP BY p.region_code, t.total
            """,
        )
    }
    signals_by_region = {
        str(r["region_code"]): r
        for r in _rows(
            con,
            """
            SELECT t.region_code,
                   count(*)::BIGINT AS signals,
                   count(*) FILTER (WHERE s.priority_tier='P1')::BIGINT AS p1_signals,
                   count(*) FILTER (WHERE s.severity='HIGH')::BIGINT AS high_signals,
                   count(*) FILTER (WHERE s.cgr_match_count>0)::BIGINT AS cgr_linked_signals
            FROM sig s JOIN (SELECT transaction_id, any_value(region_code) AS region_code FROM txr GROUP BY 1) t
              ON s.transaction_id=t.transaction_id
            GROUP BY 1
            """,
        )
    }

    total_devengado = sum((_num(r["devengado"]) or 0.0) for r in rows)
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["region_code"])
        c = conc.get(code, {})
        s = signals_by_region.get(code, {})
        row["share_of_national"] = _share(row["devengado"], total_devengado)
        row["amount_per_transaction"] = _round(
            (_num(row["devengado"]) or 0.0) / row["transactions"], 2
        ) if row["transactions"] else None
        row["provider_hhi"] = _round(c.get("provider_hhi"), 6)
        row["top_provider_name"] = c.get("top_provider_name")
        row["top_provider_id"] = c.get("top_provider_id")
        row["top_provider_share"] = _round(c.get("top_provider_share"), 6)
        row["december_share"] = _share(row["december_devengado"], row["devengado"])
        row["missing_oc_share"] = _share(row["provider_tx_without_oc"], row["provider_transactions"])
        row["days_to_pay_median"] = _round(row["days_to_pay_median"], 2)
        row["signals"] = int(s.get("signals") or 0)
        row["p1_signals"] = int(s.get("p1_signals") or 0)
        row["high_signals"] = int(s.get("high_signals") or 0)
        row["cgr_linked_signals"] = int(s.get("cgr_linked_signals") or 0)
        row["p1_per_100k_transactions"] = _round(
            100000.0 * row["p1_signals"] / row["transactions"], 4
        ) if row["transactions"] else None
        row["signals_per_100k_transactions"] = _round(
            100000.0 * row["signals"] / row["transactions"], 4
        ) if row["transactions"] else None
        out_rows.append(row)

    known = [r for r in out_rows if r["region_code"] != "UNKNOWN"]
    amounts = [(_num(r["devengado"]) or 0.0) for r in known]
    ranked = sorted(known, key=lambda r: -(_num(r["devengado"]) or 0.0))
    unknown = next((r for r in out_rows if r["region_code"] == "UNKNOWN"), None)
    concentration = {
        "gini": _gini(amounts),
        "hhi": _round(sum((a / sum(amounts)) ** 2 for a in amounts if sum(amounts) > 0), 6)
        if sum(amounts) > 0
        else None,
        "top1_share": _share(ranked[0]["devengado"], sum(amounts)) if ranked else None,
        "top1_region": ranked[0]["region_name"] if ranked else None,
        "top3_share": _share(sum((_num(r["devengado"]) or 0.0) for r in ranked[:3]), sum(amounts))
        if ranked
        else None,
        "regions_with_spend": len([a for a in amounts if a > 0]),
        "unassigned_share": _share(unknown["devengado"] if unknown else 0, total_devengado),
        "lorenz": _lorenz(amounts),
    }
    macro = _rows(
        con,
        """
        SELECT macrozone,
               coalesce(sum(devengado),0)::DOUBLE AS devengado,
               count(*)::BIGINT AS transactions,
               count(DISTINCT provider_id) FILTER (WHERE is_provider_payment)::BIGINT AS providers
        FROM txr GROUP BY 1 ORDER BY 2 DESC
        """
    )
    for row in macro:
        row["share_of_national"] = _share(row["devengado"], total_devengado)
    top_n = int(cfg["output"]["top_regions"])
    return {
        "regions": out_rows[:top_n] if len(out_rows) > top_n else out_rows,
        "macrozones": macro,
        "concentration": concentration,
    }


def _budget_lines(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], total: float) -> list[dict[str, Any]]:
    """Concentración por clasificador presupuestario (subtítulo)."""
    rows = _rows(
        con,
        f"""
        SELECT coalesce(subtitulo,'—') AS subtitulo,
               coalesce(any_value(nombre_subtitulo),'Sin clasificador informado') AS name,
               count(*)::BIGINT AS transactions,
               coalesce(sum(devengado),0)::DOUBLE AS devengado,
               count(DISTINCT provider_id) FILTER (WHERE is_provider_payment)::BIGINT AS providers,
               count(DISTINCT organization_id)::BIGINT AS organizations,
               coalesce(sum(devengado) FILTER (WHERE is_provider_payment),0)::DOUBLE AS provider_devengado,
               coalesce(sum(devengado) FILTER (WHERE mes=12),0)::DOUBLE AS december_devengado
        FROM txr GROUP BY 1
        ORDER BY devengado DESC
        LIMIT {int(cfg['output']['top_budget_lines'])}
        """
    )
    for row in rows:
        row["share_of_national"] = _share(row["devengado"], total)
        row["december_share"] = _share(row["december_devengado"], row["devengado"])
        row["provider_share"] = _share(row["provider_devengado"], row["devengado"])
    return rows


def _organizations(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], total: float) -> list[dict[str, Any]]:
    """Organismos compradores: tamaño, dependencia de proveedor y señales."""
    rows = _rows(
        con,
        f"""
        WITH base AS (
          SELECT organization_id,
                 any_value(coalesce(nombre_area,nombre_capitulo,nombre_partida)) AS organization_name,
                 any_value(nombre_partida) AS partida,
                 any_value(region_code) AS region_code,
                 count(*)::BIGINT AS transactions,
                 coalesce(sum(devengado),0)::DOUBLE AS devengado,
                 coalesce(sum(devengado) FILTER (WHERE is_provider_payment),0)::DOUBLE AS provider_devengado,
                 coalesce(sum(devengado) FILTER (WHERE mes=12),0)::DOUBLE AS december_devengado,
                 count(*) FILTER (WHERE is_provider_payment AND orden_compra IS NULL)::BIGINT AS provider_tx_without_oc,
                 count(*) FILTER (WHERE is_provider_payment)::BIGINT AS provider_transactions,
                 median(dias_pago) AS days_to_pay_median
          FROM txr WHERE coalesce(organization_id,'')<>'' GROUP BY 1
        ), conc AS (
          SELECT po.organization_id,
                 count(*)::BIGINT AS providers,
                 arg_max(po.provider_id, po.amount) AS top_provider_id,
                 max(po.amount)/nullif(t.provider_amount,0) AS top_provider_share,
                 sum(power(po.amount/nullif(t.provider_amount,0),2)) AS provider_hhi
          FROM prov_org po JOIN org_provider_total t USING(organization_id)
          GROUP BY po.organization_id, t.provider_amount
        )
        SELECT b.*, c.providers, c.top_provider_id, c.top_provider_share, c.provider_hhi,
               coalesce(s.signals,0)::BIGINT AS signals,
               coalesce(s.p1_signals,0)::BIGINT AS p1_signals,
               coalesce(s.fragmentation_signals,0)::BIGINT AS fragmentation_signals,
               coalesce(s.duplicate_signals,0)::BIGINT AS duplicate_signals,
               coalesce(s.concentration_signals,0)::BIGINT AS concentration_signals,
               coalesce(s.year_end_signals,0)::BIGINT AS year_end_signals,
               coalesce(s.cgr_linked_signals,0)::BIGINT AS cgr_linked_signals
        FROM base b
        LEFT JOIN conc c USING(organization_id)
        LEFT JOIN org_signals s USING(organization_id)
        ORDER BY b.devengado DESC
        LIMIT {int(cfg['output']['top_organizations'])}
        """
    )
    names = {
        str(r["provider_id"]): r["provider_name"]
        for r in _rows(con, "SELECT provider_id, provider_name FROM prov")
    } if rows else {}
    for row in rows:
        row["share_of_national"] = _share(row["devengado"], total)
        row["december_share"] = _share(row["december_devengado"], row["devengado"])
        row["missing_oc_share"] = _share(row["provider_tx_without_oc"], row["provider_transactions"])
        row["top_provider_share"] = _round(row.get("top_provider_share"), 6)
        row["provider_hhi"] = _round(row.get("provider_hhi"), 6)
        row["top_provider_name"] = names.get(str(row.get("top_provider_id")))
        row["days_to_pay_median"] = _round(row.get("days_to_pay_median"), 2)
        row["provider_spend_share"] = _share(row["provider_devengado"], row["devengado"])
    return rows


def _provider_candidates(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], limit: int = 6000) -> list[dict[str, Any]]:
    """Universo de evaluación: proveedores materiales más los ya señalizados.

    Evita puntuar 190 mil proveedores para mostrar 60: prioriza monto y
    presencia en la cola de investigación, que es donde vive la atipicidad.
    """
    min_amount = float(cfg["materiality"]["provider_min_amount_clp"])
    return _rows(
        con,
        f"""
        WITH scored AS (
          SELECT p.*, c.top_client_id, c.top_client_name, c.top_client_share,
                 c.max_share_of_buyer, c.max_share_of_buyer_name, c.max_share_of_buyer_providers,
                 c.client_hhi,
                 coalesce(s.signals,0)::BIGINT AS signals,
                 coalesce(s.p1_signals,0)::BIGINT AS p1_signals,
                 coalesce(s.high_signals,0)::BIGINT AS high_signals,
                 coalesce(s.cgr_match_count,0)::BIGINT AS cgr_match_count,
                 coalesce(s.signal_types,[]) AS signal_types,
                 s.max_priority_score
          FROM prov p
          LEFT JOIN prov_concentration c USING(provider_id)
          LEFT JOIN prov_signals s USING(provider_id)
        )
        SELECT * FROM scored
        WHERE amount>={min_amount} OR signals>0
        ORDER BY amount DESC
        LIMIT {int(limit)}
        """
    )


def _new_entrant_context(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any]) -> dict[str, Any]:
    """Cohorte de proveedores cuya primera aparición es el último año de la serie.

    "Nuevo en la serie" no es "empresa nueva": la serie procesada puede no
    cubrir años anteriores. El corte se declara junto al dato.
    """
    quantile = float(cfg["new_entrants"]["cohort_quantile"])
    meta = _one(con, "SELECT max(periodo)::BIGINT AS last_year, count(DISTINCT periodo)::BIGINT AS years FROM txr")
    last_year = meta.get("last_year")
    years = int(meta.get("years") or 0)
    if last_year is None or years < 2:
        return {
            "available": False,
            "reason": "SERIE_INSUFICIENTE" if years < 2 else "SIN_PERIODO",
            "cohort_year": None if last_year is None else int(last_year),
            "series_years": years,
            "cohort": [],
        }
    cohort = _rows(
        con,
        f"""
        SELECT provider_id, provider_name, rut, amount, transactions, organizations, regions,
               first_period, months_active, december_amount, tx_without_oc, tx_round_amount,
               days_to_pay_median, max_transaction_amount
        FROM prov
        WHERE first_year={int(last_year)} AND last_year={int(last_year)}
        ORDER BY amount DESC
        """
    )
    amounts = sorted((_num(r["amount"]) or 0.0) for r in cohort)
    total = sum(amounts)
    threshold = None
    if amounts:
        index = min(len(amounts) - 1, max(0, int(round(quantile * (len(amounts) - 1)))))
        threshold = amounts[index]
    return {
        "available": True,
        "cohort_year": int(last_year),
        "series_years": years,
        "cohort_providers": len(cohort),
        "cohort_amount": round(total, 2),
        "cohort_quantile": quantile,
        "cohort_quantile_amount": None if threshold is None else round(threshold, 2),
        "cohort": cohort,
        "cohort_amount_total": round(total, 2),
    }


# Pesos del score de atipicidad de proveedor. Suman 100 y cada uno debe poder
# explicarse en una frase ante un tercero: el score ordena trabajo, no acusa.
SCORE_WEIGHTS: dict[str, dict[str, Any]] = {
    "CONCENTRA_GASTO_DEL_COMPRADOR": {
        "weight": 16,
        "label": "Concentra el gasto a proveedores de un organismo",
        "reading": "Puede reflejar contrato marco, monopolio técnico o proyecto único; exige comparar categoría y competencia.",
    },
    "NUEVO_CON_MONTO_MATERIAL": {
        "weight": 16,
        "label": "Nuevo en la serie con monto material",
        "reading": "Nuevo en la serie procesada no equivale a empresa nueva ni a irregularidad.",
    },
    "DEPENDENCIA_DE_UN_COMPRADOR": {
        "weight": 12,
        "label": "Depende de un solo comprador estatal",
        "reading": "Habitual en proveedores especializados; relevante sólo junto a otras señales.",
    },
    "CONCENTRACION_EN_DICIEMBRE": {
        "weight": 12,
        "label": "Gasto concentrado en el cierre del año",
        "reading": "El cierre presupuestario genera estacionalidad legítima; el patrón importa por su magnitud relativa.",
    },
    "SIN_ORDEN_DE_COMPRA": {
        "weight": 10,
        "label": "Pagos sin orden de compra registrada",
        "reading": "Hay modalidades legítimas sin OC (convenios, trato directo autorizado); es una brecha documental a resolver.",
    },
    "SENAL_FRACCIONAMIENTO_O_DUPLICADO": {
        "weight": 10,
        "label": "Señales de fraccionamiento o pago duplicado candidato",
        "reading": "Ambos patrones admiten explicación contable; requieren revisar documento y recepción conforme.",
    },
    "MONTOS_REDONDOS": {
        "weight": 8,
        "label": "Predominio de montos exactamente redondos",
        "reading": "Frecuente en anticipos y cuotas de convenio; anómalo cuando domina toda la relación.",
    },
    "PAGO_ACELERADO": {
        "weight": 8,
        "label": "Pago sistemáticamente más rápido que el patrón país",
        "reading": "Puede responder a pronto pago pactado; se contrasta con la mediana nacional de días de pago.",
    },
    "MONTO_ATIPICO": {
        "weight": 6,
        "label": "Transacciones de monto atípico en su grupo comparable",
        "reading": "Hitos contractuales grandes producen el mismo patrón.",
    },
    "ENLACE_CGR": {
        "weight": 4,
        "label": "Coincidencia candidata con hallazgos CGR",
        "reading": "Es coincidencia de entidad, no atribución de un hallazgo a esta transacción.",
    },
}

TIER_THRESHOLDS = (("A1", 55.0), ("A2", 30.0), ("A3", 12.0))


def _tier(score: float) -> str | None:
    for tier, floor in TIER_THRESHOLDS:
        if score >= floor:
            return tier
    return None


def _score_provider(row: dict[str, Any], cfg: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Score explicable 0-100 de atipicidad de la relación de pago.

    Cada contribución declara su métrica de respaldo y su lectura alternativa,
    para que descartarla sea tan barato como confirmarla.
    """
    conc_cfg = cfg["concentration"]
    reasons: list[dict[str, Any]] = []

    def add(code: str, detail: str, metric: dict[str, Any], factor: float = 1.0) -> None:
        spec = SCORE_WEIGHTS[code]
        reasons.append(
            {
                "code": code,
                "label": spec["label"],
                "weight": round(float(spec["weight"]) * max(0.0, min(1.0, factor)), 2),
                "max_weight": spec["weight"],
                "detail": detail,
                "alternative_reading": spec["reading"],
                "metric": metric,
            }
        )

    amount = _num(row.get("amount")) or 0.0
    transactions = int(row.get("transactions") or 0)
    signal_types = {str(x) for x in (row.get("signal_types") or [])}

    buyer_share = _num(row.get("max_share_of_buyer"))
    if buyer_share is not None and buyer_share >= float(conc_cfg["buyer_share_watch"]):
        span = max(1e-9, 1.0 - float(conc_cfg["buyer_share_watch"]))
        add(
            "CONCENTRA_GASTO_DEL_COMPRADOR",
            f"Representa {buyer_share:.0%} del gasto a proveedores de {row.get('max_share_of_buyer_name') or 'un organismo'}.",
            {"max_share_of_buyer": round(buyer_share, 4), "buyers_in_that_organization": row.get("max_share_of_buyer_providers")},
            factor=0.55 + 0.45 * (buyer_share - float(conc_cfg["buyer_share_watch"])) / span,
        )

    cohort_year = context.get("cohort_year")
    cohort_threshold = _num(context.get("cohort_quantile_amount")) or 0.0
    min_new_amount = float(cfg["new_entrants"]["min_amount_clp"])
    if (
        cohort_year is not None
        and int(row.get("first_year") or 0) == int(cohort_year)
        and amount >= max(min_new_amount, cohort_threshold)
    ):
        add(
            "NUEVO_CON_MONTO_MATERIAL",
            f"Primera aparición en {cohort_year} y monto sobre el corte del cohorte de entrantes.",
            {
                "first_year": row.get("first_year"),
                "amount_clp": round(amount, 2),
                "cohort_quantile_amount": round(cohort_threshold, 2),
            },
            factor=1.0 if amount >= cohort_threshold * 2 else 0.7,
        )

    client_share = _num(row.get("top_client_share"))
    if (
        client_share is not None
        and client_share >= float(conc_cfg["client_dependency_share"])
        and amount >= float(cfg["materiality"]["provider_min_amount_clp"])
    ):
        add(
            "DEPENDENCIA_DE_UN_COMPRADOR",
            f"{client_share:.0%} de sus pagos provienen de {row.get('top_client_name') or 'un solo organismo'}.",
            {"top_client_share": round(client_share, 4), "organizations": row.get("organizations")},
            factor=1.0 if int(row.get("organizations") or 0) <= 1 else 0.7,
        )

    december_share = _share(row.get("december_amount"), amount)
    cal = cfg["calendar"]
    if december_share is not None and december_share >= float(cal["december_share_watch"]) and transactions >= 3:
        add(
            "CONCENTRACION_EN_DICIEMBRE",
            f"{december_share:.0%} de su gasto se devenga en diciembre.",
            {"december_share": december_share, "transactions": transactions},
            factor=1.0 if december_share >= float(cal["december_share_alert"]) else 0.6,
        )

    missing_oc_share = _share(row.get("tx_without_oc"), transactions)
    if (
        missing_oc_share is not None
        and missing_oc_share >= float(cfg["documentation"]["missing_purchase_order_share"])
        and amount >= float(cfg["materiality"]["provider_min_amount_clp"])
    ):
        add(
            "SIN_ORDEN_DE_COMPRA",
            f"{missing_oc_share:.0%} de sus pagos no registran orden de compra.",
            {"missing_oc_share": missing_oc_share, "transactions": transactions},
            factor=missing_oc_share,
        )

    if {"POTENTIAL_FRAGMENTATION", "EXACT_DUPLICATE_CANDIDATE"} & signal_types:
        detail = " y ".join(
            sorted(
                {
                    "fraccionamiento potencial" if t == "POTENTIAL_FRAGMENTATION" else "duplicado candidato"
                    for t in signal_types
                    if t in {"POTENTIAL_FRAGMENTATION", "EXACT_DUPLICATE_CANDIDATE"}
                }
            )
        )
        add(
            "SENAL_FRACCIONAMIENTO_O_DUPLICADO",
            f"La cola de investigación registra {detail} en sus pagos.",
            {"signals": row.get("signals"), "p1_signals": row.get("p1_signals")},
            factor=1.0 if int(row.get("p1_signals") or 0) > 0 else 0.7,
        )

    round_share = _share(row.get("tx_round_amount"), transactions)
    if round_share is not None and round_share >= 0.5 and transactions >= 5:
        add(
            "MONTOS_REDONDOS",
            f"{round_share:.0%} de sus pagos son múltiplos exactos de ${int(cfg['materiality']['round_amount_multiple_clp']):,}".replace(",", ".") + ".",
            {"round_amount_share": round_share, "transactions": transactions},
            factor=round_share,
        )

    days_median = _num(row.get("days_to_pay_median"))
    national_days = _num(context.get("national_days_median"))
    speed = cfg["payment_speed"]
    if (
        days_median is not None
        and national_days is not None
        and national_days >= float(speed["national_median_floor_days"])
        and days_median <= float(speed["fast_payment_days"])
        and int(row.get("tx_with_days") or 0) >= 5
    ):
        add(
            "PAGO_ACELERADO",
            f"Mediana de {days_median:.0f} días de pago frente a {national_days:.0f} días del país.",
            {"days_to_pay_median": days_median, "national_days_median": national_days},
        )

    if "AMOUNT_OUTLIER" in signal_types:
        add(
            "MONTO_ATIPICO",
            "Al menos un pago queda en la cola extrema de su grupo organismo/subtítulo/ítem.",
            {"max_transaction_amount": _round(row.get("max_transaction_amount"), 2)},
        )

    if int(row.get("cgr_match_count") or 0) > 0:
        add(
            "ENLACE_CGR",
            "Existe coincidencia candidata de entidad con hallazgos publicados por CGR.",
            {"cgr_match_count": row.get("cgr_match_count")},
        )

    score = round(min(100.0, sum(float(r["weight"]) for r in reasons)), 2)
    return {
        "anomaly_score": score,
        "anomaly_tier": _tier(score),
        "reasons": sorted(reasons, key=lambda r: -float(r["weight"])),
    }


def _provider_public_row(row: dict[str, Any], national_amount: float, provider_amount: float) -> dict[str, Any]:
    """Proyección estable del perfil de proveedor para la vista web."""
    amount = _num(row.get("amount")) or 0.0
    transactions = int(row.get("transactions") or 0)
    return {
        "provider_id": row.get("provider_id"),
        "provider_name": row.get("provider_name"),
        "rut": row.get("rut"),
        "entity_id": row.get("entity_id"),
        "is_person": bool(row.get("is_person")),
        "amount_clp": round(amount, 2),
        "share_of_provider_spend": _share(amount, provider_amount),
        "share_of_national_spend": _share(amount, national_amount),
        "transactions": transactions,
        "organizations": int(row.get("organizations") or 0),
        "regions": int(row.get("regions") or 0),
        "first_year": row.get("first_year"),
        "last_year": row.get("last_year"),
        "years_active": int(row.get("years_active") or 0),
        "months_active": int(row.get("months_active") or 0),
        "average_transaction_clp": _round(amount / transactions, 2) if transactions else None,
        "max_transaction_clp": _round(row.get("max_transaction_amount"), 2),
        "top_client_id": row.get("top_client_id"),
        "top_client_name": row.get("top_client_name"),
        "top_client_share": _round(row.get("top_client_share"), 4),
        "client_hhi": _round(row.get("client_hhi"), 4),
        "max_share_of_buyer": _round(row.get("max_share_of_buyer"), 4),
        "max_share_of_buyer_name": row.get("max_share_of_buyer_name"),
        "december_share": _share(row.get("december_amount"), amount),
        "missing_oc_share": _share(row.get("tx_without_oc"), transactions),
        "round_amount_share": _share(row.get("tx_round_amount"), transactions),
        "days_to_pay_median": _round(row.get("days_to_pay_median"), 2),
        "fast_paid_share": _share(row.get("tx_fast_paid"), row.get("tx_with_days")),
        "floating_debt_share": _share(row.get("tx_floating_debt"), transactions),
        "signals": int(row.get("signals") or 0),
        "p1_signals": int(row.get("p1_signals") or 0),
        "signal_types": sorted(str(x) for x in (row.get("signal_types") or [])),
        "cgr_match_count": int(row.get("cgr_match_count") or 0),
        "max_priority_score": _round(row.get("max_priority_score"), 2),
    }


def _pattern_blocks(con: duckdb.DuckDBPyConnection, totals: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Patrones transversales: calendario, documentación y comportamiento de pago."""
    devengado = _num(totals.get("devengado")) or 0.0
    provider_tx = int(totals.get("provider_transactions") or 0)
    signal_types = dict(
        (str(k), int(v))
        for k, v in con.execute(
            "SELECT signal_type, count(*) FROM sig GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    fragmentation_orgs = _rows(
        con,
        """
        SELECT s.organization_id,
               any_value(coalesce(t.nombre_area,t.nombre_capitulo,t.nombre_partida)) AS organization_name,
               count(*)::BIGINT AS fragmentation_signals
        FROM sig s LEFT JOIN txr t ON s.transaction_id=t.transaction_id
        WHERE s.signal_type='POTENTIAL_FRAGMENTATION'
        GROUP BY 1 ORDER BY 3 DESC LIMIT 10
        """
    )
    duplicate_orgs = _rows(
        con,
        """
        SELECT s.organization_id,
               any_value(coalesce(t.nombre_area,t.nombre_capitulo,t.nombre_partida)) AS organization_name,
               count(*)::BIGINT AS duplicate_signals,
               coalesce(sum(t.devengado),0)::DOUBLE AS exposed_amount_clp
        FROM sig s LEFT JOIN txr t ON s.transaction_id=t.transaction_id
        WHERE s.signal_type='EXACT_DUPLICATE_CANDIDATE'
        GROUP BY 1 ORDER BY 3 DESC LIMIT 10
        """
    )
    december_orgs = _rows(
        con,
        """
        SELECT organization_id,
               any_value(coalesce(nombre_area,nombre_capitulo,nombre_partida)) AS organization_name,
               coalesce(sum(devengado),0)::DOUBLE AS devengado,
               coalesce(sum(devengado) FILTER (WHERE mes=12),0)::DOUBLE AS december_devengado,
               count(*)::BIGINT AS transactions
        FROM txr WHERE coalesce(organization_id,'')<>''
        GROUP BY 1
        HAVING sum(devengado)>0
        ORDER BY december_devengado DESC LIMIT 12
        """
    )
    for row in december_orgs:
        row["december_share"] = _share(row["december_devengado"], row["devengado"])

    single_client = _one(
        con,
        f"""
        SELECT count(*)::BIGINT AS providers,
               coalesce(sum(p.amount),0)::DOUBLE AS amount_clp
        FROM prov p JOIN prov_concentration c USING(provider_id)
        WHERE p.organizations=1 AND p.amount>={float(cfg['materiality']['provider_min_amount_clp'])}
        """
    )
    return {
        "signal_types": signal_types,
        "fragmentation_top_organizations": fragmentation_orgs,
        "duplicate_top_organizations": duplicate_orgs,
        "december_top_organizations": december_orgs,
        "national_shares": {
            "december_share_of_devengado": _share(totals.get("december_devengado"), devengado),
            "provider_share_of_devengado": _share(totals.get("provider_devengado"), devengado),
            "person_share_of_devengado": _share(totals.get("person_devengado"), devengado),
            "honorarium_share_of_devengado": _share(totals.get("honorarium_devengado"), devengado),
            "intra_state_share_of_devengado": _share(totals.get("intra_state_devengado"), devengado),
            "floating_debt_share_of_devengado": _share(totals.get("floating_debt_devengado"), devengado),
            "provider_tx_without_oc_share": _share(totals.get("provider_tx_without_oc"), provider_tx),
            "provider_tx_round_amount_share": _share(totals.get("provider_tx_round"), provider_tx),
            "fast_paid_share": _share(totals.get("tx_fast_paid"), totals.get("tx_with_days")),
            "slow_paid_share": _share(totals.get("tx_slow_paid"), totals.get("tx_with_days")),
        },
        "single_client_providers": {
            "providers": int(single_client.get("providers") or 0),
            "amount_clp": _round(single_client.get("amount_clp"), 2),
            "definition": "Proveedor material con un único organismo comprador en la serie procesada.",
        },
    }


def _headline(
    totals: dict[str, Any],
    regional: dict[str, Any],
    patterns: dict[str, Any],
    new_entrants: dict[str, Any],
    anomalous: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Indicadores de lectura ágil: qué mirar primero y con qué advertencia."""
    devengado = _num(totals.get("devengado")) or 0.0
    shares = patterns["national_shares"]
    concentration = regional["concentration"]
    new_material = [p for p in new_entrants.get("material", [])]
    a1 = [p for p in anomalous if p.get("anomaly_tier") == "A1"]

    def tone(value: Any, watch: float, alert: float) -> str:
        v = _num(value)
        if v is None:
            return "neutral"
        if v >= alert:
            return "alert"
        if v >= watch:
            return "watch"
        return "neutral"

    return [
        {
            "id": "devengado_total",
            "label": "Devengado analizado",
            "value": round(devengado, 2),
            "format": "money",
            "tone": "neutral",
            "hint": f"{totals.get('years') or 0} año(s) de la serie procesada",
            "basis": "sum(monto_devengado) sobre transacciones normalizadas",
        },
        {
            "id": "payment_ratio",
            "label": "Pagado / devengado",
            "value": _share(totals.get("pagado"), devengado),
            "format": "percent",
            "tone": "neutral",
            "hint": "Ritmo de caja observado, no avance sobre la Ley de Presupuestos",
            "basis": "sum(monto_pago) / sum(monto_devengado)",
        },
        {
            "id": "provider_spend_share",
            "label": "Gasto a proveedores",
            "value": shares["provider_share_of_devengado"],
            "format": "percent",
            "tone": "neutral",
            "hint": "Fracción del devengado que va a terceros marcados como proveedor",
            "basis": "flag PROVEEDOR de la fuente",
        },
        {
            "id": "region_concentration",
            "label": "Concentración territorial (top 1)",
            "value": concentration.get("top1_share"),
            "format": "percent",
            "tone": tone(concentration.get("top1_share"), 0.45, 0.6),
            "hint": f"Región líder: {concentration.get('top1_region') or 'sin dato'}",
            "basis": "share regional del devengado con región informada",
        },
        {
            "id": "region_gini",
            "label": "Gini regional del gasto",
            "value": concentration.get("gini"),
            "format": "ratio",
            "tone": tone(concentration.get("gini"), 0.6, 0.75),
            "hint": "Desigualdad territorial del flujo; alta concentración es esperable por centralismo administrativo",
            "basis": "Gini sobre devengado por región",
        },
        {
            "id": "december_share",
            "label": "Peso de diciembre",
            "value": shares["december_share_of_devengado"],
            "format": "percent",
            "tone": tone(shares["december_share_of_devengado"], 0.15, 0.25),
            "hint": "Referencia de reparto uniforme: 8,3% mensual",
            "basis": "devengado de diciembre / devengado total",
        },
        {
            "id": "missing_oc_share",
            "label": "Pagos a proveedor sin OC",
            "value": shares["provider_tx_without_oc_share"],
            "format": "percent",
            "tone": tone(shares["provider_tx_without_oc_share"], 0.4, 0.6),
            "hint": "Brecha documental: hay modalidades legítimas sin orden de compra",
            "basis": "transacciones proveedor sin orden_compra / transacciones proveedor",
        },
        {
            "id": "days_to_pay_median",
            "label": "Días de pago (mediana)",
            "value": _round(totals.get("days_to_pay_median"), 1),
            "format": "days",
            "tone": "neutral",
            "hint": "Base para leer pagos acelerados y morosidad",
            "basis": "median(dias_de_pago) sobre transacciones con dato",
        },
        {
            "id": "new_provider_amount",
            "label": "Adjudicado a proveedores nuevos",
            "value": round(sum((_num(p.get("amount_clp")) or 0.0) for p in new_material), 2),
            "format": "money",
            "tone": "watch" if new_material else "neutral",
            "hint": f"{len(new_material)} proveedor(es) nuevo(s) con monto material en {new_entrants.get('cohort_year') or '—'}",
            "basis": f"primera aparición en el último año de la serie y monto sobre el corte p{int(float(cfg['new_entrants']['cohort_quantile'])*100)}",
        },
        {
            "id": "anomalous_providers",
            "label": "Proveedores en tier A1",
            "value": len(a1),
            "format": "integer",
            "tone": "alert" if a1 else "neutral",
            "hint": "Score de atipicidad ≥ 55 sobre 100; es prioridad de revisión, no imputación",
            "basis": "suma de contribuciones explicables por proveedor",
        },
        {
            "id": "single_client_providers",
            "label": "Proveedores con comprador único",
            "value": patterns["single_client_providers"]["providers"],
            "format": "integer",
            "tone": "neutral",
            "hint": "Material y con un solo organismo comprador en la serie",
            "basis": "count(distinct organization_id)=1 sobre proveedores materiales",
        },
        {
            "id": "region_coverage",
            "label": "Cobertura de región",
            "value": _share(totals.get("region_known_devengado"), devengado),
            "format": "percent",
            "tone": "neutral",
            "hint": "Devengado con región resuelta; el resto queda en 'sin región informada'",
            "basis": "campo REGION o prefijo de ubicación geográfica",
        },
    ]


def _alerts(
    totals: dict[str, Any],
    regional: dict[str, Any],
    patterns: dict[str, Any],
    organizations: list[dict[str, Any]],
    new_entrants: dict[str, Any],
    anomalous: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Lecturas accionables generadas del propio agregado, con su matiz."""
    out: list[dict[str, Any]] = []
    shares = patterns["national_shares"]
    concentration = regional["concentration"]

    top1 = _num(concentration.get("top1_share"))
    if top1 is not None and top1 >= 0.35:
        out.append(
            {
                "severity": "WATCH" if top1 < 0.55 else "ALERT",
                "title": f"{concentration.get('top1_region')} concentra {top1:.0%} del devengado con región informada",
                "detail": "La concentración territorial refleja tanto centralismo administrativo (pagos nacionales imputados al nivel central) como tamaño real del gasto. Antes de leerla como riesgo, separar organismos de alcance nacional de servicios regionales.",
                "metric": {"top1_share": top1, "gini": concentration.get("gini")},
            }
        )

    december = _num(shares.get("december_share_of_devengado"))
    if december is not None and december >= float(cfg["calendar"]["december_share_watch"]) / 2:
        out.append(
            {
                "severity": "WATCH" if december < 0.25 else "ALERT",
                "title": f"Diciembre concentra {december:.0%} del devengado del período",
                "detail": "El cierre presupuestario produce estacionalidad legítima; el foco analítico son los organismos y proveedores cuyo peso de diciembre se aleja de su propio historial.",
                "metric": {"december_share": december, "uniform_reference": round(1 / 12, 4)},
            }
        )

    no_oc = _num(shares.get("provider_tx_without_oc_share"))
    if no_oc is not None and no_oc >= 0.3:
        out.append(
            {
                "severity": "WATCH" if no_oc < 0.6 else "ALERT",
                "title": f"{no_oc:.0%} de los pagos a proveedores no registran orden de compra",
                "detail": "Es una brecha de trazabilidad documental, no evidencia de irregularidad: convenios, transferencias y tratos directos autorizados pueden carecer de OC en esta fuente.",
                "metric": {"missing_oc_share": no_oc},
            }
        )

    dependent_orgs = [
        o
        for o in organizations
        if (_num(o.get("top_provider_share")) or 0) >= float(cfg["concentration"]["buyer_share_alert"])
    ]
    if dependent_orgs:
        worst = max(dependent_orgs, key=lambda o: _num(o.get("top_provider_share")) or 0)
        out.append(
            {
                "severity": "WATCH",
                "title": f"{len(dependent_orgs)} organismo(s) del top de gasto dependen de un proveedor dominante",
                "detail": f"Caso extremo: {worst.get('organization_name')} con {(_num(worst.get('top_provider_share')) or 0):.0%} de su gasto a proveedores en {worst.get('top_provider_name') or 'un solo proveedor'}. Contrastar con contratos marco, monopolios técnicos y evolución del HHI.",
                "metric": {
                    "organizations": len(dependent_orgs),
                    "max_top_provider_share": _num(worst.get("top_provider_share")),
                },
            }
        )

    material_new = new_entrants.get("material", [])
    if material_new:
        amount = sum((_num(p.get("amount_clp")) or 0.0) for p in material_new)
        out.append(
            {
                "severity": "WATCH",
                "title": f"{len(material_new)} proveedores nuevos capturan ${amount:,.0f} en {new_entrants.get('cohort_year')}".replace(",", "."),
                "detail": "Nuevo en la serie procesada no equivale a empresa recién constituida: puede ser rotación de proveedor o cobertura histórica incompleta. Verificar primera adjudicación, antigüedad societaria y capacidad declarada.",
                "metric": {
                    "providers": len(material_new),
                    "amount_clp": round(amount, 2),
                    "cohort_year": new_entrants.get("cohort_year"),
                },
            }
        )

    a1 = [p for p in anomalous if p.get("anomaly_tier") == "A1"]
    if a1:
        out.append(
            {
                "severity": "ALERT",
                "title": f"{len(a1)} proveedores acumulan patrones concurrentes (tier A1)",
                "detail": "El tier A1 exige varias contribuciones simultáneas (concentración, entrada nueva, calendario, documentación). Cada una admite explicación individual; la concurrencia es lo que justifica revisar el expediente.",
                "metric": {
                    "providers": len(a1),
                    "amount_clp": round(sum((_num(p.get("amount_clp")) or 0.0) for p in a1), 2),
                },
            }
        )

    unassigned = _num(concentration.get("unassigned_share"))
    if unassigned is not None and unassigned >= 0.02:
        out.append(
            {
                "severity": "INFO",
                "title": f"{unassigned:.1%} del devengado no tiene región informada",
                "detail": "Se reporta como categoría propia y no se redistribuye: cualquier lectura territorial debe hacerse sobre el devengado con región resuelta.",
                "metric": {"unassigned_share": unassigned},
            }
        )
    return out


INDICATOR_CATALOG: list[dict[str, str]] = [
    {"id": "provider_hhi", "name": "HHI de proveedores", "definition": "Suma de cuadrados de la participación de cada proveedor en el gasto a proveedores de la unidad (organismo o región).", "reading": "0 = atomizado, 1 = un solo proveedor. Sobre 0,25 la unidad depende de pocos actores."},
    {"id": "top_provider_share", "name": "Participación del proveedor dominante", "definition": "Gasto del mayor proveedor sobre el gasto a proveedores de la unidad.", "reading": "Comparar con la categoría contratada: en servicios especializados es habitual."},
    {"id": "top_client_share", "name": "Dependencia del comprador", "definition": "Participación del principal organismo comprador en los pagos recibidos por el proveedor.", "reading": "Cerca de 1 indica proveedor cautivo de un solo servicio."},
    {"id": "december_share", "name": "Peso del cierre anual", "definition": "Devengado de diciembre sobre el devengado del período.", "reading": "Referencia de reparto uniforme: 8,3%. Desviaciones fuertes concentran decisiones en el cierre."},
    {"id": "missing_oc_share", "name": "Brecha de orden de compra", "definition": "Transacciones a proveedor sin orden de compra registrada sobre el total de transacciones a proveedor.", "reading": "Mide trazabilidad documental, no legalidad."},
    {"id": "round_amount_share", "name": "Predominio de montos redondos", "definition": "Pagos que son múltiplo exacto del monto de referencia configurado.", "reading": "Frecuente en cuotas y anticipos; anómalo cuando domina la relación completa."},
    {"id": "days_to_pay_median", "name": "Mediana de días de pago", "definition": "Mediana del campo DIAS_DE_PAGO de la fuente.", "reading": "Sirve para detectar tanto morosidad como pago excepcionalmente acelerado."},
    {"id": "gini_regional", "name": "Gini territorial", "definition": "Desigualdad de la distribución del devengado entre regiones con dato.", "reading": "Alto por diseño institucional; útil como serie comparable en el tiempo."},
    {"id": "p1_per_100k_transactions", "name": "Intensidad de señales P1", "definition": "Señales de prioridad P1 por cada 100.000 transacciones de la unidad.", "reading": "Normaliza por volumen para que las regiones grandes no dominen sólo por tamaño."},
    {"id": "anomaly_score", "name": "Score de atipicidad de proveedor", "definition": "Suma acotada a 100 de contribuciones explicables (concentración, entrada nueva, calendario, documentación, señales, CGR).", "reading": "Ordena revisión analítica. No estima culpabilidad, delito ni riesgo LA/FT."},
]

GUARDRAILS: list[str] = [
    "GASTO_PUBLICO_NO_ES_RIESGO_POR_SI_MISMO",
    "AUSENCIA_NO_ES_CERO",
    "SCORE_ES_PRIORIDAD_ANALITICA_NO_IMPUTACION",
    "NUEVO_EN_LA_SERIE_NO_ES_EMPRESA_NUEVA",
    "SIN_ORDEN_DE_COMPRA_NO_IMPLICA_ILEGALIDAD",
    "ENLACE_CGR_ES_COINCIDENCIA_CANDIDATA_DE_ENTIDAD",
    "EJECUCION_ES_FLUJO_OBSERVADO_NO_AVANCE_SOBRE_LEY_DE_PRESUPUESTOS",
    "REGION_DE_LA_FUENTE_NO_ES_COMUNA_CANONICA",
]


def build_spend_view(
    parquet_glob: str = "data/processed/transactions_*.parquet",
    prioritized_path: str = "data/signals/prioritized_signals.parquet",
    output: str = DEFAULT_OUTPUT,
    config_path: str | Path = DEFAULT_CONFIG,
    mode: str = "REAL",
) -> dict[str, Any]:
    """Construye la vista de ejecución y pagos y la publica como JSON compacto."""
    files = sorted(glob.glob(parquet_glob)) if "*" in parquet_glob else [parquet_glob]
    if not [f for f in files if Path(f).exists()]:
        raise FileNotFoundError(f"No hay parquet de transacciones que coincida con {parquet_glob}")

    cfg = load_view_config(config_path)
    con = duckdb.connect()
    try:
        source_meta = _prepare_transactions(con, parquet_glob)
        _prepare_providers(con, cfg)
        priority_available = _prepare_signals(con, prioritized_path)

        totals = _national_totals(con, cfg)
        devengado = _num(totals.get("devengado")) or 0.0
        provider_devengado = _num(totals.get("provider_devengado")) or 0.0

        execution = _execution_blocks(con)
        regional = _regional_blocks(con, cfg)
        budget_lines = _budget_lines(con, cfg, devengado)
        organizations = _organizations(con, cfg, devengado)

        candidates = _provider_candidates(con, cfg)
        new_context = _new_entrant_context(con, cfg)
        context = {
            "national_days_median": totals.get("days_to_pay_median"),
            "cohort_year": new_context.get("cohort_year") if new_context.get("available") else None,
            "cohort_quantile_amount": new_context.get("cohort_quantile_amount"),
        }

        scored: list[dict[str, Any]] = []
        for row in candidates:
            public = _provider_public_row(row, devengado, provider_devengado)
            public.update(_score_provider(row, cfg, context))
            scored.append(public)

        top_providers = sorted(scored, key=lambda r: -(_num(r["amount_clp"]) or 0.0))[
            : int(cfg["output"]["top_providers"])
        ]
        anomalous = [r for r in scored if r.get("anomaly_tier")]
        anomalous.sort(
            key=lambda r: (-(_num(r["anomaly_score"]) or 0.0), -(_num(r["amount_clp"]) or 0.0))
        )
        anomalous = anomalous[: int(cfg["output"]["top_anomalous_providers"])]

        cohort_amount = _num(new_context.get("cohort_amount")) or 0.0
        min_new = float(cfg["new_entrants"]["min_amount_clp"])
        threshold = max(min_new, _num(new_context.get("cohort_quantile_amount")) or 0.0)
        by_id = {str(r["provider_id"]): r for r in scored}
        new_rows: list[dict[str, Any]] = []
        for row in new_context.get("cohort", []):
            amount = _num(row.get("amount")) or 0.0
            if amount < threshold:
                continue
            enriched = dict(by_id.get(str(row.get("provider_id")), {}))
            if not enriched:
                enriched = {
                    "provider_id": row.get("provider_id"),
                    "provider_name": row.get("provider_name"),
                    "rut": row.get("rut"),
                    "amount_clp": round(amount, 2),
                    "transactions": int(row.get("transactions") or 0),
                    "organizations": int(row.get("organizations") or 0),
                }
            enriched.update(
                {
                    "cohort_year": new_context.get("cohort_year"),
                    "share_of_new_cohort": _share(amount, cohort_amount),
                    "first_period": row.get("first_period"),
                    "months_active": int(row.get("months_active") or 0),
                    "exceeds_cohort_threshold": True,
                    "cohort_threshold_clp": round(threshold, 2),
                }
            )
            new_rows.append(enriched)
        new_rows.sort(key=lambda r: -(_num(r.get("amount_clp")) or 0.0))
        new_rows = new_rows[: int(cfg["output"]["top_new_providers"])]
        new_entrants = {
            **{k: v for k, v in new_context.items() if k != "cohort"},
            "material": new_rows,
        }

        patterns = _pattern_blocks(con, totals, cfg)
        headline = _headline(totals, regional, patterns, new_entrants, anomalous, cfg)
        alerts = _alerts(totals, regional, patterns, organizations, new_entrants, anomalous, cfg)
    finally:
        con.close()

    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_system": "PRESUPUESTO_ABIERTO",
        "radar_id": "RADAR_PRESUPUESTO",
        "mode": mode,
        "coverage": {
            "first_year": totals.get("first_year"),
            "last_year": totals.get("last_year"),
            "years": int(totals.get("years") or 0),
            "transactions": int(totals.get("transactions") or 0),
            "organizations": int(totals.get("organizations") or 0),
            "recipients": int(totals.get("recipients") or 0),
            "providers": int(totals.get("providers") or 0),
            "devengado_clp": round(devengado, 2),
            "pagado_clp": _round(totals.get("pagado"), 2),
            "provider_devengado_clp": round(provider_devengado, 2),
            "region_resolved_share": _share(totals.get("region_known_devengado"), devengado),
            "distinct_raw_region_values": source_meta.get("distinct_raw_regions"),
            "priority_queue_available": priority_available,
            "parquet_files": len([f for f in files if Path(f).exists()]),
        },
        "headline_indicators": headline,
        "alerts": alerts,
        "execution": execution,
        "territory": regional,
        "budget_lines": budget_lines,
        "organizations": organizations,
        "providers": {
            "top_by_amount": top_providers,
            "anomalous": anomalous,
            "evaluated_candidates": len(candidates),
            "score_weights": {code: spec["weight"] for code, spec in SCORE_WEIGHTS.items()},
            "tier_thresholds": {tier: floor for tier, floor in TIER_THRESHOLDS},
        },
        "new_providers": new_entrants,
        "patterns": patterns,
        "indicator_catalog": INDICATOR_CATALOG,
        "thresholds": cfg,
        "region_reference": region_reference(),
        "methodology": {
            "execution_semantics": "FLUJO_DEVENGADO_Y_PAGADO_OBSERVADO",
            "budget_appropriation_available": False,
            "budget_appropriation_note": (
                "La fuente de pagos no publica el presupuesto vigente por organismo, por lo que no "
                "se calcula porcentaje de ejecución sobre la Ley de Presupuestos; se reporta ritmo "
                "y composición del flujo efectivamente devengado y pagado."
            ),
            "provider_definition": "Transacción con flag PROVEEDOR verdadero, identificador de proveedor resuelto y registro no agregado.",
            "region_resolution": "Campo REGION de la fuente; si falta, prefijo de CODIGO_UBICACION_GEOGRAFICA. Irresoluble queda 'Sin región informada'.",
            "score_semantics": "PRIORIDAD_ANALITICA_EXPLICABLE_0_100",
            "signals_reused_from": prioritized_path,
            "no_new_signals_created": True,
        },
        "guardrails": GUARDRAILS,
    }

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Construye la vista de ejecución y pagos del Estado")
    parser.add_argument("--parquet-glob", default="data/processed/transactions_*.parquet")
    parser.add_argument("--priority", default="data/signals/prioritized_signals.parquet")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument(
        "--mode",
        default="REAL",
        choices=["REAL", "DEMO_SYNTHETIC"],
        help="Etiqueta de procedencia que la vista web muestra al usuario.",
    )
    args = parser.parse_args()
    payload = build_spend_view(args.parquet_glob, args.priority, args.output, args.config, args.mode)
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "mode": payload["mode"],
                "transactions": payload["coverage"]["transactions"],
                "regions": len(payload["territory"]["regions"]),
                "anomalous_providers": len(payload["providers"]["anomalous"]),
                "new_providers": len(payload["new_providers"].get("material", [])),
                "alerts": len(payload["alerts"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
