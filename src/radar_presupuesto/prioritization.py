from __future__ import annotations

"""Explainable investigation priority, rebuilt on two independent axes.

The previous version collapsed *how much a pattern deserves a look* and *how
compatible it is with a laundering typology* into a single number, and paid
fixed points per signal type regardless of how common that pattern is. The
result was a queue dominated by large, ordinary payments.

This version scores review priority against an explicit peer group, weights each
pattern by how rare it actually is inside that peer group, and measures
materiality relative to peers rather than in absolute pesos. The LA/FT axis is
computed separately in `typologies.py` and joined downstream, so neither one can
contaminate the other.

`investigation_priority_score` is preserved as an alias of the review axis so
existing dashboards and exports keep working.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .calibration import load_multipliers
from .windows import DEFAULT_WINDOWS, AnalysisWindows

DEFAULT_TOP_N = 5000
PREVALENCE_FLOOR = 0.0005
FAMILY_MIN_SHARE = 0.08

SIGNAL_FAMILY = {
    "POTENTIAL_FRAGMENTATION": "DOCUMENTOS_Y_PAGOS",
    "EXACT_DUPLICATE_CANDIDATE": "DOCUMENTOS_Y_PAGOS",
    "PROVIDER_CONCENTRATION": "COMPETENCIA_Y_CONCENTRACION",
    "NEW_TO_SERIES_HIGH_SPEND": "ENTRADA_Y_CAMBIO_DE_ESCALA",
    "AMOUNT_OUTLIER": "MAGNITUD_ATIPICA",
    "PAYMENT_DELAY_OUTLIER": "EJECUCION_CONTRACTUAL",
    "YEAR_END_SPIKE": "EJECUCION_PRESUPUESTARIA",
}

METHODOLOGY = (
    "Score 0-100 de prioridad de revisión. Combina rareza empírica del patrón dentro de un "
    "grupo de pares explícito, convergencia de familias independientes, materialidad relativa "
    "a los pares, evidencia externa candidata y contexto registral de la contraparte. "
    "No es un score de culpabilidad ni de lavado de activos: la compatibilidad con tipologías "
    "LA/FT se calcula en un eje separado."
)

GUARDRAIL = (
    "La prioridad ordena el trabajo de revisión. No acredita irregularidad, delito funcionario, "
    "fraude, corrupción ni lavado de activos, y no atribuye responsabilidad a ninguna persona o entidad."
)


def _family_case_sql(column: str = "signal_type") -> str:
    whens = " ".join(
        f"WHEN '{signal}' THEN '{family}'" for signal, family in SIGNAL_FAMILY.items()
    )
    return f"CASE {column} {whens} ELSE 'OTRA_SENAL' END"


def _register_peer_context(
    con: duckdb.DuckDBPyConnection, parquet_glob: str, windows: AnalysisWindows
) -> None:
    """Build the peer group every comparison in this module is made against.

    A peer group is a budget line (subtítulo) crossed with the spending scale of
    the public body. Comparing a ministry's fuel purchases against a small
    municipal office's consultancy contracts is what produced false positives
    before; comparing like with like is what fixes them.

    The statistics come from the **whole learning window**, not from what is
    publishable. History no longer supports acting, but it is what says what
    normal looked like — and a baseline built only on recent years compares the
    present against itself.
    """
    con.execute(
        f"""
        CREATE OR REPLACE VIEW facts AS
        SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW provider_facts AS
        SELECT organization_id,
               provider_id,
               periodo,
               coalesce(nullif(subtitulo,''),'NA') AS subtitulo,
               try_cast(monto_devengado AS DOUBLE) AS amount
        FROM facts
        WHERE coalesce(provider_id,'') <> ''
          AND coalesce(is_aggregated, FALSE) = FALSE
          AND try_cast(monto_devengado AS DOUBLE) > 0
          AND """ + windows.sql_learning_filter() + """
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW org_scale AS
        SELECT organization_id,
               periodo,
               sum(amount) AS org_year_amount,
               ntile(5) OVER (PARTITION BY periodo ORDER BY sum(amount)) AS scale_band
        FROM provider_facts
        GROUP BY organization_id, periodo
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW relation_universe AS
        WITH per_subtitulo AS (
          SELECT organization_id, provider_id, periodo, subtitulo,
                 sum(amount) AS amount,
                 row_number() OVER (
                   PARTITION BY organization_id, provider_id, periodo
                   ORDER BY sum(amount) DESC, subtitulo
                 ) AS rn
          FROM provider_facts
          GROUP BY organization_id, provider_id, periodo, subtitulo
        ), dominant AS (
          SELECT organization_id, provider_id, periodo, subtitulo AS dominant_subtitulo
          FROM per_subtitulo WHERE rn = 1
        ), totals AS (
          SELECT organization_id, provider_id, periodo, sum(amount) AS relation_amount
          FROM provider_facts
          GROUP BY organization_id, provider_id, periodo
        )
        SELECT d.organization_id,
               d.provider_id,
               d.periodo,
               d.dominant_subtitulo,
               t.relation_amount,
               s.org_year_amount,
               s.scale_band,
               d.dominant_subtitulo || '|S' || cast(s.scale_band AS VARCHAR) AS peer_group
        FROM dominant d
        JOIN totals t USING (organization_id, provider_id, periodo)
        JOIN org_scale s ON s.organization_id = d.organization_id AND s.periodo = d.periodo
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW org_universe AS
        SELECT organization_id,
               periodo,
               org_year_amount,
               scale_band,
               'ORG|S' || cast(scale_band AS VARCHAR) AS org_peer_group
        FROM org_scale
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW org_peer_stats AS
        SELECT org_peer_group,
               count(*) AS orgs_in_peer,
               median(org_year_amount) AS peer_median_org_amount
        FROM org_universe
        GROUP BY org_peer_group
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW peer_stats AS
        SELECT peer_group,
               count(*) AS relations_in_peer,
               median(relation_amount) AS peer_median_relation_amount
        FROM relation_universe
        GROUP BY peer_group
        """
    )


def _register_rarity(con: duckdb.DuckDBPyConnection) -> None:
    """Prevalence of each pattern inside its peer group, over all relations.

    The denominator is every relation in the peer group, including the clean
    ones. That is what makes the number mean "how unusual is this", instead of
    "how common is this among things we already flagged".
    """
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW signal_relations AS
        SELECT DISTINCT s.signal_type,
               {_family_case_sql('s.signal_type')} AS signal_family,
               s.organization_id,
               coalesce(s.provider_id,'') AS provider_id,
               s.periodo
        FROM sig s
        WHERE coalesce(s.organization_id,'') <> ''
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW rarity AS
        WITH flagged AS (
          SELECT r.peer_group, sr.signal_type, count(DISTINCT
                   sr.organization_id || '|' || sr.provider_id || '|' || cast(sr.periodo AS VARCHAR)
                 ) AS flagged_relations
          FROM signal_relations sr
          JOIN relation_universe r
            ON r.organization_id = sr.organization_id
           AND r.provider_id = sr.provider_id
           AND r.periodo = sr.periodo
          GROUP BY r.peer_group, sr.signal_type
        )
        SELECT f.peer_group,
               f.signal_type,
               f.flagged_relations,
               p.relations_in_peer,
               greatest(
                 cast(f.flagged_relations AS DOUBLE) / nullif(p.relations_in_peer, 0),
                 {PREVALENCE_FLOOR}
               ) AS prevalence
        FROM flagged f
        JOIN peer_stats p USING (peer_group)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW org_rarity AS
        WITH flagged AS (
          SELECT o.org_peer_group, sr.signal_type,
                 count(DISTINCT sr.organization_id || '|' || cast(sr.periodo AS VARCHAR)) AS flagged_orgs
          FROM signal_relations sr
          JOIN org_universe o
            ON o.organization_id = sr.organization_id AND o.periodo = sr.periodo
          GROUP BY o.org_peer_group, sr.signal_type
        )
        SELECT f.org_peer_group,
               f.signal_type,
               f.flagged_orgs,
               p.orgs_in_peer,
               greatest(
                 cast(f.flagged_orgs AS DOUBLE) / nullif(p.orgs_in_peer, 0),
                 {PREVALENCE_FLOOR}
               ) AS prevalence
        FROM flagged f
        JOIN org_peer_stats p USING (org_peer_group)
        """
    )


