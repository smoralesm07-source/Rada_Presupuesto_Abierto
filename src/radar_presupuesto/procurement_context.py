from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


GUARDRAIL = (
    "La presencia o ausencia de una orden de compra en Presupuesto Abierto no acredita por sí sola "
    "regularidad o irregularidad del proceso de contratación. Debe contrastarse con Mercado Público "
    "y los documentos del procedimiento correspondiente."
)


def build_procurement_context(
    parquet_glob: str,
    findings_json: str = "docs/data/investigative_findings.json",
    output_json: str = "docs/data/procurement_context.json",
    max_orders_per_finding: int = 12,
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
            "schema": "RIGP-PROCUREMENT-CONTEXT-v1",
            "guardrail": GUARDRAIL,
            "coverage": {"findings_requested": 0, "findings_with_rows": 0, "findings_with_purchase_order": 0},
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
    con.close()

    rows = []
    for row in df.where(df.notna(), None).to_dict("records"):
        source_rows = int(row.get("source_rows") or 0)
        with_oc = int(row.get("rows_with_purchase_order") or 0)
        examples = [str(x) for x in (row.get("purchase_order_examples") or []) if x]
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
            }
        )

    by_id = {r["finding_id"]: r for r in rows}
    ordered = [by_id[t["finding_id"]] for t in targets if t["finding_id"] in by_id]
    coverage = {
        "findings_requested": len(targets),
        "findings_with_rows": len(ordered),
        "findings_with_purchase_order": sum(1 for r in ordered if r["has_purchase_order"]),
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": "RIGP-PROCUREMENT-CONTEXT-v1",
        "guardrail": GUARDRAIL,
        "coverage": coverage,
        "findings": ordered,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return coverage
