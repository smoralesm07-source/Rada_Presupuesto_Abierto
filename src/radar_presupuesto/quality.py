from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import duckdb


def audit_quality(parquet_glob: str, output: str = "docs/data/quality.json") -> dict:
    con=duckdb.connect(); con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}',union_by_name=true)")
    row=con.execute("""SELECT count(*) rows,count(DISTINCT transaction_id) distinct_transaction_ids,count(*) FILTER (WHERE periodo IS NULL OR mes IS NULL OR mes NOT BETWEEN 1 AND 12) invalid_period_rows,count(*) FILTER (WHERE coalesce(rut_beneficiario,'')<>'') rut_rows,count(*) FILTER (WHERE beneficiario_id_type='HASH_SHA1') hashed_identity_rows,count(*) FILTER (WHERE is_provider=TRUE) provider_rows,count(*) FILTER (WHERE is_person=TRUE) person_rows,count(*) FILTER (WHERE coalesce(nombre_beneficiario,'')<>'') beneficiary_name_rows,count(*) FILTER (WHERE try_cast(monto_devengado AS DOUBLE) IS NOT NULL) devengado_rows,count(*) FILTER (WHERE try_cast(monto_pago AS DOUBLE) IS NOT NULL) pago_rows,count(*) FILTER (WHERE fecha_documento IS NOT NULL) document_date_rows,count(*) FILTER (WHERE fecha_pago IS NOT NULL) payment_date_rows,count(*) FILTER (WHERE coalesce(orden_compra,'')<>'') purchase_order_rows,count(*) FILTER (WHERE coalesce(codigo_bip,'')<>'') bip_rows,count(*) FILTER (WHERE coalesce(region,'')<>'') region_rows,count(*) FILTER (WHERE coalesce(sector,'')<>'') sector_rows,count(*) FILTER (WHERE try_cast(monto_devengado AS DOUBLE)<0) negative_devengado_rows,min(periodo) first_year,max(periodo) last_year,coalesce(sum(try_cast(monto_devengado AS DOUBLE)),0) devengado_total FROM facts""").fetchone()
    cols=[d[0] for d in con.description]; m=dict(zip(cols,row)); total=int(m["rows"] or 0)
    def pct(key): return round(int(m[key] or 0)/total,6) if total else 0.0
    coverage={"valid_rut":pct("rut_rows"),"hashed_source_identity":pct("hashed_identity_rows"),"provider_flag":pct("provider_rows"),"person_flag":pct("person_rows"),"beneficiary_name":pct("beneficiary_name_rows"),"monto_devengado":pct("devengado_rows"),"monto_pago":pct("pago_rows"),"fecha_documento":pct("document_date_rows"),"fecha_pago":pct("payment_date_rows"),"orden_compra":pct("purchase_order_rows"),"bip":pct("bip_rows"),"region":pct("region_rows"),"sector":pct("sector_rows")}
    duplicate_ratio=1-(int(m["distinct_transaction_ids"] or 0)/total) if total else 0.0; warnings=[]
    if not total: warnings.append("EMPTY_DATASET")
    if total and coverage["monto_devengado"]<0.50: warnings.append("LOW_DEVENGADO_COVERAGE")
    if duplicate_ratio>0.01: warnings.append("TRANSACTION_ID_COLLISIONS_GT_1PCT")
    if int(m["invalid_period_rows"] or 0)>0: warnings.append("INVALID_PERIOD_ROWS")
    payload={"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"status":"PASS" if not warnings else "WARN","rows":total,"distinct_transaction_ids":int(m["distinct_transaction_ids"] or 0),"duplicate_transaction_id_ratio":round(duplicate_ratio,8),"invalid_period_rows":int(m["invalid_period_rows"] or 0),"negative_devengado_rows":int(m["negative_devengado_rows"] or 0),"first_year":None if m["first_year"] is None else int(m["first_year"]),"last_year":None if m["last_year"] is None else int(m["last_year"]),"devengado_total":float(m["devengado_total"] or 0),"coverage":coverage,"warnings":warnings,"interpretation":"RUT válido se informa solo tras validar dígito verificador. Identidades HASH_SHA1 se conservan como claves pseudónimas de fuente, no como RUT. Cobertura no equivale a riesgo."}
    out=Path(output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); con.close(); return payload