def _register_external_evidence(con: duckdb.DuckDBPyConnection, cgr_links_path: str) -> None:
    """Candidate CGR evidence, weighted by how the entity was matched.

    A match on a validated RUT is evidence about the same entity. A match on a
    normalised name is a hypothesis about two strings. They must not carry the
    same weight, and before this version they did.
    """
    if not Path(cgr_links_path).exists():
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW cgr_provider AS
            SELECT NULL::VARCHAR provider_id, 0 cgr_match_count, 0.0 cgr_max_confidence,
                   NULL::DOUBLE cgr_max_aml_score, 0 cgr_finding_count, ''::VARCHAR cgr_match_grade
            WHERE FALSE
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW cgr_org AS
            SELECT NULL::VARCHAR organization_id, 0 cgr_match_count, 0.0 cgr_max_confidence,
                   NULL::DOUBLE cgr_max_aml_score, 0 cgr_finding_count, ''::VARCHAR cgr_match_grade
            WHERE FALSE
            """
        )
        return

    con.execute(f"CREATE OR REPLACE VIEW cgr AS SELECT * FROM read_parquet('{cgr_links_path}')")
    columns = {row[1] for row in con.execute("PRAGMA table_info('cgr')").fetchall()}
    grade = "any_value(match_grade)" if "match_grade" in columns else "'NAME_ONLY'"
    for view, entity_type, key in (
        ("cgr_provider", "PROVIDER", "provider_id"),
        ("cgr_org", "ORGANIZATION", "organization_id"),
    ):
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW {view} AS
            SELECT local_entity_id AS {key},
                   count(*) AS cgr_match_count,
                   max(confidence) AS cgr_max_confidence,
                   max(try_cast(cgr_max_aml_score AS DOUBLE)) AS cgr_max_aml_score,
                   max(cgr_finding_count) AS cgr_finding_count,
                   max({grade}) AS cgr_match_grade
            FROM cgr
            WHERE local_entity_type = '{entity_type}'
            GROUP BY local_entity_id
            """
        )


