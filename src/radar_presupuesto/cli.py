from __future__ import annotations
import argparse,json
from .coverage import write_coverage
from .pipeline import run_sample,run_years
from .search import hybrid_search,query_fts
from .source_discovery import write_catalog
from .spend_view import build_spend_view
from .territorial_export import build_territorial_context

def main()->None:
    p=argparse.ArgumentParser(prog="radar-pa"); sub=p.add_subparsers(dest="cmd",required=True); probe=sub.add_parser("probe",help="audita fuentes y cobertura"); probe.add_argument("--catalog",default="docs/data/source_catalog.json"); probe.add_argument("--coverage",default="docs/data/coverage.json"); run=sub.add_parser("run",help="ejecuta pipeline"); run.add_argument("--years",nargs="*",type=int); run.add_argument("--sample"); fts=sub.add_parser("fts",help="búsqueda full-text rápida"); fts.add_argument("query"); fts.add_argument("--db",default="data/index/search.sqlite"); fts.add_argument("--limit",type=int,default=50); s=sub.add_parser("search",help="búsqueda híbrida estructurada + texto"); s.add_argument("--text"); s.add_argument("--rut"); s.add_argument("--organization-id"); s.add_argument("--provider-id"); s.add_argument("--year",type=int); s.add_argument("--month",type=int); s.add_argument("--min-amount",type=float); s.add_argument("--max-amount",type=float); s.add_argument("--purchase-order"); s.add_argument("--bip"); s.add_argument("--location"); s.add_argument("--budget-code"); s.add_argument("--limit",type=int,default=100); s.add_argument("--parquet",default="data/processed/transactions_*.parquet")
    sv=sub.add_parser("spend-view",help="construye la vista de ejecución y pagos del Estado"); sv.add_argument("--parquet-glob",default="data/processed/transactions_*.parquet"); sv.add_argument("--priority",default="data/signals/prioritized_signals.parquet"); sv.add_argument("--output",default="docs/data/spend_view_v1.json"); sv.add_argument("--config",default="config/spend_view.yaml"); sv.add_argument("--mode",default="REAL",choices=["REAL","DEMO_SYNTHETIC"])
    tv=sub.add_parser("territorial",help="exporta el contexto territorial compacto"); tv.add_argument("--parquet-glob",default="data/processed/transactions_*.parquet"); tv.add_argument("--priority",default="data/signals/prioritized_signals.parquet"); tv.add_argument("--output",default="docs/data/territorial_context_v1.json")
    args=p.parse_args()
    if args.cmd=="probe":
        catalog=write_catalog(args.catalog); coverage=write_coverage(args.coverage); print(json.dumps({"downloads":catalog,"services":len(coverage)},ensure_ascii=False,indent=2))
    elif args.cmd=="run":
        if args.sample: run_sample(args.sample)
        elif args.years: run_years(args.years)
        else: raise SystemExit("run requiere --sample o --years")
    elif args.cmd=="fts": print(json.dumps(query_fts(args.db,args.query,args.limit),ensure_ascii=False,indent=2))
    elif args.cmd=="spend-view":
        payload=build_spend_view(args.parquet_glob,args.priority,args.output,args.config,args.mode); print(json.dumps({"schema":payload["schema"],"mode":payload["mode"],"transactions":payload["coverage"]["transactions"],"regions":len(payload["territory"]["regions"]),"anomalous_providers":len(payload["providers"]["anomalous"]),"new_providers":len(payload["new_providers"].get("material",[])),"alerts":len(payload["alerts"])},ensure_ascii=False,indent=2))
    elif args.cmd=="territorial":
        payload=build_territorial_context(args.parquet_glob,args.priority,args.output); print(json.dumps({"schema":payload["schema"],"regions":len(payload["regions"])},ensure_ascii=False,indent=2))
    elif args.cmd=="search":
        df=hybrid_search(args.parquet,text=args.text,rut=args.rut,organization_id=args.organization_id,provider_id=args.provider_id,year=args.year,month=args.month,min_amount=args.min_amount,max_amount=args.max_amount,purchase_order=args.purchase_order,bip=args.bip,location=args.location,budget_code=args.budget_code,limit=args.limit); print(df.to_json(orient="records",force_ascii=False,date_format="iso",indent=2))
if __name__=="__main__": main()
