from __future__ import annotations

from pathlib import Path

import duckdb


def extend_signals(
    parquet_glob: str,
    signals_path: str = "data/signals/risk_signals.parquet",
    concentration_min_providers: int = 8,
    concentration_min_share: float = 0.45,
    concentration_min_hhi: float = 0.25,
    concentration_min_amount: float = 10_000_000,
    payment_delay_min_days: float = 60.0,
    payment_delay_min_group: int = 20,
    payment_delay_quantile: float = 0.99,
    new_series_min_amount: float = 50_000_000,
    new_series_quantile: float = 0.99,
) -> dict:
    """Append explainable second-generation signals to the base signal parquet."""
    path = Path(signals_path)
    if not path.exists():
        raise FileNotFoundError(signals_path)

    con = duckdb.connect()
    con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)")
    con.execute(f"CREATE OR REPLACE TABLE merged AS SELECT * FROM read_parquet('{path.as_posix()}')")

    con.execute(f"""
        INSERT INTO merged
        WITH spend AS (
          SELECT organization_id,periodo,provider_id,min(recipient_id) recipient_id,
                 sum(try_cast(monto_devengado AS DOUBLE)) amount,
                 min(transaction_id) transaction_id,min(mes) mes
          FROM facts
          WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''
            AND coalesce(is_aggregated,FALSE)=FALSE
            AND try_cast(monto_devengado AS DOUBLE)>0
          GROUP BY 1,2,3
        ), totals AS (
          SELECT organization_id,periodo,sum(amount) total,count(*) providers FROM spend GROUP BY 1,2
        ), ranked AS (
          SELECT s.*,t.total,t.providers,s.amount/t.total AS provider_share,
                 sum(power(s.amount/t.total,2)) OVER (PARTITION BY s.organization_id,s.periodo) hhi,
                 row_number() OVER (PARTITION BY s.organization_id,s.periodo ORDER BY s.amount DESC,s.provider_id) rn
          FROM spend s JOIN totals t USING(organization_id,periodo) WHERE t.total>0
        )
        SELECT 'SIG-PA-PROVIDER_CONCENTRATION-'||upper(substr(md5(organization_id||'|'||cast(periodo AS VARCHAR)||'|'||provider_id),1,20)),
               'PROVIDER_CONCENTRATION',transaction_id,organization_id,recipient_id,provider_id,
               periodo,mes,provider_share,1.0/providers,hhi,
               CASE WHEN provider_share>=0.65 OR hhi>=0.40 THEN 'HIGH' ELSE 'MEDIUM' END,
               'MEDIUM','DERIVED_SIGNAL',
               'Un proveedor concentra una fracción material del gasto a proveedores del organismo en el año observado.',
               'La concentración puede responder a contratos marco, monopolios técnicos o grandes proyectos; requiere comparar categoría, competencia y evolución histórica.',
               '["Revisar categoría y modalidad de contratación","Comparar HHI con años previos","Revisar adjudicaciones/OC del proveedor dominante","Contrastar si existen alternativas de mercado"]'
        FROM ranked
        WHERE rn=1 AND providers>={int(concentration_min_providers)}
          AND provider_share>={float(concentration_min_share)} AND hhi>={float(concentration_min_hhi)}
          AND amount>={float(concentration_min_amount)}
    """)

    con.execute(f"""
        INSERT INTO merged
        WITH b AS (
          SELECT *,try_cast(dias_de_pago AS DOUBLE) pay_days FROM facts
          WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''
            AND coalesce(is_aggregated,FALSE)=FALSE
            AND try_cast(dias_de_pago AS DOUBLE) IS NOT NULL
            AND try_cast(dias_de_pago AS DOUBLE)>=0
        ), st AS (
          SELECT organization_id,count(*) n,median(pay_days) med,
                 quantile_cont(pay_days,{float(payment_delay_quantile)}) q
          FROM b GROUP BY 1
        )
        SELECT 'SIG-PA-PAYMENT_DELAY_OUTLIER-'||upper(substr(md5(b.transaction_id),1,20)),
               'PAYMENT_DELAY_OUTLIER',b.transaction_id,b.organization_id,b.recipient_id,b.provider_id,
               b.periodo,b.mes,b.pay_days,st.med,
               CASE WHEN st.med>0 THEN b.pay_days/st.med ELSE b.pay_days END,
               CASE WHEN b.pay_days>=120 THEN 'HIGH' ELSE 'MEDIUM' END,
               'MEDIUM','DERIVED_SIGNAL',
               'El plazo de pago está en la cola extrema del organismo y supera un umbral material de días.',
               'El retraso puede obedecer a controversias, recepción conforme tardía o condiciones contractuales; revisar secuencia documental antes de interpretar.',
               '["Revisar fecha de recepción conforme","Revisar controversias/notas de crédito","Comparar con otros pagos del mismo contrato","Verificar patrón recurrente con el proveedor"]'
        FROM b JOIN st USING(organization_id)
        WHERE st.n>={int(payment_delay_min_group)} AND b.pay_days>={float(payment_delay_min_days)}
          AND b.pay_days>=st.q AND (st.med<=0 OR b.pay_days>=st.med*2)
    """)

    con.execute(f"""
        INSERT INTO merged
        WITH meta AS (
          SELECT count(DISTINCT periodo) AS series_years,max(periodo) max_year FROM facts
        ), firsts AS (
          SELECT provider_id,min(periodo) first_year FROM facts
          WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' GROUP BY 1
        ), cur AS (
          SELECT f.provider_id,min(f.recipient_id) recipient_id,min(f.organization_id) organization_id,
                 min(f.transaction_id) transaction_id,min(f.mes) mes,count(*) tx,
                 count(DISTINCT f.organization_id) organizations,
                 sum(try_cast(f.monto_devengado AS DOUBLE)) amount,f.periodo
          FROM facts f JOIN firsts x USING(provider_id),meta m
          WHERE f.is_provider=TRUE AND coalesce(f.provider_id,'')<>''
            AND coalesce(f.is_aggregated,FALSE)=FALSE
            AND x.first_year=m.max_year AND f.periodo=m.max_year
          GROUP BY 1,9
        ), threshold AS (
          SELECT quantile_cont(amount,{float(new_series_quantile)}) q FROM cur
        )
        SELECT 'SIG-PA-NEW_TO_SERIES_HIGH_SPEND-'||upper(substr(md5(cur.provider_id||'|'||cast(cur.periodo AS VARCHAR)),1,20)),
               'NEW_TO_SERIES_HIGH_SPEND',cur.transaction_id,cur.organization_id,cur.recipient_id,cur.provider_id,
               cur.periodo,cur.mes,cur.amount,threshold.q,cur.organizations,
               CASE WHEN cur.organizations>=3 THEN 'HIGH' ELSE 'MEDIUM' END,
               'MEDIUM','DERIVED_SIGNAL',
               'Proveedor no observado en años anteriores de la serie procesada ingresa con gasto acumulado en la cola superior de sus pares nuevos.',
               'Nuevo en la serie no significa nueva empresa ni irregularidad; puede reflejar cambio de proveedor, licitación reciente o cobertura histórica incompleta.',
               '["Confirmar primera aparición en serie completa","Revisar adjudicación inicial y OC","Comparar monto con proveedores nuevos pares","Contrastar antigüedad societaria en fuentes externas"]'
        FROM cur,threshold,meta
        WHERE meta.series_years>=2 AND cur.tx>=3
          AND cur.amount>=greatest({float(new_series_min_amount)},coalesce(threshold.q,0))
    """)

    tmp = path.with_suffix(".v03.tmp.parquet")
    con.execute(f"""
        COPY (
          SELECT * EXCLUDE(_rn) FROM (
            SELECT *,row_number() OVER (
              PARTITION BY signal_id
              ORDER BY CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                       coalesce(deviation,0) DESC
            ) _rn FROM merged
          ) WHERE _rn=1
        ) TO '{tmp.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)
    """)
    con.close()
    tmp.replace(path)

    con = duckdb.connect()
    row = con.execute(f"SELECT count(*),count(DISTINCT signal_id) FROM read_parquet('{path.as_posix()}')").fetchone()
    by_type = dict(con.execute(f"SELECT signal_type,count(*) FROM read_parquet('{path.as_posix()}') GROUP BY 1").fetchall())
    con.close()
    return {"path": str(path), "signals": int(row[0]), "distinct_signal_ids": int(row[1]), "by_type": by_type}