def _register_entity_risk(con: duckdb.DuckDBPyConnection, entity_signals_path: str) -> None:
    if Path(entity_signals_path).exists():
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW entity_risk AS
            SELECT provider_id,
                   count(*) AS entity_signal_count,
                   count(DISTINCT signal_type) AS entity_signal_types,
                   string_agg(DISTINCT signal_type, '|' ORDER BY signal_type) AS entity_signal_list
            FROM read_parquet('{entity_signals_path}')
            WHERE coalesce(provider_id,'') <> ''
            GROUP BY provider_id
            """
        )
    else:
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW entity_risk AS
            SELECT NULL::VARCHAR provider_id, 0 entity_signal_count,
                   0 entity_signal_types, ''::VARCHAR entity_signal_list
            WHERE FALSE
            """
        )


def _select_with_family_quota(rows: list[dict], top_n: int, min_share: float) -> list[dict]:
    """Take the top N without letting one family crowd out every other.

    Ranking purely by score is what made fragmentation and seasonality invisible:
    they are individually lower-scoring, so none of them ever survived the cut,
    and the convergence logic downstream had nothing to converge.
    """
    if len(rows) <= top_n:
        return rows
    families: dict[str, list[dict]] = {}
    for row in rows:
        families.setdefault(str(row.get("signal_family") or "OTRA_SENAL"), []).append(row)
    quota = max(1, int(top_n * min_share))
    selected: list[dict] = []
    seen: set[str] = set()
    for family_rows in families.values():
        for row in family_rows[:quota]:
            key = str(row.get("signal_id"))
            if key not in seen:
                seen.add(key)
                selected.append(row)
    for row in rows:
        if len(selected) >= top_n:
            break
        key = str(row.get("signal_id"))
        if key not in seen:
            seen.add(key)
            selected.append(row)
    selected.sort(
        key=lambda r: (
            -float(r.get("review_priority_score") or 0),
            {"HIGH": 0, "MEDIUM": 1}.get(str(r.get("severity")), 2),
            -float(r.get("deviation") or 0),
        )
    )
    return selected[:top_n]


