from __future__ import annotations

from pathlib import Path

import duckdb


def build_signals(
    parquet_glob: str,
    output_path: str = "data/signals/risk_signals.parquet",
    amount_z: float = 4.5,
    min_group: int = 20,
    amount_min_ratio: float = 3.0,
    amount_quantile: float = 0.99,
    amount_provider_only: bool = True,
    amount_exclude_aggregated: bool = True,
    frag_min: int = 3,
    frag_cv: float = 0.15,
    year_end_ratio: float = 2.5,
) -> dict:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"CREATE OR REPLACE VIEW facts AS "
        f"SELECT * FROM read_parquet('{parquet_glob}',union_by_name=true)"
    )

    amount_filters = [
        "try_cast(monto_devengado AS DOUBLE) IS NOT NULL",
        "try_cast(monto_devengado AS DOUBLE) >= 0",
    ]
    if amount_provider_only:
        amount_filters.append("is_provider=TRUE")
        amount_filters.append("coalesce(provider_id,'')<>''")
    if amount_exclude_aggregated:
        amount_filters.append("coalesce(is_aggregated,FALSE)=FALSE")
    amount_where = " AND ".join(amount_filters)

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW amount_stats AS
        WITH b AS (
          SELECT organization_id,
                 coalesce(subtitulo,'') subtitulo,
                 coalesce(item,'') item,
                 try_cast(monto_devengado AS DOUBLE) amount,
                 ln(1+greatest(try_cast(monto_devengado AS DOUBLE),0)) x
          FROM facts
          WHERE {amount_where}
        ), med AS (
          SELECT organization_id,subtitulo,item,
                 count(*) n,
                 median(x) med_x,
                 median(amount) med_amount,
                 quantile_cont(amount,{float(amount_quantile)}) quantile_amount
          FROM b
          GROUP BY 1,2,3
        )
        SELECT b.organization_id,b.subtitulo,b.item,
               med.n,med.med_x,med.med_amount,med.quantile_amount,
               median(abs(b.x-med.med_x)) mad_x
        FROM b
        JOIN med USING(organization_id,subtitulo,item)
        GROUP BY 1,2,3,4,5,6,7
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE signals AS
        SELECT 'SIG-PA-AMOUNT_OUTLIER-'||upper(substr(md5(f.transaction_id),1,20)) signal_id,
               'AMOUNT_OUTLIER' signal_type,
               f.transaction_id,f.organization_id,f.recipient_id,f.provider_id,
               f.periodo,f.mes,
               cast(f.monto_devengado AS DOUBLE) observed_value,
               s.med_amount expected_value,
               0.6745*(ln(1+greatest(cast(f.monto_devengado AS DOUBLE),0))-s.med_x)/s.mad_x deviation,
               CASE WHEN 0.6745*(ln(1+greatest(cast(f.monto_devengado AS DOUBLE),0))-s.med_x)/s.mad_x>=7
                    THEN 'HIGH' ELSE 'MEDIUM' END severity,
               'MEDIUM' confidence,
               'DERIVED_SIGNAL' record_class,
               'Monto proveedor en la cola superior material de su grupo organismo/subtítulo/ítem: supera el percentil configurado y el múltiplo mínimo de la mediana.' why_flagged,
               'Patrón que requiere explicación documental/contextual; no implica irregularidad por sí solo.' investigation_hypothesis,
               '[\"Revisar documento y Orden de Compra\",\"Comparar con objeto/ítem presupuestario\",\"Revisar historial del proveedor en el organismo\",\"Descartar hitos contractuales o pagos extraordinarios legítimos\"]' recommended_checks
        FROM facts f
        JOIN amount_stats s
          ON f.organization_id=s.organization_id
         AND coalesce(f.subtitulo,'')=s.subtitulo
         AND coalesce(f.item,'')=s.item
        WHERE {amount_where}
          AND s.n>={int(min_group)}
          AND s.mad_x>0
          AND cast(f.monto_devengado AS DOUBLE) >= s.quantile_amount
          AND cast(f.monto_devengado AS DOUBLE) >= s.med_amount*{float(amount_min_ratio)}
          AND 0.6745*(ln(1+greatest(cast(f.monto_devengado AS DOUBLE),0))-s.med_x)/s.mad_x>={float(amount_z)}
        """
    )

    con.execute(
        f"""
        INSERT INTO signals
        WITH g AS (
          SELECT organization_id,provider_id,recipient_id,coalesce(item,'') item,
                 date_trunc('week',try_cast(fecha_documento AS DATE)) wk,
                 count(*) n,
                 avg(cast(monto_devengado AS DOUBLE)) av,
                 stddev_pop(cast(monto_devengado AS DOUBLE)) sd,
                 min(transaction_id) transaction_id,
                 min(periodo) periodo,
                 min(mes) mes
          FROM facts
          WHERE is_provider=TRUE
            AND coalesce(provider_id,'')<>''
            AND coalesce(is_aggregated,FALSE)=FALSE
            AND try_cast(fecha_documento AS DATE) IS NOT NULL
            AND try_cast(monto_devengado AS DOUBLE)>0
          GROUP BY 1,2,3,4,5
        )
        SELECT 'SIG-PA-POTENTIAL_FRAGMENTATION-'||upper(substr(md5(organization_id||provider_id||item||cast(wk AS VARCHAR)),1,20)),
               'POTENTIAL_FRAGMENTATION',transaction_id,organization_id,recipient_id,provider_id,
               periodo,mes,n,{int(frag_min)},
               CASE WHEN av=0 THEN NULL ELSE sd/av END,
               'MEDIUM','MEDIUM','DERIVED_SIGNAL',
               'Múltiples documentos de montos similares para mismo organismo/proveedor/ítem en una ventana semanal.',
               'Puede corresponder a facturación periódica o pagos parciales; requiere contrastar objeto, OC y modalidad de contratación.',
               '[\"Revisar OC/licitación\",\"Agrupar documentos por objeto\",\"Descartar pagos parciales o periodicidad legítima\"]'
        FROM g
        WHERE n>={int(frag_min)} AND av>0 AND sd/av<={float(frag_cv)}
        """
    )

    con.execute(
        f"""
        INSERT INTO signals
        WITH monthly AS (
          SELECT organization_id,periodo,mes,
                 sum(cast(monto_devengado AS DOUBLE)) amount
          FROM facts
          WHERE try_cast(monto_devengado AS DOUBLE) IS NOT NULL
          GROUP BY 1,2,3
        ), yr AS (
          SELECT organization_id,periodo,
                 avg(amount) FILTER (WHERE mes BETWEEN 1 AND 10) base,
                 avg(amount) FILTER (WHERE mes BETWEEN 11 AND 12) endavg
          FROM monthly
          GROUP BY 1,2
        ), sample AS (
          SELECT organization_id,periodo,
                 min(transaction_id) transaction_id
          FROM facts
          GROUP BY 1,2
        )
        SELECT 'SIG-PA-YEAR_END_SPIKE-'||upper(substr(md5(y.organization_id||cast(y.periodo AS VARCHAR)),1,20)),
               'YEAR_END_SPIKE',s.transaction_id,y.organization_id,
               '' recipient_id,'' provider_id,
               y.periodo,CAST(NULL AS BIGINT) mes,y.endavg,y.base,y.endavg/y.base,
               'MEDIUM','MEDIUM','DERIVED_SIGNAL',
               'Promedio mensual noviembre-diciembre supera materialmente el promedio enero-octubre.',
               'La estacionalidad presupuestaria puede ser legítima; comparar con años previos y composición por proveedor.',
               '[\"Comparar estacionalidad histórica\",\"Revisar concentración por proveedor\",\"Revisar nuevas OC/modificaciones\"]'
        FROM yr y
        JOIN sample s USING(organization_id,periodo)
        WHERE y.base>0
          AND y.endavg IS NOT NULL
          AND y.endavg/y.base>={float(year_end_ratio)}
        """
    )

    con.execute(
        """
        INSERT INTO signals
        WITH d AS (
          SELECT periodo,mes,organization_id,recipient_id,
                 any_value(provider_id) provider_id,
                 coalesce(numero_documento,'') numero_documento,
                 coalesce(cast(fecha_documento AS VARCHAR),'') fecha_documento,
                 coalesce(cast(monto_devengado AS VARCHAR),'') monto_devengado,
                 coalesce(folio,'') folio,
                 count(*) n,
                 min(transaction_id) transaction_id
          FROM facts
          WHERE coalesce(is_aggregated,FALSE)=FALSE
          GROUP BY 1,2,3,4,6,7,8,9
          HAVING count(*)>1
        )
        SELECT 'SIG-PA-EXACT_DUPLICATE-'||upper(substr(md5(transaction_id),1,20)),
               'EXACT_DUPLICATE_CANDIDATE',transaction_id,organization_id,recipient_id,provider_id,
               periodo,mes,n,1,n-1,
               'HIGH','MEDIUM','DERIVED_SIGNAL',
               'Registros coinciden en las principales claves documentales.',
               'Puede ser duplicación de origen, ajuste o pago parcial; requiere verificación.',
               '[\"Verificar duplicación fuente\",\"Revisar folio\",\"Comparar fechas y pagos parciales\"]'
        FROM d
        """
    )

    con.execute(
        f"COPY signals TO '{out.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)"
    )
    count = con.execute("SELECT count(*) FROM signals").fetchone()[0]
    by_type = dict(
        con.execute("SELECT signal_type,count(*) FROM signals GROUP BY 1").fetchall()
    )
    con.close()
    return {"path": str(out), "signals": count, "by_type": by_type}
