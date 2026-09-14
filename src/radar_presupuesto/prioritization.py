from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

# Anclaje de la escala de rareza: un patrón que aparece en 1 de cada 100 proveedores
# del mismo grupo de pares satura el componente. Mover este número cambia el ranking.
RARITY_SATURATION = 100.0

# Anclaje de la materialidad relativa: 100 veces la mediana de pares satura el tramo
# de magnitud. Reemplaza los tramos absolutos en CLP, que premiaban al proveedor
# grande por ser grande.
MATERIALITY_SATURATION = 100.0


def prioritize_signals(
    parquet_glob: str,
    signals_path: str = "data/signals/risk_signals.parquet",
    cgr_links_path: str = "data/evidence/cgr_evidence_links.parquet",
    peer_context_path: str = "data/processed/provider_peer_context.parquet",
    output_parquet: str = "data/signals/prioritized_signals.parquet",
    output_json: str = "docs/data/investigation_queue.json",
    top_n: int = 5000,
    min_peer_providers: int = 5,
) -> dict:
    """Build an explainable investigation queue; score is priority, not AML risk.

    La rareza y la materialidad se miden contra el grupo de pares (mismo organismo,
    año, subtítulo e ítem) cuando ese contexto existe. Si el grupo no alcanza el
    mínimo de pares comparables, la fila lo declara en `scoring_basis` y cae al
    prior por tipo de señal, en vez de simular una medición que no se pudo hacer.
    """
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
                   max(cgr_finding_count) cgr_finding_count,
                   max(CASE match_grade WHEN 'RUT_EXACT' THEN 3 WHEN 'NAME_EXACT' THEN 2 ELSE 1 END) cgr_identity_rank
            FROM cgr WHERE local_entity_type='PROVIDER' GROUP BY 1
        """)
        con.execute("""
            CREATE OR REPLACE TEMP VIEW cgr_org AS
            SELECT local_entity_id organization_id,count(*) cgr_match_count,
                   max(confidence) cgr_max_confidence,
                   max(try_cast(cgr_max_aml_score AS DOUBLE)) cgr_max_aml_score,
                   max(cgr_finding_count) cgr_finding_count,
                   max(CASE match_grade WHEN 'RUT_EXACT' THEN 3 WHEN 'NAME_EXACT' THEN 2 ELSE 1 END) cgr_identity_rank
            FROM cgr WHERE local_entity_type='ORGANIZATION' GROUP BY 1
        """)
    else:
        con.execute("CREATE OR REPLACE TEMP VIEW cgr_provider AS SELECT NULL::VARCHAR provider_id,0 cgr_match_count,0.0 cgr_max_confidence,NULL::DOUBLE cgr_max_aml_score,0 cgr_finding_count,0 cgr_identity_rank WHERE FALSE")
        con.execute("CREATE OR REPLACE TEMP VIEW cgr_org AS SELECT NULL::VARCHAR organization_id,0 cgr_match_count,0.0 cgr_max_confidence,NULL::DOUBLE cgr_max_aml_score,0 cgr_finding_count,0 cgr_identity_rank WHERE FALSE")

    peer_context_available = bool(peer_context_path) and Path(peer_context_path).exists()
    if peer_context_available:
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW peer_ctx AS
            SELECT peer_group_id,organization_id,provider_id,
                   try_cast(periodo AS BIGINT) periodo,
                   try_cast(peer_provider_count AS BIGINT) peer_provider_count,
                   try_cast(peer_percentile AS DOUBLE) peer_percentile,
                   try_cast(amount_to_peer_median_ratio AS DOUBLE) amount_to_peer_median_ratio,
                   peer_position
            FROM read_parquet('{peer_context_path}')
            WHERE coalesce(peer_group_id,'')<>''
        """)
    else:
        con.execute("""
            CREATE OR REPLACE TEMP VIEW peer_ctx AS
            SELECT NULL::VARCHAR peer_group_id,NULL::VARCHAR organization_id,NULL::VARCHAR provider_id,
                   NULL::BIGINT periodo,NULL::BIGINT peer_provider_count,NULL::DOUBLE peer_percentile,
                   NULL::DOUBLE amount_to_peer_median_ratio,NULL::VARCHAR peer_position
            WHERE FALSE
        """)

    # Prevalencia empírica: cuántos proveedores del grupo de pares cargan esta señal,
    # sobre el total de proveedores del grupo -- los limpios incluidos. Ese denominador
    # es lo que hace que la rareza signifique algo.
    con.execute("""
        CREATE OR REPLACE TEMP VIEW signal_peer AS
        SELECT s.signal_type,s.provider_id,p.peer_group_id,p.peer_provider_count
        FROM sig s
        JOIN peer_ctx p
          ON s.organization_id=p.organization_id
         AND s.provider_id=p.provider_id
         AND try_cast(s.periodo AS BIGINT)=p.periodo
    """)
    con.execute("""
        CREATE OR REPLACE TEMP VIEW peer_prevalence AS
        SELECT peer_group_id,signal_type,
               count(DISTINCT provider_id) peer_flagged_providers,
               max(peer_provider_count) peer_group_size,
               least(1.0,count(DISTINCT provider_id)::DOUBLE/nullif(max(peer_provider_count),0)) peer_signal_prevalence
        FROM signal_peer GROUP BY 1,2
    """)

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
                   pc.peer_group_id,pc.peer_provider_count,pc.peer_percentile,
                   pc.amount_to_peer_median_ratio,pc.peer_position,
                   pv.peer_signal_prevalence,pv.peer_flagged_providers,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_match_count,0) ELSE greatest(coalesce(cp.cgr_match_count,0),coalesce(co.cgr_match_count,0)) END cgr_match_count,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_max_confidence,0) ELSE greatest(coalesce(cp.cgr_max_confidence,0),coalesce(co.cgr_max_confidence,0)) END cgr_max_confidence,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_max_aml_score,0) ELSE greatest(coalesce(cp.cgr_max_aml_score,0),coalesce(co.cgr_max_aml_score,0)) END cgr_max_aml_score,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_finding_count,0) ELSE greatest(coalesce(cp.cgr_finding_count,0),coalesce(co.cgr_finding_count,0)) END cgr_finding_count,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_identity_rank,0) ELSE greatest(coalesce(cp.cgr_identity_rank,0),coalesce(co.cgr_identity_rank,0)) END cgr_identity_rank
            FROM sig s
            LEFT JOIN tx_context t USING(transaction_id)
            LEFT JOIN provider_signal_stats ps USING(provider_id)
            LEFT JOIN org_signal_stats os USING(organization_id)
            LEFT JOIN cgr_provider cp USING(provider_id)
            LEFT JOIN cgr_org co USING(organization_id)
            LEFT JOIN peer_ctx pc
              ON s.organization_id=pc.organization_id
             AND s.provider_id=pc.provider_id
             AND try_cast(s.periodo AS BIGINT)=pc.periodo
            LEFT JOIN peer_prevalence pv
              ON pv.peer_group_id=pc.peer_group_id
             AND pv.signal_type=s.signal_type
          ), based AS (
            SELECT e.*,
              CASE WHEN peer_group_id IS NOT NULL
                    AND coalesce(peer_provider_count,0)>={int(min_peer_providers)}
                    AND coalesce(peer_signal_prevalence,0)>0
                   THEN 'PARES' ELSE 'PRIOR_POR_TIPO' END scoring_basis
            FROM e
          ), components AS (
            SELECT based.*,
              CASE severity WHEN 'HIGH' THEN 30 WHEN 'MEDIUM' THEN 20 ELSE 10 END severity_component,
              -- Rareza empírica -ln(prevalencia) dentro del grupo de pares. Sustituye los
              -- puntos fijos por tipo de señal: un patrón frecuente en su propio mercado
              -- deja de valer lo mismo que uno excepcional.
              CASE WHEN scoring_basis='PARES'
                   THEN cast(round(15.0*least(1.0,(-ln(peer_signal_prevalence))/ln({RARITY_SATURATION}))) AS INTEGER)
                   ELSE CASE signal_type
                     WHEN 'AMOUNT_OUTLIER' THEN 15
                     WHEN 'PROVIDER_CONCENTRATION' THEN 15
                     WHEN 'NEW_TO_SERIES_HIGH_SPEND' THEN 15
                     WHEN 'POTENTIAL_FRAGMENTATION' THEN 12
                     WHEN 'EXACT_DUPLICATE_CANDIDATE' THEN 10
                     WHEN 'PAYMENT_DELAY_OUTLIER' THEN 10
                     WHEN 'YEAR_END_SPIKE' THEN 8
                     ELSE 6 END
              END rarity_component,
              CASE WHEN provider_signal_types>=3 THEN 20 WHEN provider_signal_types=2 THEN 12 ELSE 0 END
                + CASE WHEN organization_signal_types>=4 THEN 10 WHEN organization_signal_types>=2 THEN 5 ELSE 0 END cooccurrence_component,
              -- El peso ahora depende del grado de identidad del enlace, no de un umbral
              -- de confianza que un match por nombre podía alcanzar. Un RUT validado
              -- acredita que es la misma entidad; un nombre parecido es una hipótesis
              -- sobre dos cadenas de texto y pesa casi nada. El techo de 7 no cambia:
              -- la CGR nunca debe dominar el ranking.
              CASE WHEN coalesce(cgr_match_count,0)=0 THEN 0
                   WHEN cgr_identity_rank>=3 THEN 5
                   WHEN cgr_identity_rank=2 THEN 2
                   ELSE 1 END
                -- El puntaje AML de la CGR sólo suma cuando sabemos que es la misma
                -- entidad; si no, estaríamos ponderando un hallazgo ajeno.
                + CASE WHEN cgr_identity_rank>=3 AND coalesce(cgr_max_aml_score,0)>=70 THEN 2 ELSE 0 END external_evidence_component,
              CASE WHEN has_purchase_order OR has_bip THEN 5 ELSE 0 END actionability_component,
              -- Materialidad relativa a la mediana del grupo de pares, más la posición
              -- dentro del grupo. Los tramos absolutos en CLP quedan sólo como prior
              -- cuando no hay pares suficientes para comparar.
              CASE WHEN scoring_basis='PARES' THEN
                     CASE WHEN coalesce(amount_to_peer_median_ratio,0)>1
                          THEN cast(round(7.0*least(1.0,ln(amount_to_peer_median_ratio)/ln({MATERIALITY_SATURATION}))) AS INTEGER)
                          ELSE 0 END
                     + CASE WHEN coalesce(peer_percentile,0)>=0.99 THEN 3
                            WHEN coalesce(peer_percentile,0)>=0.90 THEN 2
                            WHEN coalesce(peer_percentile,0)>=0.75 THEN 1 ELSE 0 END
                   ELSE CASE WHEN coalesce(transaction_amount,0)>=1000000000 THEN 10
                             WHEN coalesce(transaction_amount,0)>=100000000 THEN 7
                             WHEN coalesce(transaction_amount,0)>=10000000 THEN 4 ELSE 0 END
              END relative_materiality_component
            FROM based
          ), scored AS (
            SELECT *,least(100,severity_component+rarity_component+cooccurrence_component+
                external_evidence_component+actionability_component+relative_materiality_component) investigation_priority_score
            FROM components
          )
          SELECT *,
             CASE WHEN investigation_priority_score>=70 THEN 'P1'
                  WHEN investigation_priority_score>=50 THEN 'P2' ELSE 'P3' END priority_tier,
             concat_ws(' | ',
               'severidad='||cast(severity_component AS VARCHAR),
               CASE WHEN scoring_basis='PARES'
                    THEN 'rareza='||cast(rarity_component AS VARCHAR)||' (la señal aparece en '
                         ||cast(peer_flagged_providers AS VARCHAR)||' de '||cast(peer_provider_count AS VARCHAR)
                         ||' proveedores del grupo '||peer_group_id||')'
                    ELSE 'rareza='||cast(rarity_component AS VARCHAR)||' (prior por tipo: sin pares suficientes para medirla)' END,
               'coocurrencia='||cast(cooccurrence_component AS VARCHAR),
               'contexto_CGR_candidato='||cast(external_evidence_component AS VARCHAR),
               'accionabilidad='||cast(actionability_component AS VARCHAR),
               CASE WHEN scoring_basis='PARES'
                    THEN 'materialidad_relativa='||cast(relative_materiality_component AS VARCHAR)||' ('
                         ||cast(round(coalesce(amount_to_peer_median_ratio,0),1) AS VARCHAR)
                         ||'x la mediana del grupo, percentil '
                         ||cast(cast(round(coalesce(peer_percentile,0)*100) AS INTEGER) AS VARCHAR)||')'
                    ELSE 'materialidad_absoluta='||cast(relative_materiality_component AS VARCHAR)||' (sin grupo de pares comparable)' END
             ) priority_explanation
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
    bases = dict(con.execute(f"SELECT scoring_basis,count(*) FROM read_parquet('{out.as_posix()}') GROUP BY 1").fetchall())
    total = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    con.close()

    records = df.where(df.notna(), None).to_dict("records")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "methodology": (
            "Score 0-100 de prioridad investigativa explicable; combina severidad, rareza empírica del patrón "
            "dentro de su grupo de pares, coocurrencia de señales, contexto externo CGR candidato de peso limitado, "
            "accionabilidad documental y materialidad relativa a la mediana de pares. "
            "No es un score de culpabilidad ni de lavado de activos."
        ),
        "peer_scoring_policy": (
            "El grupo de pares es organismo, año, subtítulo e ítem. La rareza es -ln(prevalencia) de la señal "
            f"entre los proveedores del grupo, incluidos los que no tienen señal alguna; satura en 1 de cada {int(RARITY_SATURATION)}. "
            f"Cuando el grupo no alcanza {int(min_peer_providers)} proveedores comparables, la fila declara "
            "scoring_basis='PRIOR_POR_TIPO' y vuelve al prior por tipo de señal y a los tramos absolutos en CLP, "
            "en vez de publicar una comparación que no se pudo hacer."
        ),
        "external_evidence_policy": (
            "El aporte de la CGR depende del grado de identidad del enlace: un RUT validado acredita "
            "que es la misma entidad y suma hasta 7 puntos; un nombre exacto suma 2 y uno aproximado 1. "
            "El puntaje AML de la CGR sólo pondera sobre enlaces con RUT. Todo enlace permanece CANDIDATE."
        ),
        "peer_context_available": peer_context_available,
        "total_signals": int(total),
        "priority_tiers": tiers,
        "scoring_basis": bases,
        "queue": records,
    }
    q = Path(output_json)
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "path": str(out),
        "signals": int(total),
        "priority_tiers": tiers,
        "scoring_basis": bases,
        "peer_context_available": peer_context_available,
    }