def prioritize_signals(
    parquet_glob: str,
    signals_path: str = "data/signals/risk_signals.parquet",
    cgr_links_path: str = "data/evidence/cgr_evidence_links.parquet",
    entity_signals_path: str = "data/signals/entity_signals.parquet",
    calibration_path: str = "docs/data/calibration.json",
    output_parquet: str = "data/signals/prioritized_signals.parquet",
    output_json: str = "docs/data/investigation_queue.json",
    top_n: int = DEFAULT_TOP_N,
    family_min_share: float = FAMILY_MIN_SHARE,
    windows: AnalysisWindows | None = None,
) -> dict:
    windows = windows or DEFAULT_WINDOWS
    con = duckdb.connect()
    con.execute(f"CREATE OR REPLACE VIEW sig AS SELECT * FROM read_parquet('{signals_path}')")
    _register_peer_context(con, parquet_glob, windows)
    _register_rarity(con)
    _register_external_evidence(con, cgr_links_path)
    _register_entity_risk(con, entity_signals_path)

    # Lo que el analista cerró y por qué. Sin casos cerrados suficientes esto
    # queda vacío y ningún score se mueve.
    multipliers = load_multipliers(calibration_path)
    con.execute("CREATE OR REPLACE TEMP TABLE calibration(signal_type VARCHAR, multiplier DOUBLE)")
    for signal_type, multiplier in multipliers.items():
        con.execute("INSERT INTO calibration VALUES (?, ?)", [signal_type, float(multiplier)])

    # La fecha de última actividad mide accionabilidad. Un parquet parcial o de
    # una corrida anterior puede no traer las fechas; en ese caso la columna
    # queda nula y la interfaz lo dice, en vez de romper la construcción.
    fact_columns = {row[1] for row in con.execute("PRAGMA table_info('facts')").fetchall()}
    date_parts = [c for c in ("fecha_pago", "fecha_documento") if c in fact_columns]
    activity_expr = (
        f"max(try_cast(coalesce({', '.join(date_parts)}) AS DATE))"
        if date_parts
        else "cast(NULL AS DATE)"
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW relation_activity AS
        SELECT organization_id,
               coalesce(provider_id,'') AS provider_id,
               periodo,
               {activity_expr} AS last_activity
        FROM facts
        WHERE coalesce(is_aggregated, FALSE) = FALSE
        GROUP BY 1,2,3
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW tx_context AS
        SELECT transaction_id,
               any_value(coalesce(nullif(nombre_area,''),nullif(nombre_capitulo,''),nombre_partida)) organization_name,
               any_value(nombre_beneficiario) provider_or_recipient_name,
               max(try_cast(monto_devengado AS DOUBLE)) transaction_amount,
               bool_or(coalesce(orden_compra,'')<>'') has_purchase_order,
               bool_or(coalesce(codigo_bip,'')<>'') has_bip,
               any_value(region) region
        FROM facts GROUP BY 1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW provider_signal_stats AS
        SELECT provider_id,
               count(*) signal_count,
               count(DISTINCT signal_type) signal_types,
               count(DISTINCT {_family_case_sql()}) signal_families
        FROM sig WHERE coalesce(provider_id,'')<>'' AND signal_type<>'YEAR_END_SPIKE' GROUP BY 1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW org_signal_stats AS
        SELECT organization_id,
               count(*) signal_count,
               count(DISTINCT signal_type) signal_types,
               count(DISTINCT {_family_case_sql()}) signal_families
        FROM sig WHERE coalesce(organization_id,'')<>'' GROUP BY 1
        """
    )

    out = Path(output_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
          WITH enriched AS (
            SELECT s.*,
                   {_family_case_sql('s.signal_type')} AS signal_family,
                   t.organization_name, t.provider_or_recipient_name, t.transaction_amount,
                   coalesce(t.has_purchase_order, FALSE) has_purchase_order,
                   coalesce(t.has_bip, FALSE) has_bip, t.region,
                   coalesce(ru.peer_group, ou.org_peer_group, 'NA|S0') AS peer_group,
                   coalesce(ru.relation_amount, ou.org_year_amount) AS relation_amount,
                   coalesce(ps.peer_median_relation_amount, ops.peer_median_org_amount)
                     AS peer_median_relation_amount,
                   coalesce(ps.relations_in_peer, ops.orgs_in_peer) AS relations_in_peer,
                   coalesce(r.prevalence, orr.prevalence, 0.5) AS pattern_prevalence,
                   ra.last_activity,
                   coalesce(pss.signal_count,0) provider_signal_count,
                   coalesce(pss.signal_types,0) provider_signal_types,
                   coalesce(pss.signal_families,0) provider_signal_families,
                   coalesce(oss.signal_count,0) organization_signal_count,
                   coalesce(oss.signal_types,0) organization_signal_types,
                   coalesce(oss.signal_families,0) organization_signal_families,
                   coalesce(er.entity_signal_count,0) entity_signal_count,
                   coalesce(er.entity_signal_types,0) entity_signal_types,
                   coalesce(er.entity_signal_list,'') entity_signal_list,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_match_count,0)
                        ELSE greatest(coalesce(cp.cgr_match_count,0),coalesce(co.cgr_match_count,0)) END cgr_match_count,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_max_confidence,0)
                        ELSE greatest(coalesce(cp.cgr_max_confidence,0),coalesce(co.cgr_max_confidence,0)) END cgr_max_confidence,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_max_aml_score,0)
                        ELSE greatest(coalesce(cp.cgr_max_aml_score,0),coalesce(co.cgr_max_aml_score,0)) END cgr_max_aml_score,
                   CASE WHEN s.signal_type='YEAR_END_SPIKE' THEN coalesce(co.cgr_finding_count,0)
                        ELSE greatest(coalesce(cp.cgr_finding_count,0),coalesce(co.cgr_finding_count,0)) END cgr_finding_count,
                   coalesce(nullif(cp.cgr_match_grade,''), nullif(co.cgr_match_grade,''), 'NONE') cgr_match_grade
            FROM sig s
            LEFT JOIN tx_context t ON t.transaction_id = s.transaction_id
            LEFT JOIN relation_universe ru
              ON ru.organization_id = s.organization_id
             AND ru.provider_id = coalesce(s.provider_id,'')
             AND ru.periodo = s.periodo
            LEFT JOIN peer_stats ps ON ps.peer_group = ru.peer_group
            LEFT JOIN rarity r ON r.peer_group = ru.peer_group AND r.signal_type = s.signal_type
            LEFT JOIN org_universe ou
              ON ou.organization_id = s.organization_id AND ou.periodo = s.periodo
            LEFT JOIN org_peer_stats ops ON ops.org_peer_group = ou.org_peer_group
            LEFT JOIN org_rarity orr
              ON orr.org_peer_group = ou.org_peer_group AND orr.signal_type = s.signal_type
            LEFT JOIN relation_activity ra
              ON ra.organization_id = s.organization_id
             AND ra.provider_id = coalesce(s.provider_id,'')
             AND ra.periodo = s.periodo
            LEFT JOIN provider_signal_stats pss ON pss.provider_id = s.provider_id
            LEFT JOIN org_signal_stats oss ON oss.organization_id = s.organization_id
            LEFT JOIN entity_risk er ON er.provider_id = s.provider_id
            LEFT JOIN cgr_provider cp ON cp.provider_id = s.provider_id
            LEFT JOIN cgr_org co ON co.organization_id = s.organization_id
          ), components AS (
            SELECT e.*,
              -- Rareza: cuánto se aparta el patrón de lo normal en su grupo de pares.
              least(30, round(30 * ln(1.0/pattern_prevalence) / ln(1.0/{PREVALENCE_FLOOR}))) AS rarity_component,
              -- Convergencia: familias independientes que coinciden en la misma contraparte.
              least(25,
                CASE WHEN provider_signal_families>=3 THEN 15
                     WHEN provider_signal_families=2 THEN 9 ELSE 0 END
                + CASE WHEN organization_signal_families>=4 THEN 6
                       WHEN organization_signal_families>=2 THEN 3 ELSE 0 END
                + CASE WHEN entity_signal_types>=2 THEN 4
                       WHEN entity_signal_types=1 THEN 2 ELSE 0 END
              ) AS convergence_component,
              -- Materialidad relativa a los pares, no en pesos absolutos.
              least(20, greatest(0, round(
                10 * ln(greatest(1.0,
                  coalesce(transaction_amount,0) / nullif(peer_median_relation_amount,0)
                )) / ln(50)
                + 10 * ln(greatest(1.0,
                  coalesce(relation_amount,0) / nullif(peer_median_relation_amount,0)
                )) / ln(50)
              ))) AS relative_materiality_component,
              -- Evidencia externa: un RUT validado pesa; una coincidencia de nombre, poco.
              CASE
                WHEN cgr_match_count=0 THEN 0
                WHEN cgr_match_grade='RUT_EXACT' AND cgr_max_confidence>=0.88 THEN 15
                WHEN cgr_match_grade='RUT_EXACT' THEN 11
                WHEN cgr_max_confidence>=0.88 THEN 6
                ELSE 3
              END + CASE WHEN cgr_max_aml_score>=70 AND cgr_match_grade='RUT_EXACT' THEN 3 ELSE 0 END
                AS external_evidence_component,
              -- Contexto registral de la contraparte.
              least(10, entity_signal_count * 3) AS entity_context_component
            FROM enriched e
          ), scored AS (
            SELECT c.*,
              coalesce(cal.multiplier, 1.0) AS calibration_multiplier,
              least(100, c.rarity_component + c.convergence_component + c.relative_materiality_component
                    + c.external_evidence_component + c.entity_context_component)
                AS review_priority_score_raw,
              -- El ajuste es acotado y viaja explicado: nunca mueve el score en silencio.
              least(100, round(
                least(100, c.rarity_component + c.convergence_component + c.relative_materiality_component
                      + c.external_evidence_component + c.entity_context_component)
                * coalesce(cal.multiplier, 1.0)
              )) AS review_priority_score
            FROM components c
            LEFT JOIN calibration cal ON cal.signal_type = c.signal_type
          )
          SELECT *,
             review_priority_score AS investigation_priority_score,
             CASE WHEN try_cast(periodo AS INTEGER) >= {int(windows.action_from_year)} THEN 'ACCION'
                  WHEN try_cast(periodo AS INTEGER) >= {int(windows.learning_from_year)} THEN 'APRENDIZAJE'
                  ELSE 'FUERA_DE_SERIE' END AS analysis_window,
             CASE WHEN review_priority_score>=70 THEN 'P1'
                  WHEN review_priority_score>=50 THEN 'P2' ELSE 'P3' END AS priority_tier,
             concat_ws(' | ',
               'rareza=' || cast(rarity_component AS VARCHAR)
                 || ' (prevalencia ' || cast(round(pattern_prevalence*100, 3) AS VARCHAR) || '% en ' || peer_group || ')',
               'convergencia=' || cast(convergence_component AS VARCHAR),
               'materialidad_relativa=' || cast(relative_materiality_component AS VARCHAR),
               'evidencia_externa=' || cast(external_evidence_component AS VARCHAR)
                 || ' (' || cgr_match_grade || ')',
               'contexto_entidad=' || cast(entity_context_component AS VARCHAR),
               CASE WHEN calibration_multiplier = 1.0 THEN 'calibración=sin ajuste'
                    ELSE 'calibración=x' || cast(round(calibration_multiplier, 2) AS VARCHAR)
                         || ' sobre ' || cast(review_priority_score_raw AS VARCHAR)
               END) AS priority_explanation
          FROM scored
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )

    # Sólo la ventana de acción llega a la bandeja. Lo anterior ya se usó: está
    # dentro de las prevalencias y las medianas contra las que se puntuó esto.
    ranked = con.execute(
        f"""
        SELECT * FROM read_parquet('{out.as_posix()}')
        WHERE analysis_window = 'ACCION'
        ORDER BY review_priority_score DESC,
                 CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                 coalesce(deviation,0) DESC
        LIMIT {int(top_n) * 4}
        """
    ).df()
    tiers = dict(
        con.execute(
            f"""
            SELECT priority_tier, count(*) FROM read_parquet('{out.as_posix()}')
            WHERE analysis_window = 'ACCION' GROUP BY 1
            """
        ).fetchall()
    )
    by_window = dict(
        con.execute(
            f"SELECT analysis_window, count(*) FROM read_parquet('{out.as_posix()}') GROUP BY 1"
        ).fetchall()
    )
    total = con.execute(
        f"SELECT count(*) FROM read_parquet('{out.as_posix()}')"
    ).fetchone()[0]
    actionable_total = int(by_window.get("ACCION", 0))
    peer_groups = con.execute("SELECT count(*) FROM peer_stats").fetchone()[0]
    baseline = con.execute(
        f"""
        SELECT count(DISTINCT periodo) FILTER (
                 WHERE try_cast(periodo AS INTEGER) < {int(windows.action_from_year)}
               ) AS baseline_years,
               count(*) AS baseline_relations
        FROM relation_universe
        """
    ).fetchone()
    con.close()

    candidates = ranked.where(ranked.notna(), None).to_dict("records")
    records = _select_with_family_quota(candidates, int(top_n), float(family_min_share))
    published_families: dict[str, int] = {}
    for row in records:
        key = str(row.get("signal_family") or "OTRA_SENAL")
        published_families[key] = published_families.get(key, 0) + 1

    payload = {
        "schema": "RIGP-INVESTIGATION-QUEUE-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "methodology": METHODOLOGY,
        "guardrail": GUARDRAIL,
        "axes": {
            "review_priority_score": "Cuánto conviene mirar esto primero (0-100).",
            "laft_compatibility_score": "Calculado aparte en la capa de tipologías; no forma parte de este score.",
        },
        "calibration": {
            "multipliers_applied": len(multipliers),
            "signal_types_adjusted": sorted(multipliers),
            "source": calibration_path,
            "note": (
                "Los ajustes provienen de expedientes cerrados por analistas, verificados por hash. "
                "Sin casos cerrados suficientes no se mueve ningún score."
            ),
        },
        "score_components": {
            "rarity_component": "0-30 · -ln(prevalencia del patrón en su grupo de pares)",
            "convergence_component": "0-25 · familias independientes que coinciden en la contraparte",
            "relative_materiality_component": "0-20 · monto frente a la mediana del grupo de pares",
            "external_evidence_component": "0-18 · evidencia CGR candidata, ponderada por calidad del match",
            "entity_context_component": "0-10 · señales registrales de la contraparte",
        },
        "peer_group_definition": (
            "Relación proveedor–organismo: subtítulo dominante × quintil de escala de gasto del "
            "organismo en el año. Señal sin proveedor (nivel organismo): quintil de escala de gasto."
        ),
        "peer_groups": int(peer_groups),
        "analysis_windows": windows.describe(),
        "window_policy": (
            "Sólo la ventana de acción se publica como cola de trabajo. La ventana de aprendizaje "
            "no se descarta: es la base sobre la que se calcularon prevalencias, medianas de pares "
            "y primeras apariciones de proveedor."
        ),
        "signals_by_window": {str(k): int(v) for k, v in by_window.items()},
        "baseline": {
            "years_before_action_window": int(baseline[0] or 0),
            "relations_in_learning_window": int(baseline[1] or 0),
        },
        "total_signals": int(total),
        "actionable_signals": actionable_total,
        "priority_tiers": tiers,
        "published_signals": len(records),
        "publication_policy": {
            "top_n": int(top_n),
            "family_min_share": float(family_min_share),
            "note": "Cuota mínima por familia para que ninguna desaparezca del corte por score.",
        },
        "published_families": published_families,
        "queue": records,
    }
    queue_path = Path(output_json)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return {
        "path": str(out),
        "signals": int(total),
        "actionable_signals": actionable_total,
        "signals_by_window": {str(k): int(v) for k, v in by_window.items()},
        "baseline_years": int(baseline[0] or 0),
        "action_from_year": windows.action_from_year,
        "calibration_multipliers": len(multipliers),
        "priority_tiers": tiers,
        "published_signals": len(records),
        "published_families": published_families,
        "peer_groups": int(peer_groups),
    }
