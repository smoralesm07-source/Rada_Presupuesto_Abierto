from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb


GUARDRAIL = (
    "Un hallazgo RIGP prioriza revisión documental y OSINT. No acredita irregularidad, "
    "delito funcionario, fraude, corrupción, lavado de activos ni responsabilidad de una entidad o persona."
)


LEGAL_REVIEW = {
    "INTEGRIDAD_DOCUMENTAL_PAGOS": [
        "Revisar si la reiteración documental corresponde a hitos contractuales legítimos o a una duplicidad material.",
        "Verificar órdenes de compra, recepción conforme, facturas, notas de crédito y secuencia de pagos antes de escalar.",
        "Sólo si aparecen pagos improcedentes, simulación u otros antecedentes independientes corresponde evaluar relevancia jurídica o penal.",
    ],
    "COMPETENCIA_ADJUDICACION": [
        "Revisar competencia, modalidad de contratación, adjudicaciones, trato directo, bases y evolución del proveedor frente a sus pares.",
        "Buscar vínculos societarios, personales o funcionales entre proveedor y decisores únicamente con fuentes trazables.",
        "Una eventual hipótesis de conflicto de interés, trato preferente o delito funcionario requiere evidencia adicional; no se infiere del patrón de gasto.",
    ],
    "CONVERGENCIA_MULTIFACTOR": [
        "Reconstruir la secuencia completa del vínculo servicio–proveedor y separar hechos confirmados de señales estadísticas.",
        "Contrastar contratación, ejecución, pagos, antecedentes societarios y evidencia externa candidata antes de formular una hipótesis.",
        "La convergencia aumenta prioridad de revisión, no probabilidad de delito.",
    ],
    "CONCENTRACION_DEPENDENCIA": [
        "Comparar concentración con años previos, categoría de compra y estructura de mercado.",
        "Descartar monopolios técnicos, convenios marco, concesiones, contratos de largo plazo y proyectos de gran escala.",
        "Si la concentración coexiste con vínculos personales, intervención indebida u otras evidencias independientes, evaluar una revisión de integridad reforzada.",
    ],
    "IRRUPCION_CAMBIO_ESCALA": [
        "Confirmar si el proveedor es nuevo sólo en la serie observada o efectivamente nuevo en el mercado/registro pertinente.",
        "Revisar adjudicación inicial, crecimiento interanual, compradores públicos y capacidad económica observable.",
        "Un cambio de escala no implica irregularidad; sirve para decidir dónde profundizar.",
    ],
    "EJECUCION_CONTRACTUAL": [
        "Revisar hitos de contrato, recepción conforme, modificaciones, controversias, notas de crédito y condiciones de pago.",
        "Comparar plazos y comportamiento con contratos y proveedores equivalentes del mismo servicio.",
        "La anomalía temporal o de pago es una pista de gestión contractual, no una conclusión jurídica.",
    ],
    "EJECUCION_PRESUPUESTARIA": [
        "Comparar el patrón con estacionalidad histórica, cierre presupuestario, programas y calendario de ejecución.",
        "Identificar qué proveedores y documentos explican la concentración temporal.",
        "El gasto de fin de año requiere contexto presupuestario antes de interpretarse como hallazgo de integridad.",
    ],
    "PATRON_ATIPICO": [
        "Revisar los documentos soporte y el contexto económico de la relación antes de escalar.",
        "Comparar con historia y pares para descartar explicaciones operativas normales.",
    ],
}


def _split_pipe(value: object) -> list[str]:
    if value is None:
        return []
    return [x for x in str(value).split("|") if x]


def _decorate(record: dict) -> dict:
    out = dict(record)
    if "signal_types" in out:
        out["signal_types"] = _split_pipe(out["signal_types"])
    if "signal_families" in out:
        out["signal_families"] = _split_pipe(out["signal_families"])
    if "service_names" in out:
        out["service_names"] = _split_pipe(out["service_names"])
    family = out.get("finding_family")
    if family:
        out["review_steps"] = LEGAL_REVIEW.get(str(family), LEGAL_REVIEW["PATRON_ATIPICO"])
    out["guardrail"] = GUARDRAIL
    return out


