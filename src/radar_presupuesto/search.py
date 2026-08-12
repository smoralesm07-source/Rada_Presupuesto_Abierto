from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import pandas as pd

FTS_FIELDS = ["transaction_id", "organization_id", "recipient_id", "provider_id", "rut", "source_id", "beneficiary", "institution", "area", "budget_text", "document_number", "document_type", "purchase_order", "bip", "sector", "region"]


def _fts_sql() -> str:
    fields = ["transaction_id UNINDEXED"] + FTS_FIELDS[1:]
    return "CREATE VIRTUAL TABLE transactions_fts USING fts5(" + ", ".join(fields) + ", tokenize='unicode61 remove_diacritics 2')"


def _txt(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def build_fts(df: pd.DataFrame, db_path: str | Path) -> None:
    db_path = Path(db_path); db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path); con.execute("DROP TABLE IF EXISTS transactions_fts"); con.execute(_fts_sql())
    rows = []
    for _, row in df.iterrows():
        budget = " ".join(_txt(row.get(c)) for c in ["nombre_subtitulo","nombre_item","nombre_asignacion","nombre_programa_presupuestario","nombre_bip","nombre_ubicacion_geografica"])
        institution = " ".join(_txt(row.get(c)) for c in ["nombre_partida","nombre_capitulo"])
        rows.append((_txt(row.get("transaction_id")),_txt(row.get("organization_id")),_txt(row.get("recipient_id")),_txt(row.get("provider_id")),_txt(row.get("rut_beneficiario")),_txt(row.get("beneficiario_source_id")),_txt(row.get("nombre_beneficiario")),institution,_txt(row.get("nombre_area")),budget,_txt(row.get("numero_documento")),_txt(row.get("tipo_documento")),_txt(row.get("orden_compra")),_txt(row.get("codigo_bip")),_txt(row.get("sector")),_txt(row.get("region"))))
    con.executemany("INSERT INTO transactions_fts VALUES (" + ",".join("?" for _ in FTS_FIELDS) + ")", rows)
    con.commit(); con.close()


def query_fts(db_path: str | Path, query: str, limit: int = 50) -> list[dict]:
    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    rows = con.execute("SELECT *, bm25(transactions_fts) AS rank FROM transactions_fts WHERE transactions_fts MATCH ? ORDER BY rank LIMIT ?", (query, max(1,min(int(limit),10000)))).fetchall()
    con.close(); return [dict(r) for r in rows]


