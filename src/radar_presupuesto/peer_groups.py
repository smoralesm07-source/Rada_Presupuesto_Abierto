from __future__ import annotations

from pathlib import Path

import duckdb


def build_provider_peer_context(
    parquet_glob: str,
    output_parquet: str = "data/processed/provider_peer_context.parquet",
    min_peer_providers: int = 5,
) -> dict:
    """Build provider materiality context relative to comparable budget-category peers.

    Peer group = same public organization, year, subtitle and item. For each
    organization-provider-year relation the output keeps the budget category where
    the provider concentrates the largest amount, then reports its position among
    providers in that same group. This is descriptive context for future scoring;
    it does not itself create a signal or allegation.
    """
    out = Path(output_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)")
    con.execute(
        f"""
        COPY (
          WITH category_spend AS (
            SELECT
              organization_id,
              periodo,
              coalesce(nullif(trim(subtitulo),''),'SIN_SUBTITULO') AS subtitulo,
              coalesce(nullif(trim(item),''),'SIN_ITEM') AS item,
              provider_id,
              any_value(nombre_beneficiario) AS provider_name,
              sum(coalesce(try_cast(monto_devengado AS DOUBLE),0)) AS provider_amount,
              count(*) AS transaction_count
            FROM facts
            WHERE is_provider=TRUE
              AND coalesce(provider_id,'')<>''
              AND coalesce(is_aggregated,FALSE)=FALSE
              AND coalesce(try_cast(monto_devengado AS DOUBLE),0)>0
            GROUP BY 1,2,3,4,5
          ), peer_stats AS (
            SELECT
              organization_id,periodo,subtitulo,item,
              count(*) AS peer_provider_count,
              median(provider_amount) AS peer_median_amount,
              quantile_cont(provider_amount,0.75) AS peer_p75_amount,
              quantile_cont(provider_amount,0.90) AS peer_p90_amount,
              quantile_cont(provider_amount,0.99) AS peer_p99_amount
            FROM category_spend
            GROUP BY 1,2,3,4
          ), ranked AS (
            SELECT
              c.*,
              p.peer_provider_count,
              p.peer_median_amount,
              p.peer_p75_amount,
              p.peer_p90_amount,
              p.peer_p99_amount,
              percent_rank() OVER (
                PARTITION BY c.organization_id,c.periodo,c.subtitulo,c.item
                ORDER BY c.provider_amount
              ) AS peer_percentile,
              row_number() OVER (
                PARTITION BY c.organization_id,c.periodo,c.provider_id
                ORDER BY c.provider_amount DESC,c.subtitulo,c.item
              ) AS dominant_category_rank
            FROM category_spend c
            JOIN peer_stats p USING(organization_id,periodo,subtitulo,item)
          )
          SELECT
            'PEER-' || upper(substr(md5(
              organization_id || '|' || cast(periodo AS VARCHAR) || '|' || subtitulo || '|' || item
            ),1,20)) AS peer_group_id,
            organization_id,
            provider_id,
            provider_name,
            periodo,
            subtitulo,
            item,
            provider_amount,
            transaction_count,
            peer_provider_count,
            peer_median_amount,
            peer_p75_amount,
            peer_p90_amount,
            peer_p99_amount,
            peer_percentile,
            CASE
              WHEN peer_median_amount>0 THEN provider_amount/peer_median_amount
              ELSE NULL
            END AS amount_to_peer_median_ratio,
            CASE
              WHEN peer_provider_count<{int(min_peer_providers)} THEN 'INSUFFICIENT_PEERS'
              WHEN peer_percentile>=0.99 THEN 'EXTREME_WITHIN_PEERS'
              WHEN peer_percentile>=0.90 THEN 'HIGH_WITHIN_PEERS'
              ELSE 'WITHIN_PEER_RANGE'
            END AS peer_position,
            'Contexto relativo dentro del mismo organismo, año, subtítulo e ítem. No acredita irregularidad ni reemplaza el análisis de mercado o contratación.' AS peer_guardrail
          FROM ranked
          WHERE dominant_category_rank=1
        ) TO '{out.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """
    )
    row = con.execute(
        f"""
        SELECT
          count(*) AS rows,
          count(DISTINCT peer_group_id) AS groups,
          sum(CASE WHEN peer_position='INSUFFICIENT_PEERS' THEN 1 ELSE 0 END) AS insufficient,
          sum(CASE WHEN peer_position='EXTREME_WITHIN_PEERS' THEN 1 ELSE 0 END) AS extreme,
          sum(CASE WHEN peer_position='HIGH_WITHIN_PEERS' THEN 1 ELSE 0 END) AS high
        FROM read_parquet('{out.as_posix()}')
        """
    ).fetchone()
    con.close()
    return {
        "path": str(out),
        "rows": int(row[0] or 0),
        "peer_groups": int(row[1] or 0),
        "insufficient_peer_rows": int(row[2] or 0),
        "extreme_peer_rows": int(row[3] or 0),
        "high_peer_rows": int(row[4] or 0),
        "min_peer_providers": int(min_peer_providers),
    }
