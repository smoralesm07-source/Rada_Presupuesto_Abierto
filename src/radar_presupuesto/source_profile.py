from __future__ import annotations

import argparse,json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
from .extract import download
from .ids import source_identifier_type
from .normalize import canonical_column,detect_delimiter
from .pipeline import AVAILABLE_SOURCE_STATUSES
from .source_discovery import discover_downloads


def profile_year(year:int,output:str="docs/data/source_profile.json",nrows:int=250_000)->dict:
    sources={x["year"]:x for x in discover_downloads() if x.get("status") in AVAILABLE_SOURCE_STATUSES}; source=sources.get(year)
    if not source: raise SystemExit(f"No bulk source confirmed for {year}")
    raw=Path("data/raw")/f"profile-pagos-{year}.gz"
    if not raw.exists(): download(source["url"],raw)
    sep=detect_delimiter(raw); df=pd.read_csv(raw,compression="gzip",sep=sep,encoding="utf-8-sig",dtype=str,nrows=nrows,low_memory=False); original_columns=list(df.columns); canonical={c:canonical_column(c) for c in df.columns}; renamed=df.rename(columns=canonical)
    def counts(col,top=20):
        if col not in renamed:return {}
        v=renamed[col].fillna("").astype(str).str.strip(); return {str(k):int(x) for k,x in v.value_counts(dropna=False).head(top).items()}
    ids=renamed.get("beneficiario_source_id",pd.Series([],dtype="string")).fillna("").astype(str).str.strip(); names=renamed.get("nombre_beneficiario",pd.Series([],dtype="string")).fillna("").astype(str).str.strip(); types=ids.map(source_identifier_type); type_counts={str(k):int(v) for k,v in types.value_counts().items()}
    payload={"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"year":year,"source":source,"sample_rows":int(len(df)),"delimiter":sep,"original_columns":original_columns,"canonical_column_mapping":canonical,"value_counts":{"proveedor":counts("proveedor"),"persona":counts("persona"),"honorario":counts("honorario"),"intraestado":counts("intraestado"),"deuda_flotante":counts("deuda_flotante"),"agregado":counts("agregado")},"beneficiary_identity_type_counts":type_counts,"hashed_identity_examples":[{"raw":str(r),"name":str(n)} for r,n in zip(ids[types=="HASH_SHA1"].head(30),names[types=="HASH_SHA1"].head(30))],"note":"BENEFICIARIO es una clave de identidad de fuente: puede ser RUT válido o identificador SHA1 pseudónimo. El radar los mantiene separados."}
    out=Path(output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); return payload


def main():
    p=argparse.ArgumentParser();p.add_argument("--year",type=int,required=True);p.add_argument("--output",default="docs/data/source_profile.json");p.add_argument("--nrows",type=int,default=250000);a=p.parse_args();print(json.dumps(profile_year(a.year,a.output,a.nrows),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
