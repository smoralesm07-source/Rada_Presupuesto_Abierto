from __future__ import annotations

"""Facts-derived context for each service–provider–year relation.

Two things the analyst could not see before live here.

The first is **opacity**. Roughly a fifth of the counterparties in the source
arrive pseudonymised (the payer publishes a SHA1 instead of a RUT), and that is
concentrated in payments to natural persons. A relation built on opaque
identities is not low risk — it is unmeasurable, and the interface has to say so
instead of silently scoring it like any other.

The second is **documentary traceability**: whether the payments in a relation
carry a purchase order at all. Without one there is no procurement process to
pull, which changes what an analyst can realistically ask for.
"""

from pathlib import Path

import duckdb
import pandas as pd

OPACITY_LABEL = {
    "TRAZABLE": "Contraparte identificada con RUT validado.",
    "PARCIAL": "Parte de la contraparte llega pseudonimizada por la fuente.",
    "OPACA": "La mayor parte de la contraparte llega pseudonimizada; la identidad no es verificable con esta fuente.",
}

GUARDRAIL = (
    "La opacidad describe un límite de la fuente, no una conducta. Un receptor "
    "pseudonimizado no es más sospechoso: es menos verificable, y eso cambia qué "
    "puede afirmarse a partir del dato."
)


def build_relation_context(parquet_glob: str) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            WITH base AS (
              SELECT organization_id,
                     coalesce(provider_id,'') AS provider_id,
                     periodo,
                     try_cast(monto_devengado AS DOUBLE) AS amount,
                     coalesce(beneficiario_id_type,'') AS id_type,
                     coalesce(is_person, FALSE) AS is_person,
                     coalesce(is_honorarium, FALSE) AS is_honorarium,
                     coalesce(nullif(trim(orden_compra),''), '') AS oc,
                     coalesce(nullif(nombre_area,''), nullif(nombre_capitulo,''), nombre_partida) AS organization_name,
                     nombre_beneficiario AS counterparty_name
              FROM read_parquet('{parquet_glob}', union_by_name=true)
              WHERE coalesce(is_aggregated, FALSE) = FALSE
                AND try_cast(monto_devengado AS DOUBLE) > 0
            )
            SELECT organization_id,
                   provider_id,
                   periodo,
                   any_value(organization_name) AS organization_name,
                   any_value(counterparty_name) AS counterparty_name,
                   sum(amount) AS relation_amount,
                   count(*) AS tx_count,
                   sum(CASE WHEN id_type = 'HASH_SHA1' THEN amount ELSE 0 END)
                     / nullif(sum(amount), 0) AS opaque_amount_share,
                   sum(CASE WHEN is_person THEN amount ELSE 0 END)
                     / nullif(sum(amount), 0) AS person_amount_share,
                   sum(CASE WHEN is_honorarium THEN amount ELSE 0 END)
                     / nullif(sum(amount), 0) AS honorarium_amount_share,
                   sum(CASE WHEN oc <> '' THEN amount ELSE 0 END)
                     / nullif(sum(amount), 0) AS purchase_order_amount_share,
                   count(DISTINCT nullif(oc,'')) AS distinct_purchase_orders
            FROM base
            GROUP BY organization_id, provider_id, periodo
            """
        ).df()
    finally:
        con.close()


def classify_opacity(share: float | None) -> str:
    value = float(share or 0)
    if value >= 0.5:
        return "OPACA"
    if value > 0.0:
        return "PARCIAL"
    return "TRAZABLE"


def relation_patterns(row: pd.Series, min_amount: float = 20_000_000) -> list[str]:
    """Context flags that behave like patterns for the typology layer."""
    patterns: list[str] = []
    amount = float(row.get("relation_amount") or 0)
    if classify_opacity(row.get("opaque_amount_share")) == "OPACA":
        patterns.append("OPAQUE_COUNTERPARTY")
    if float(row.get("honorarium_amount_share") or 0) >= 0.5 and amount >= min_amount:
        patterns.append("HONORARIUM_CONCENTRATION")
    if float(row.get("person_amount_share") or 0) >= 0.5 and amount >= min_amount:
        patterns.append("PERSON_RECIPIENT")
    if float(row.get("purchase_order_amount_share") or 0) < 0.05 and amount >= min_amount:
        patterns.append("NO_PURCHASE_ORDER_TRAIL")
    return patterns


def build_opacity_index(parquet_glob: str, output_json: str | Path | None = None) -> dict:
    """Publish how much of each body's spend is simply not verifiable."""
    context = build_relation_context(parquet_glob)
    if context.empty:
        payload = {
            "schema": "RIGP-OPACITY-INDEX-v1",
            "guardrail": GUARDRAIL,
            "labels": OPACITY_LABEL,
            "overall": {},
            "services": [],
        }
    else:
        context["opaque_amount"] = context["relation_amount"] * context[
            "opaque_amount_share"
        ].fillna(0)
        total = float(context["relation_amount"].sum())
        opaque = float(context["opaque_amount"].sum())
        by_service = (
            context.groupby(["organization_id"])
            .agg(
                organization_name=("organization_name", "first"),
                relation_amount=("relation_amount", "sum"),
                opaque_amount=("opaque_amount", "sum"),
                relations=("provider_id", "count"),
            )
            .reset_index()
        )
        by_service["opaque_share"] = (
            by_service["opaque_amount"] / by_service["relation_amount"].replace(0, pd.NA)
        ).fillna(0)
        by_service["opacity_level"] = by_service["opaque_share"].map(classify_opacity)
        by_service = by_service.sort_values("opaque_amount", ascending=False)
        payload = {
            "schema": "RIGP-OPACITY-INDEX-v1",
            "guardrail": GUARDRAIL,
            "labels": OPACITY_LABEL,
            "overall": {
                "relation_amount": total,
                "opaque_amount": opaque,
                "opaque_share": round(opaque / total, 6) if total else 0.0,
                "relations": int(len(context)),
            },
            "services": [
                {
                    "organization_id": str(row.organization_id),
                    "organization_name": str(row.organization_name or row.organization_id),
                    "relation_amount": float(row.relation_amount),
                    "opaque_amount": float(row.opaque_amount),
                    "opaque_share": round(float(row.opaque_share), 6),
                    "opacity_level": str(row.opacity_level),
                    "relations": int(row.relations),
                }
                for row in by_service.head(500).itertuples()
            ],
        }
    if output_json:
        out = Path(output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        import json

        out.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    return payload
