from __future__ import annotations

import json
from pathlib import Path

import duckdb


def build_sii_document_candidates(
    parquet_glob: str,
    output: str = "data/interop/sii_document_candidates_latest.parquet",
    metadata_output: str = "docs/data/sii_document_candidates_status.json",
) -> dict:
    """Export one recent document candidate per resolved provider for Radar SII.

    This is deliberately a candidate feed, not an SII verification result. The
    downstream Radar SII bridge converts supported document types to the official
    CMSP format and the SII response remains the sole authority for document
    authorization/timbraje status.
    """
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta_path = Path(metadata_output)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    safe_glob = parquet_glob.replace("'", "''")
    safe_out = str(out).replace("'", "''")

    sql = f"""
    COPY (
      WITH candidates AS (
        SELECT
          entity_id,
          rut_beneficiario AS rut,
          nombre_beneficiario AS provider_name,
          tipo_documento,
          coalesce(nullif(trim(cast(numero_documento AS varchar)), ''), nullif(trim(cast(folio AS varchar)), '')) AS numero_documento,
          cast(fecha_documento AS date) AS fecha_documento,
          transaction_id,
          transaction_fingerprint,
          periodo,
          mes,
          source_file,
          source_row_number,
          row_number() OVER (
            PARTITION BY entity_id
            ORDER BY cast(fecha_documento AS date) DESC NULLS LAST,
                     periodo DESC NULLS LAST,
                     mes DESC NULLS LAST,
                     transaction_id DESC
          ) AS rn
        FROM read_parquet('{safe_glob}')
        WHERE entity_id IS NOT NULL
          AND coalesce(is_provider, false) = true
          AND coalesce(is_intra_state, false) = false
          AND coalesce(is_person, false) = false
          AND fecha_documento IS NOT NULL
          AND nullif(trim(cast(tipo_documento AS varchar)), '') IS NOT NULL
          AND coalesce(
                nullif(trim(cast(numero_documento AS varchar)), ''),
                nullif(trim(cast(folio AS varchar)), '')
              ) IS NOT NULL
      )
      SELECT
        entity_id,
        rut,
        provider_name,
        tipo_documento,
        numero_documento,
        fecha_documento,
        transaction_id,
        transaction_fingerprint,
        periodo,
        mes,
        source_file,
        source_row_number,
        'PRESUPUESTO_ABIERTO' AS candidate_source,
        'SPECIFIC_DOCUMENT_VERIFICATION_CANDIDATE' AS observation_intent
      FROM candidates
      WHERE rn = 1
      ORDER BY fecha_documento DESC, entity_id
    ) TO '{safe_out}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    con.execute(sql)

    stats = con.execute(
        f"""
        SELECT
          count(*)::BIGINT AS rows,
          count(DISTINCT entity_id)::BIGINT AS entities,
          min(fecha_documento)::DATE AS min_document_date,
          max(fecha_documento)::DATE AS max_document_date,
          count(DISTINCT tipo_documento)::BIGINT AS document_type_labels
        FROM read_parquet('{safe_out}')
        """
    ).fetchone()

    result = {
        "status": "OK",
        "schema": "PRESUPUESTO_ABIERTO_SII_DOCUMENT_CANDIDATES_V1",
        "output": str(out),
        "rows": int(stats[0] or 0),
        "entities": int(stats[1] or 0),
        "min_document_date": str(stats[2]) if stats[2] else None,
        "max_document_date": str(stats[3]) if stats[3] else None,
        "document_type_labels": int(stats[4] or 0),
        "semantic": "CANDIDATES_ONLY_NOT_SII_AUTHORIZATION",
        "next_stage": "RADAR_SII_CMSP_BRIDGE",
        "guardrails": [
            "one_latest_observed_spend_document_per_resolved_provider",
            "provider_only",
            "exclude_intra_state",
            "exclude_natural_person_flag",
            "SII_response_is_authority",
        ],
    }
    meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
