from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def prioritize_signals(
    parquet_glob: str,
    signals_path: str = "data/signals/risk_signals.parquet",
    cgr_links_path: str = "data/evidence/cgr_evidence_links.parquet",
    output_parquet: str = "data/signals/prioritized_signals.parquet",
    output_json: str = "docs/data/investigation_queue.json",
    top_n: int = 250,
) -> dict:
    """Build an explainable investigation queue; score is priority, not AML risk."""
    con = duckdb.connect()
    con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)")
    con.execute(f"CREATE OR REPLACE VIEW sig AS SELECT * FROM read_parquet('{signals_path}')")
    con.execute("""
        CREATE OR REPLACE TEMP VIEW tx_context AS
        SELECT transaction_id,
               any_value(coalesce(nullif(nombre_area,''),nullif(nombre_capitulo,''),nombre_partida)) organization_name,
               any_value(nombre_beneficiario) provider_or_recipient_name,
               max(try_cast(monto_devengado AS DOUBLE)) transaction_amount,
               bool_or(coalesce(orden_compra,'')<>'') has_purchase_order,
               bool_or(coalesce(codigo_bip,'')<>'') has_bip,
               any_value(region) region
        FROM facts GROUP BY 1
    """)
    con.execute("""
        CREATE OR REPLACE TEMP VIEW provider_signal_stats AS
        SELECT provider_id,count(*) signal_count,count(DISTINCT signal_type) signal_types
        FROM sig WHERE coalesce(provider_id,'')<>'' AND signal_type<>'YEAR_END_SPIKE' GROUP BY 1
    """)
    con.execute("""
        CREATE OR REPLACE TEMP VIEW org_signal_stats AS
        SELECT organization_id,count(*) signal_count,count(DISTINCT signal_type) signal_types
        FROM sig WHERE coalesce(organization_id,'')<>'' GROUP BY 1
    """)

    if Path(cgr_links_path).exists():
        con.execute(f"CREATE OR REPLACE VIEW cgr AS SELECT * FROM read_parquet('{cgr_links_path}')")
        con.execute("""
            CREATE OR REPLACE TEMP VIEW cgr_provider AS
            SELECT local_entity_id provider_id,count(*) cgr_match_count,
                   max(confidence) cgr_max_confidence,
                   max(try_cast(cgr_max_aml_score AS DOUBLE)) cgr_max_aml_score,
                   max(cgr_finding_count) cgr_finding_count
            FROM cgr WHERE local_entity_type='PROVIDER' GROUP BY 1
        """)
        con.execute("""
            CREATE OR REPLACE TEMP VIEW cgr_org AS
            SELECT local_entity_id organization_id,count(*) cgr_match_count,
                   max(confidence) cgr_max_confidence,
                   max(try_cast(cgr_max_aml_score AS DOUBLE)) cgr_max_aml_score,
                   max(cgr_finding_count) cgr_finding_count
            FROM cgr WHERE local_entity_type='ORGANIZATION' GROUP BY 1
        """)
    else:
        con.execute("CREATE OR REPLACE TEMP VIEW cgr_provider AS SELECT NULL::VARCHAR provider_id,0 cgr_match_count,0.0 cgr_max_confidence,NULL::DOUBLE cgr_max_aml_score,0 cgr_finding_count WHERE FALSE")
        con.execute("CREATE OR REPLACE TEMP VIEW cgr_org AS SELECT NULL::VARCHAR organization_id,0 cgr_match_count,0.0 cgr_max_confidence,NULL::DOUBLE cgr_max_aml_score,0 cgr_finding_count WHERE FALSE")

    out = Path(output_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
          WITH e AS (
            SELECT s.*,t.organization_name,t.provider_or_recipient_name,t.transaction_amount,
                   coalesce(t.has_purchase_order,FALSE) has_purchase_order,
                   coalesce(t.has_bip,FALSE) has_bip,t.region,
                   coalesce(ps.signal_count,0) provider_signal_count,
                   coalesce(ps.signal_types,0) provider_signal_types,
                   coalesce(os.signal_count,0) organization_signal_count,
                   coalesce(os.signal_types,0) organization_signal_types,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_match_count,0) ELSE greatest(coalesce(cp.cgr_match_count,0),coalesce(co.cgr_match_count,0)) END cgr_match_count,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_max_confidence,0) ELSE greatest(coalesce(cp.cgr_max_confidence,0),coalesce(co.cgr_max_confidence,0)) END cgr_max_confidence,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_max_aml_score,0) ELSE greatest(coalesce(cp.cgr_max_aml_score,0),coalesce(co.cgr_max_aml_score,0)) END cgr_max_aml_score,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_finding_count,0) ELSE greatest(coalesce(cp.cgr_finding_count,0),coalesce(co.cgr_finding_count,0)) END cgr_finding_count
            FROM sig s
            LEFT JOIN tx_context t USING(transaction_id)
            LEFT JOIN provider_signal_stats ps USING(provider_id)
            LEFT JOIN org_signal_stats os USING(organization_id)
            LEFT JOIN cgr_provider cp USING(provider_id)
            LEFT JOIN cgr_org co USING(organization_id)
          ), components AS (
            SELECT e.*,
              CASE severity WHEN 'HIGH' THEN 30 WHEN 'MEDIUM' THEN 20 ELSE 10 END severity_component,
              CASE signal_type
                WHEN 'AMOUNT_OUTLIER' THEN 15
                WHEN 'PROVIDER_CONCENTRATION' THEN 15
                WHEN 'NEW_TO_SERIES_HIGH_SPEND' THEN 15
                WHEN 'POTENTIAL_FRAGMENTATION' THEN 12
                WHEN 'EXACT_DUPLICATE_CANDIDATE' THEN 10
                WHEN 'PAYMENT_DELAY_OUTLIER' THEN 10
                WHEN 'YEAR_END_SPIKE' THEN 8
                ELSE 6 END signal_component,
              CASE WHEN provider_signal_types>=3 THEN 20 WHEN provider_signal_types=2 THEN 12 ELSE 0 END
                + CASE WHEN organization_signal_types>=4 THEN 10 WHEN organization_signal_types>=2 THEN 5 ELSE 0 END cooccurrence_component,
              CASE WHEN cgr_max_confidence>=0.88 THEN 15 WHEN cgr_max_confidence>=0.80 THEN 10 ELSE 0 END
                + CASE WHEN cgr_max_aml_score>=70 THEN 5 ELSE 0 END external_evidence_component,
              CASE WHEN has_purchase_order OR has_bip THEN 5 ELSE 0 END actionability_component,
              CASE WHEN coalesce(transaction_amount,0)>=1000000000 THEN 10
                   WHEN coalesce(transaction_amount,0)>=100000000 THEN 7
                   WHEN coalesce(transaction_amount,0)>=10000000 THEN 4 ELSE 0 END materiality_component
            FROM e
          ), scored AS (
            SELECT *,least(100,severity_component+signal_component+cooccurrence_component+
                external_evidence_component+actionability_component+materiality_component) investigation_priority_score
            FROM components
          )
          SELECT *,
             CASE WHEN investigation_priority_score>=70 THEN 'P1'
                  WHEN investigation_priority_score>=50 THEN 'P2' ELSE 'P3' END priority_tier,
             concat_ws(' | ',
               'severidad='||cast(severity_component AS VARCHAR),
               'señal='||cast(signal_component AS VARCHAR),
               'coocurrencia='||cast(cooccurrence_component AS VARCHAR),
               'evidencia_CGR='||cast(external_evidence_component AS VARCHAR),
               'accionabilidad='||cast(actionability_component AS VARCHAR),
               'materialidad='||cast(materiality_component AS VARCHAR)) priority_explanation
          FROM scored
        ) TO '{out.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)
    """)

    df = con.execute(f"""
        SELECT * FROM read_parquet('{out.as_posix()}')
        ORDER BY investigation_priority_score DESC,
                 CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                 coalesce(deviation,0) DESC
        LIMIT {int(top_n)}
    """).df()
    tiers = dict(con.execute(f"SELECT priority_tier,count(*) FROM read_parquet('{out.as_posix()}') GROUP BY 1").fetchall())
    total = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    con.close()

    records = df.where(df.notna(), None).to_dict("records")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "methodology": "Score 0-100 de prioridad investigativa explicable; combina severidad, tipo de patrón, coocurrencia de señales, evidencia externa CGR, accionabilidad documental y materialidad. No es un score de culpabilidad ni de lavado de activos.",
        "total_signals": int(total),
        "priority_tiers": tiers,
        "queue": records,
    }
    q = Path(output_json)
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"path": str(out), "signals": int(total), "priority_tiers": tiers}
