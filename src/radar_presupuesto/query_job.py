from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from .extract import download
from .normalize import normalize_to_parquet
from .pipeline import AVAILABLE_SOURCE_STATUSES
from .search import hybrid_search
from .source_discovery import discover_downloads

ALLOWED_FILTERS = {"rut","source_id","organization_id","recipient_id","provider_id","month","date_from","date_to","min_amount","max_amount","min_paid_amount","max_paid_amount","purchase_order","bip","location","region","sector","budget_code","document_number","document_type","provider_only","person_only","honorarium_only","intra_state_only","floating_debt_only","max_payment_days"}


def run_query(year: int, output_dir: str = "data/query", text: str | None = None, filters: dict | None = None, limit: int = 1000) -> dict:
    limit = max(1,min(int(limit),10000)); filters = filters or {}
    unknown = set(filters) - ALLOWED_FILTERS
    if unknown: raise ValueError(f"Filtros no soportados: {sorted(unknown)}")
    sources = {x["year"]:x for x in discover_downloads() if x.get("status") in AVAILABLE_SOURCE_STATUSES}
    source = sources.get(int(year))
    if not source: raise SystemExit(f"No se confirmó fuente bulk oficial para {year}")
    out = Path(output_dir); out.mkdir(parents=True,exist_ok=True); raw=out/f"pagos-{year}.gz"; parquet=out/f"transactions_{year}.parquet"
    if not raw.exists(): download(source["url"],raw)
    normalize_meta=normalize_to_parquet(raw,parquet)
    df=hybrid_search(str(parquet),text=text,year=year,limit=limit,**filters)
    csv_path=out/"result.csv"; json_path=out/"result.json"; meta_path=out/"query_metadata.json"
    df.to_csv(csv_path,index=False); json_path.write_text(df.to_json(orient="records",force_ascii=False,date_format="iso",indent=2),encoding="utf-8")
    metadata={"executed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"source":source,"normalization":normalize_meta,"query":{"year":year,"text":text,"filters":filters,"limit":limit},"result_count":int(len(df)),"outputs":{"csv":str(csv_path),"json":str(json_path)}}
    meta_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8"); return metadata


def main() -> None:
    p=argparse.ArgumentParser(description="Auditable one-year Presupuesto Abierto search job"); p.add_argument("--year",type=int,required=True); p.add_argument("--text"); p.add_argument("--filters-json",default="{}"); p.add_argument("--limit",type=int,default=1000); p.add_argument("--output-dir",default="data/query"); args=p.parse_args()
    filters=json.loads(args.filters_json); print(json.dumps(run_query(args.year,args.output_dir,args.text,filters,args.limit),ensure_ascii=False,indent=2))


if __name__=="__main__": main()
