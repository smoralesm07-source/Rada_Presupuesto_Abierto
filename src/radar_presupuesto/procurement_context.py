from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .split_discrimination import (
    GUARDRAIL as SPLIT_GUARDRAIL,
    UNDETERMINED as SPLIT_UNDETERMINED,
    classify_split_shape,
    cluster_sql,
)

SCHEMA = "RIGP-PROCUREMENT-CONTEXT-v2"


GUARDRAIL = (
    "La presencia o ausencia de una orden de compra en Presupuesto Abierto no acredita por sí sola "
    "regularidad o irregularidad del proceso de contratación. Debe contrastarse con Mercado Público "
    "y los documentos del procedimiento correspondiente."
)


def _as_list(value: object) -> list:
    """Normalize DuckDB/Pandas list-like results without ambiguous truth checks."""
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def build_procurement_context(
    parquet_glob: str,
    findings_json: str = "docs/data/investigative_findings.json",
    output_json: str = "docs/data/procurement_context.json",
    max_orders_per_finding: int = 12,
    split_min_count: int = 3,
    split_max_cv: float = 0.15,
    split_max_clusters: int = 3,
) -> dict:
    """Build compact order-of-purchase context for the currently published findings.

    This is the bridge between budget execution and the future Mercado Público layer.
    It intentionally publishes only relations already selected for analyst triage.
    """
    findings_path = Path(findings_json)
    if not findings_path.exists():
        raise FileNotFoundError(findings_json)
    payload = json.loads(findings_path.read_text(encoding="utf-8"))
    relations = payload.get("relation_findings") or []

    targets = []
    for r in relations:
        org = str(r.get("organization_id") or "")
        provider = str(r.get("provider_id") or "")
        year = r.get("periodo")
        fid = str(r.get("finding_id") or "")
        if org and provider and year is not None and fid:
            targets.append(
                {
                    "finding_id": fid,
                    "organization_id": org,
                    "provider_id": provider,
                    "periodo": int(year),
                }
            )

    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not targets:
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": SCHEMA,
            "guardrail": GUARDRAIL,
            "split_guardrail": SPLIT_GUARDRAIL,
            "coverage": {
                "findings_requested": 0,
                "findings_with_rows": 0,
                "findings_with_purchase_order": 0,
                "findings_with_weekly_clusters": 0,
                "findings_worth_triage": 0,
            },
            "findings": [],
        }
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result["coverage"]

    con = duckdb.connect()
    con.register("targets", pd.DataFrame(targets))
    con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)")
    df = con.execute(
        f"""
        SELECT
          t.finding_id,
          t.organization_id,
          t.provider_id,
          t.periodo,
          count(*) AS source_rows,
          sum(CASE WHEN coalesce(trim(f.orden_compra),'')<>'' THEN 1 ELSE 0 END) AS rows_with_purchase_order,
          count(DISTINCT nullif(trim(f.orden_compra),'')) AS purchase_order_count,
          list_slice(
            list_sort(list_distinct(list(nullif(trim(f.orden_compra),'')))),
            1,
            {int(max_orders_per_finding)}
          ) AS purchase_order_examples,
          sum(coalesce(try_cast(f.monto_devengado AS DOUBLE),0)) AS devengado_total,
          min(f.fecha_documento) AS first_document_date,
          max(f.fecha_documento) AS last_document_date
        FROM targets t
        JOIN facts f
          ON f.organization_id=t.organization_id
         AND f.provider_id=t.provider_id
         AND f.periodo=t.periodo
        WHERE coalesce(f.is_aggregated,FALSE)=FALSE
        GROUP BY 1,2,3,4
        ORDER BY purchase_order_count DESC, devengado_total DESC
        """
    ).df()
    # Agrupar por ítem afina el grupo, pero una vista de hechos que no traiga
    # la columna no puede tumbar la capa: se agrupa sin ella y se sigue.
    fact_columns = {str(c[0]) for c in con.execute("DESCRIBE SELECT * FROM facts").fetchall()}
    item_expr = "coalesce(f.item,'')" if "item" in fact_columns else "''"
    clusters = con.execute(
        cluster_sql(min_count=split_min_count, max_cv=split_max_cv,
                    max_clusters=split_max_clusters, item_expr=item_expr)
    ).df()
    con.close()

    by_finding = _split_by_finding(clusters)

    rows = []
    for row in df.where(df.notna(), None).to_dict("records"):
        source_rows = int(row.get("source_rows") or 0)
        with_oc = int(row.get("rows_with_purchase_order") or 0)
        examples = [str(x) for x in _as_list(row.get("purchase_order_examples")) if x]
        rows.append(
            {
                **row,
                "source_rows": source_rows,
                "rows_with_purchase_order": with_oc,
                "purchase_order_count": int(row.get("purchase_order_count") or 0),
                "purchase_order_examples": examples,
                "purchase_order_row_coverage": (with_oc / source_rows) if source_rows else 0.0,
                "has_purchase_order": bool(examples),
                "guardrail": GUARDRAIL,
                **by_finding.get(str(row.get("finding_id") or ""), _no_clusters()),
            }
        )

    by_id = {r["finding_id"]: r for r in rows}
    ordered = [by_id[t["finding_id"]] for t in targets if t["finding_id"] in by_id]
    coverage = {
        "findings_requested": len(targets),
        "findings_with_rows": len(ordered),
        "findings_with_purchase_order": sum(1 for r in ordered if r["has_purchase_order"]),
        "findings_with_weekly_clusters": sum(1 for r in ordered if r["weekly_cluster_count"]),
        "findings_worth_triage": sum(1 for r in ordered if r["split_worth_triage"]),
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": SCHEMA,
        "guardrail": GUARDRAIL,
        "split_guardrail": SPLIT_GUARDRAIL,
        "coverage": coverage,
        "findings": ordered,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return coverage


def _no_clusters() -> dict:
    """Un hallazgo sin grupo semanal no tiene forma que describir.

    Se declara vacío en vez de omitirse: la app distingue «no aplica» de «no se
    calculó» sólo si el campo existe.
    """
    return {
        "weekly_cluster_count": 0,
        "split_shape": SPLIT_UNDETERMINED,
        "split_worth_triage": False,
        "weekly_clusters": [],
    }


def _split_by_finding(clusters: pd.DataFrame) -> dict:
    """Clasifica cada grupo semanal del hallazgo y lo resume.

    Los grupos se publican ordenados por monto, porque la materialidad vive ahí:
    un grupo de $400 millones importa antes que uno de $200 mil. La forma que
    resume el hallazgo es la del grupo mayor, pero basta que cualquiera de ellos
    merezca revisión para que el hallazgo la merezca.
    """
    if clusters is None or clusters.empty:
        return {}

    out: dict[str, dict] = {}
    for row in clusters.where(clusters.notna(), None).to_dict("records"):
        fid = str(row.get("finding_id") or "")
        if not fid:
            continue
        documents = int(row.get("documents") or 0)
        shape = classify_split_shape(
            documents,
            int(row.get("distinct_orders") or 0),
            int(row.get("rows_with_order") or 0),
        )
        entry = {
            "item": str(row.get("item") or ""),
            "week_start": str(row.get("week_start") or ""),
            "documents": documents,
            "cluster_total": float(row.get("cluster_total") or 0.0),
            "max_document_amount": float(row.get("max_document_amount") or 0.0),
            "amount_cv": round(float(row.get("cv") or 0.0), 6),
            "rows_with_order": int(row.get("rows_with_order") or 0),
            "distinct_orders": int(row.get("distinct_orders") or 0),
            "order_examples": [str(x) for x in _as_list(row.get("order_examples")) if x],
            **shape,
        }
        bucket = out.setdefault(fid, {"weekly_cluster_count": int(row.get("cluster_count") or 0),
                                      "weekly_clusters": []})
        bucket["weekly_clusters"].append(entry)

    for fid, bucket in out.items():
        top = bucket["weekly_clusters"][0]
        bucket["split_shape"] = top["split_shape"]
        # Basta que uno de los grupos publicados merezca revisión: el resumen
        # del hallazgo no puede esconder un grupo de órdenes separadas detrás de
        # otro mayor que resultó ser cuotas.
        bucket["split_worth_triage"] = any(c["worth_triage"] for c in bucket["weekly_clusters"])
    return out
