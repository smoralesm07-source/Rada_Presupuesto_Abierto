from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd


def build_fts(df: pd.DataFrame, db_path: str | Path) -> None:
    db_path=Path(db_path); db_path.parent.mkdir(parents=True,exist_ok=True); con=sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS transactions_fts")
    con.execute("CREATE VIRTUAL TABLE transactions_fts USING fts5(transaction_id UNINDEXED, organization_id, provider_id, rut, beneficiary, institution, area, budget_text, document_number, purchase_order, bip, tokenize='unicode61 remove_diacritics 2')")
    cols={"transaction_id":"transaction_id","organization_id":"organization_id","provider_id":"provider_id","rut":"rut_beneficiario_normalizado","beneficiary":"nombre_beneficiario","institution":"nombre_capitulo","area":"nombre_area","document_number":"numero_documento","purchase_order":"orden_compra","bip":"codigo_bip"}
    payload=[]
    for _,row in df.iterrows():
        budget=" ".join(str(row.get(c,"") or "") for c in ["nombre_subtitulo","nombre_item","nombre_asignacion","nombre_programa_presupuestario","nombre_bip","nombre_ubicacion_geografica"])
        payload.append(tuple(str(row.get(src,"") or "") for src in cols.values())[:7]+(budget,)+tuple(str(row.get(src,"") or "") for src in list(cols.values())[7:]))
    con.executemany("INSERT INTO transactions_fts VALUES (?,?,?,?,?,?,?,?,?,?,?)",payload); con.commit(); con.close()


def query_fts(db_path: str | Path, query: str, limit: int = 50) -> list[dict]:
    con=sqlite3.connect(db_path); con.row_factory=sqlite3.Row
    rows=con.execute("SELECT *, bm25(transactions_fts) AS rank FROM transactions_fts WHERE transactions_fts MATCH ? ORDER BY rank LIMIT ?",(query,limit)).fetchall(); con.close()
    return [dict(r) for r in rows]


def query_parquet(parquet_glob: str, where: str = "TRUE", limit: int = 100) -> pd.DataFrame:
    import duckdb
    return duckdb.sql(f"SELECT * FROM read_parquet('{parquet_glob}') WHERE {where} LIMIT {int(limit)}").df()


def build_fts_from_parquet(parquet_glob: str, db_path: str | Path, chunk_rows: int = 50_000) -> int:
    import duckdb
    db_path=Path(db_path); db_path.parent.mkdir(parents=True,exist_ok=True); sqlcon=sqlite3.connect(db_path)
    sqlcon.execute("DROP TABLE IF EXISTS transactions_fts")
    sqlcon.execute("CREATE VIRTUAL TABLE transactions_fts USING fts5(transaction_id UNINDEXED, organization_id, provider_id, rut, beneficiary, institution, area, budget_text, document_number, purchase_order, bip, tokenize='unicode61 remove_diacritics 2')")
    dcon=duckdb.connect(); q=f"""SELECT transaction_id,organization_id,provider_id,coalesce(rut_beneficiario_normalizado,'') rut,coalesce(nombre_beneficiario,'') beneficiary,coalesce(nombre_capitulo,'') institution,coalesce(nombre_area,'') area,concat_ws(' ',coalesce(nombre_subtitulo,''),coalesce(nombre_item,''),coalesce(nombre_asignacion,''),coalesce(nombre_programa_presupuestario,''),coalesce(nombre_bip,''),coalesce(nombre_ubicacion_geografica,'')) budget_text,coalesce(numero_documento,'') document_number,coalesce(orden_compra,'') purchase_order,coalesce(codigo_bip,'') bip FROM read_parquet('{parquet_glob}',union_by_name=true)"""
    cur=dcon.execute(q); total=0
    while True:
        batch=cur.fetch_df_chunk(max(1,chunk_rows//2048))
        if batch.empty: break
        sqlcon.executemany("INSERT INTO transactions_fts VALUES (?,?,?,?,?,?,?,?,?,?,?)",batch.itertuples(index=False,name=None)); total+=len(batch); sqlcon.commit()
    sqlcon.close(); dcon.close(); return total


def hybrid_search(parquet_glob: str="data/processed/transactions_*.parquet",text: str|None=None,rut: str|None=None,organization_id: str|None=None,provider_id: str|None=None,year: int|None=None,month: int|None=None,min_amount: float|None=None,max_amount: float|None=None,purchase_order: str|None=None,bip: str|None=None,location: str|None=None,budget_code: str|None=None,limit: int=100) -> pd.DataFrame:
    import duckdb
    where=[]; params=[]
    if text:
        where.append("lower(concat_ws(' ',coalesce(nombre_beneficiario,''),coalesce(nombre_partida,''),coalesce(nombre_capitulo,''),coalesce(nombre_area,''),coalesce(nombre_subtitulo,''),coalesce(nombre_item,''),coalesce(nombre_asignacion,''),coalesce(nombre_programa_presupuestario,''),coalesce(nombre_bip,''),coalesce(nombre_ubicacion_geografica,''),coalesce(numero_documento,''),coalesce(orden_compra,''))) LIKE ?"); params.append(f"%{text.lower()}%")
    if rut:
        from .ids import normalize_rut
        where.append("rut_beneficiario_normalizado = ?"); params.append(normalize_rut(rut))
    for field,value in [("organization_id",organization_id),("provider_id",provider_id),("orden_compra",purchase_order),("codigo_bip",bip)]:
        if value: where.append(f"{field} = ?"); params.append(value)
    if year is not None: where.append("periodo = ?"); params.append(int(year))
    if month is not None: where.append("mes = ?"); params.append(int(month))
    if min_amount is not None: where.append("try_cast(monto_devengado AS DOUBLE) >= ?"); params.append(float(min_amount))
    if max_amount is not None: where.append("try_cast(monto_devengado AS DOUBLE) <= ?"); params.append(float(max_amount))
    if location: where.append("lower(coalesce(nombre_ubicacion_geografica,'')) LIKE ?"); params.append(f"%{location.lower()}%")
    if budget_code: where.append("concat_ws('.',coalesce(subtitulo,''),coalesce(item,''),coalesce(asignacion,'')) LIKE ?"); params.append(f"{budget_code}%")
    clause=" AND ".join(where) if where else "TRUE"; con=duckdb.connect()
    df=con.execute(f"SELECT * FROM read_parquet('{parquet_glob}',union_by_name=true) WHERE {clause} ORDER BY periodo DESC,mes DESC,try_cast(monto_devengado AS DOUBLE) DESC NULLS LAST LIMIT {int(limit)}",params).df(); con.close(); return df


def main() -> None:
    p=argparse.ArgumentParser(description="Search Radar Presupuesto Abierto FTS index"); p.add_argument("--db",default="data/index/search.sqlite"); p.add_argument("--query",required=True); p.add_argument("--limit",type=int,default=50); args=p.parse_args()
    print(json.dumps(query_fts(args.db,args.query,args.limit),ensure_ascii=False,indent=2))


if __name__=="__main__": main()