def build_fts_from_parquet(parquet_glob: str, db_path: str | Path, chunk_rows: int = 50_000) -> int:
    import duckdb
    db_path = Path(db_path); db_path.parent.mkdir(parents=True, exist_ok=True)
    sqlcon = sqlite3.connect(db_path); sqlcon.execute("PRAGMA journal_mode=OFF"); sqlcon.execute("PRAGMA synchronous=OFF")
    sqlcon.execute("DROP TABLE IF EXISTS transactions_fts"); sqlcon.execute(_fts_sql())
    dcon = duckdb.connect()
    q = f"""SELECT transaction_id,organization_id,recipient_id,coalesce(provider_id,''),coalesce(rut_beneficiario,''),coalesce(beneficiario_source_id,''),coalesce(nombre_beneficiario,''),concat_ws(' ',coalesce(nombre_partida,''),coalesce(nombre_capitulo,'')),coalesce(nombre_area,''),concat_ws(' ',coalesce(nombre_subtitulo,''),coalesce(nombre_item,''),coalesce(nombre_asignacion,''),coalesce(nombre_programa_presupuestario,''),coalesce(nombre_bip,''),coalesce(nombre_ubicacion_geografica,'')),coalesce(numero_documento,''),coalesce(tipo_documento,''),coalesce(orden_compra,''),coalesce(codigo_bip,''),coalesce(sector,''),coalesce(region,'') FROM read_parquet('{parquet_glob}',union_by_name=true)"""
    cur = dcon.execute(q); total = 0; placeholders = ",".join("?" for _ in FTS_FIELDS)
    while True:
        batch = cur.fetch_df_chunk(max(1, chunk_rows // 2048))
        if batch.empty: break
        sqlcon.executemany(f"INSERT INTO transactions_fts VALUES ({placeholders})", batch.itertuples(index=False,name=None)); total += len(batch)
        if total % 250000 < len(batch): sqlcon.commit()
    sqlcon.commit(); sqlcon.close(); dcon.close(); return total


def hybrid_search(parquet_glob: str = "data/processed/transactions_*.parquet", text: str | None = None, rut: str | None = None, source_id: str | None = None, organization_id: str | None = None, recipient_id: str | None = None, provider_id: str | None = None, year: int | None = None, month: int | None = None, date_from: str | None = None, date_to: str | None = None, min_amount: float | None = None, max_amount: float | None = None, min_paid_amount: float | None = None, max_paid_amount: float | None = None, purchase_order: str | None = None, bip: str | None = None, location: str | None = None, region: str | None = None, sector: str | None = None, budget_code: str | None = None, document_number: str | None = None, document_type: str | None = None, provider_only: bool | None = None, person_only: bool | None = None, honorarium_only: bool | None = None, intra_state_only: bool | None = None, floating_debt_only: bool | None = None, max_payment_days: int | None = None, limit: int = 100) -> pd.DataFrame:
    import duckdb
    from .ids import normalize_rut
    where, params = [], []
    if text:
        where.append("lower(concat_ws(' ',coalesce(nombre_beneficiario,''),coalesce(rut_beneficiario,''),coalesce(nombre_partida,''),coalesce(nombre_capitulo,''),coalesce(nombre_area,''),coalesce(nombre_subtitulo,''),coalesce(nombre_item,''),coalesce(nombre_asignacion,''),coalesce(nombre_programa_presupuestario,''),coalesce(nombre_bip,''),coalesce(nombre_ubicacion_geografica,''),coalesce(numero_documento,''),coalesce(tipo_documento,''),coalesce(orden_compra,''),coalesce(sector,''),coalesce(region,''))) LIKE ?"); params.append(f"%{text.lower()}%")
    if rut:
        nrut = normalize_rut(rut)
        if not nrut: raise ValueError("RUT inválido: formato o dígito verificador")
        where.append("rut_beneficiario = ?"); params.append(nrut)
    for field,value in [("beneficiario_source_id",source_id),("organization_id",organization_id),("recipient_id",recipient_id),("provider_id",provider_id),("orden_compra",purchase_order),("codigo_bip",bip),("numero_documento",document_number)]:
        if value: where.append(f"{field} = ?"); params.append(value)
    if year is not None: where.append("periodo = ?"); params.append(int(year))
    if month is not None: where.append("mes = ?"); params.append(int(month))
    if date_from: where.append("coalesce(try_cast(fecha_documento AS DATE),try_cast(fecha_pago AS DATE)) >= ?::DATE"); params.append(date_from)
    if date_to: where.append("coalesce(try_cast(fecha_documento AS DATE),try_cast(fecha_pago AS DATE)) <= ?::DATE"); params.append(date_to)
    if min_amount is not None: where.append("try_cast(monto_devengado AS DOUBLE) >= ?"); params.append(float(min_amount))
    if max_amount is not None: where.append("try_cast(monto_devengado AS DOUBLE) <= ?"); params.append(float(max_amount))
    if min_paid_amount is not None: where.append("try_cast(monto_pago AS DOUBLE) >= ?"); params.append(float(min_paid_amount))
    if max_paid_amount is not None: where.append("try_cast(monto_pago AS DOUBLE) <= ?"); params.append(float(max_paid_amount))
    for field,value in [("nombre_ubicacion_geografica",location),("region",region),("sector",sector),("tipo_documento",document_type)]:
        if value: where.append(f"lower(coalesce({field},'')) LIKE ?"); params.append(f"%{value.lower()}%")
    if budget_code: where.append("concat_ws('.',coalesce(subtitulo,''),coalesce(item,''),coalesce(asignacion,'')) LIKE ?"); params.append(f"{budget_code}%")
    for field,value in [("is_provider",provider_only),("is_person",person_only),("is_honorarium",honorarium_only),("is_intra_state",intra_state_only),("is_floating_debt",floating_debt_only)]:
        if value is not None: where.append(f"{field} = ?"); params.append(bool(value))
    if max_payment_days is not None: where.append("try_cast(dias_de_pago AS INTEGER) <= ?"); params.append(int(max_payment_days))
    clause = " AND ".join(where) if where else "TRUE"; safe_limit = max(1,min(int(limit),10000)); con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{parquet_glob}',union_by_name=true) WHERE {clause} ORDER BY periodo DESC,mes DESC,try_cast(monto_devengado AS DOUBLE) DESC NULLS LAST LIMIT {safe_limit}",params).df(); con.close(); return df


def main() -> None:
    p = argparse.ArgumentParser(description="Search Radar Presupuesto Abierto FTS index"); p.add_argument("--db",default="data/index/search.sqlite"); p.add_argument("--query",required=True); p.add_argument("--limit",type=int,default=50); args=p.parse_args()
    print(json.dumps(query_fts(args.db,args.query,args.limit),ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