def build_investigative_findings(
    prioritized_path: str = "data/signals/prioritized_signals.parquet",
    output_parquet: str = "data/signals/investigative_findings.parquet",
    output_json: str = "docs/data/investigative_findings.json",
    top_n: int = 250,
) -> dict:
    """Convert technical signals into analyst-facing findings and entity hot-spots.

    The output is deliberately conservative: it ranks where to review first and never
    converts statistical patterns into allegations or criminal classifications.
    """
    source = Path(prioritized_path)
    if not source.exists():
        raise FileNotFoundError(prioritized_path)

    con = duckdb.connect()
    con.execute(f"CREATE OR REPLACE VIEW prioritized AS SELECT * FROM read_parquet('{source.as_posix()}')")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW enriched AS
        SELECT *,
          CASE signal_type
            WHEN 'POTENTIAL_FRAGMENTATION' THEN 'DOCUMENTOS_Y_PAGOS'
            WHEN 'EXACT_DUPLICATE_CANDIDATE' THEN 'DOCUMENTOS_Y_PAGOS'
            WHEN 'PROVIDER_CONCENTRATION' THEN 'COMPETENCIA_Y_CONCENTRACION'
            WHEN 'NEW_TO_SERIES_HIGH_SPEND' THEN 'ENTRADA_Y_CAMBIO_DE_ESCALA'
            WHEN 'AMOUNT_OUTLIER' THEN 'MAGNITUD_ATIPICA'
            WHEN 'PAYMENT_DELAY_OUTLIER' THEN 'EJECUCION_CONTRACTUAL'
            WHEN 'YEAR_END_SPIKE' THEN 'EJECUCION_PRESUPUESTARIA'
            ELSE 'OTRA_SENAL'
          END AS signal_family
        FROM prioritized
        """
    )

    out = Path(output_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
          WITH relation AS (
            SELECT
              organization_id,
              provider_id,
              periodo,
              any_value(organization_name) organization_name,
              any_value(provider_or_recipient_name) provider_name,
              count(*) signal_count,
              count(DISTINCT signal_type) signal_type_count,
              count(DISTINCT signal_family) signal_family_count,
              string_agg(DISTINCT signal_type, '|' ORDER BY signal_type) signal_types,
              string_agg(DISTINCT signal_family, '|' ORDER BY signal_family) signal_families,
              max(investigation_priority_score) max_priority_score,
              sum(CASE WHEN priority_tier='P1' THEN 1 ELSE 0 END) p1_signals,
              sum(CASE WHEN priority_tier='P2' THEN 1 ELSE 0 END) p2_signals,
              max(coalesce(cgr_match_count,0)) cgr_match_count,
              max(coalesce(cgr_max_confidence,0)) cgr_max_confidence,
              max(coalesce(transaction_amount,0)) max_transaction_amount
            FROM enriched
            WHERE coalesce(organization_id,'')<>'' AND coalesce(provider_id,'')<>''
            GROUP BY 1,2,3
          ), classified AS (
            SELECT *,
              CASE
                WHEN signal_family_count>=3 THEN 'CONVERGENCIA_MULTIFACTOR'
                WHEN strpos(signal_types,'POTENTIAL_FRAGMENTATION')>0 AND strpos(signal_types,'EXACT_DUPLICATE_CANDIDATE')>0 THEN 'INTEGRIDAD_DOCUMENTAL_PAGOS'
                WHEN strpos(signal_types,'PROVIDER_CONCENTRATION')>0 AND (strpos(signal_types,'NEW_TO_SERIES_HIGH_SPEND')>0 OR strpos(signal_types,'AMOUNT_OUTLIER')>0) THEN 'COMPETENCIA_ADJUDICACION'
                WHEN strpos(signal_types,'PROVIDER_CONCENTRATION')>0 THEN 'CONCENTRACION_DEPENDENCIA'
                WHEN strpos(signal_types,'NEW_TO_SERIES_HIGH_SPEND')>0 OR strpos(signal_types,'AMOUNT_OUTLIER')>0 THEN 'IRRUPCION_CAMBIO_ESCALA'
                WHEN strpos(signal_types,'PAYMENT_DELAY_OUTLIER')>0 THEN 'EJECUCION_CONTRACTUAL'
                WHEN strpos(signal_types,'YEAR_END_SPIKE')>0 THEN 'EJECUCION_PRESUPUESTARIA'
                ELSE 'PATRON_ATIPICO'
              END finding_family,
              CASE
                WHEN (signal_family_count>=2 AND max_priority_score>=70)
                     OR (signal_family_count>=2 AND cgr_match_count>0)
                     OR signal_type_count>=3 THEN 'ATENCION_INMEDIATA'
                WHEN max_priority_score>=70
                     OR (signal_family_count>=2 AND max_priority_score>=50)
                     OR (cgr_match_count>0 AND max_priority_score>=50) THEN 'REVISION_PRIORITARIA'
                ELSE 'SEGUIMIENTO'
              END attention_level
            FROM relation
          )
          SELECT
            'HAL-RIGP-' || upper(substr(md5(
              coalesce(organization_id,'') || '|' || coalesce(provider_id,'') || '|' || cast(periodo AS VARCHAR)
            ),1,20)) finding_id,
            *,
            CASE finding_family
              WHEN 'INTEGRIDAD_DOCUMENTAL_PAGOS' THEN 'Reiteración documental o de pagos que requiere validación'
              WHEN 'COMPETENCIA_ADJUDICACION' THEN 'Concentración o irrupción relevante en una relación de contratación'
              WHEN 'CONVERGENCIA_MULTIFACTOR' THEN 'Convergencia de patrones independientes en la misma relación'
              WHEN 'CONCENTRACION_DEPENDENCIA' THEN 'Relación con concentración o dependencia significativa'
              WHEN 'IRRUPCION_CAMBIO_ESCALA' THEN 'Proveedor con irrupción o cambio de escala material'
              WHEN 'EJECUCION_CONTRACTUAL' THEN 'Patrón atípico en ejecución o pagos contractuales'
              WHEN 'EJECUCION_PRESUPUESTARIA' THEN 'Patrón temporal de ejecución que requiere contexto'
              ELSE 'Patrón atípico que requiere revisión contextual'
            END finding_title,
            CASE
              WHEN attention_level='ATENCION_INMEDIATA' THEN 'Convergen señales de familias distintas o evidencia externa candidata; conviene reconstruir primero esta relación.'
              WHEN attention_level='REVISION_PRIORITARIA' THEN 'La relación contiene una señal de alta prioridad o combinación suficiente para revisión documental dirigida.'
              ELSE 'Mantener como contexto y revisar si aparecen nuevas señales, mayor materialidad o evidencia externa.'
            END why_review
          FROM classified
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )

    relation_df = con.execute(
        f"""
        SELECT * FROM read_parquet('{out.as_posix()}')
        ORDER BY
          CASE attention_level WHEN 'ATENCION_INMEDIATA' THEN 1 WHEN 'REVISION_PRIORITARIA' THEN 2 ELSE 3 END,
          max_priority_score DESC,
          signal_family_count DESC,
          max_transaction_amount DESC
        LIMIT {int(top_n)}
        """
    ).df()

    service_df = con.execute(
        f"""
        SELECT
          organization_id,
          any_value(organization_name) organization_name,
          count(*) signal_count,
          count(DISTINCT provider_id) FILTER (WHERE coalesce(provider_id,'')<>'') providers_with_signals,
          count(DISTINCT signal_type) signal_type_count,
          count(DISTINCT signal_family) signal_family_count,
          string_agg(DISTINCT signal_type, '|' ORDER BY signal_type) signal_types,
          string_agg(DISTINCT signal_family, '|' ORDER BY signal_family) signal_families,
          sum(CASE WHEN priority_tier='P1' THEN 1 ELSE 0 END) p1_signals,
          sum(CASE WHEN priority_tier='P2' THEN 1 ELSE 0 END) p2_signals,
          max(investigation_priority_score) max_priority_score,
          max(coalesce(cgr_match_count,0)) cgr_match_count,
          max(coalesce(cgr_max_confidence,0)) cgr_max_confidence
        FROM enriched
        WHERE coalesce(organization_id,'')<>''
        GROUP BY 1
        ORDER BY p1_signals DESC, signal_family_count DESC, max_priority_score DESC, signal_count DESC
        LIMIT {int(top_n)}
        """
    ).df()

    provider_df = con.execute(
        f"""
        SELECT
          provider_id,
          any_value(provider_or_recipient_name) provider_name,
          count(*) signal_count,
          count(DISTINCT organization_id) service_count,
          count(DISTINCT periodo) observed_years_with_signals,
          count(DISTINCT signal_type) signal_type_count,
          count(DISTINCT signal_family) signal_family_count,
          string_agg(DISTINCT signal_type, '|' ORDER BY signal_type) signal_types,
          string_agg(DISTINCT signal_family, '|' ORDER BY signal_family) signal_families,
          string_agg(DISTINCT organization_name, '|' ORDER BY organization_name) service_names,
          sum(CASE WHEN priority_tier='P1' THEN 1 ELSE 0 END) p1_signals,
          sum(CASE WHEN priority_tier='P2' THEN 1 ELSE 0 END) p2_signals,
          max(investigation_priority_score) max_priority_score,
          max(coalesce(cgr_match_count,0)) cgr_match_count,
          max(coalesce(cgr_max_confidence,0)) cgr_max_confidence
        FROM enriched
        WHERE coalesce(provider_id,'')<>''
        GROUP BY 1
        ORDER BY p1_signals DESC, service_count DESC, signal_family_count DESC, max_priority_score DESC
        LIMIT {int(top_n)}
        """
    ).df()

    network_df = con.execute(
        f"""
        SELECT
          provider_id,
          any_value(provider_or_recipient_name) provider_name,
          count(DISTINCT organization_id) service_count,
          count(DISTINCT periodo) observed_years_with_signals,
          count(*) signal_count,
          count(DISTINCT signal_type) signal_type_count,
          count(DISTINCT signal_family) signal_family_count,
          string_agg(DISTINCT signal_type, '|' ORDER BY signal_type) signal_types,
          string_agg(DISTINCT signal_family, '|' ORDER BY signal_family) signal_families,
          string_agg(DISTINCT organization_name, '|' ORDER BY organization_name) service_names,
          sum(CASE WHEN priority_tier='P1' THEN 1 ELSE 0 END) p1_signals,
          max(investigation_priority_score) max_priority_score,
          max(coalesce(cgr_match_count,0)) cgr_match_count,
          max(coalesce(cgr_max_confidence,0)) cgr_max_confidence,
          'Red estrella proveedor–servicios para revisión de patrón transversal; no implica coordinación indebida entre actores.' network_interpretation
        FROM enriched
        WHERE coalesce(provider_id,'')<>'' AND coalesce(organization_id,'')<>''
        GROUP BY 1
        HAVING count(DISTINCT organization_id)>=3
           AND count(DISTINCT signal_family)>=2
           AND max(investigation_priority_score)>=50
        ORDER BY p1_signals DESC, service_count DESC, signal_family_count DESC, max_priority_score DESC
        LIMIT {int(top_n)}
        """
    ).df()

    con.close()

    def records(df) -> list[dict]:
        return [_decorate(x) for x in df.where(df.notna(), None).to_dict("records")]

    relation_records = records(relation_df)
    service_records = records(service_df)
    provider_records = records(provider_df)
    network_records = records(network_df)

    attention_counts = {"ATENCION_INMEDIATA": 0, "REVISION_PRIORITARIA": 0, "SEGUIMIENTO": 0}
    family_counts: dict[str, int] = {}
    for row in relation_records:
        level = str(row.get("attention_level") or "SEGUIMIENTO")
        attention_counts[level] = attention_counts.get(level, 0) + 1
        family = str(row.get("finding_family") or "PATRON_ATIPICO")
        family_counts[family] = family_counts.get(family, 0) + 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "methodology_version": "RIGP-FINDINGS-v1",
        "methodology": (
            "Capa intermedia entre señales técnicas y trabajo analítico. Agrupa señales por relación servicio–proveedor–año, "
            "eleva atención sólo por convergencia, prioridad previa y/o evidencia externa candidata, y produce vistas por servicio, proveedor y red estrella."
        ),
        "guardrail": GUARDRAIL,
        "attention_logic": {
            "ATENCION_INMEDIATA": "Dos o más familias con prioridad alta, dos o más familias con evidencia externa candidata, o tres o más tipos de señal en la misma relación.",
            "REVISION_PRIORITARIA": "Una señal P1, o convergencia moderada con prioridad P2/P1, o evidencia externa candidata acompañando prioridad suficiente.",
            "SEGUIMIENTO": "Señal contextual que no reúne aún convergencia suficiente para escalar."
        },
        "counts": {
            "relations_returned": len(relation_records),
            "services_returned": len(service_records),
            "providers_returned": len(provider_records),
            "network_candidates_returned": len(network_records),
            "attention_levels": attention_counts,
            "finding_families": family_counts,
        },
        "relation_findings": relation_records,
        "service_hotspots": service_records,
        "provider_hotspots": provider_records,
        "network_candidates": network_records,
    }

    q = Path(output_json)
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    total_relations = duckdb.connect().execute(
        f"SELECT count(*) FROM read_parquet('{out.as_posix()}')"
    ).fetchone()[0]
    return {
        "path": str(out),
        "json": str(q),
        "relations": int(total_relations),
        "attention_levels_top": attention_counts,
        "service_hotspots": len(service_records),
        "provider_hotspots": len(provider_records),
        "network_candidates": len(network_records),
    }
