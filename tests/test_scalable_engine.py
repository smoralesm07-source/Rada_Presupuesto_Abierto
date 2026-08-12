from pathlib import Path
import pandas as pd
from radar_presupuesto.analytics import build_signals
from radar_presupuesto.features import build_profiles
from radar_presupuesto.normalize import normalize_frame
from radar_presupuesto.search import build_fts_from_parquet,hybrid_search,query_fts
FIX=Path(__file__).parent/"fixtures"/"sample_transactions.csv"

def _parquet(tmp_path:Path)->Path:
    df=normalize_frame(pd.read_csv(FIX,dtype=str),source_file=FIX.name);path=tmp_path/"transactions_2026.parquet";df.to_parquet(path,index=False);return path

def test_duckdb_profiles_and_signals(tmp_path):
    parquet=_parquet(tmp_path);profiles=build_profiles(str(parquet),str(tmp_path/"profiles"));assert Path(profiles["providers"]).exists();assert Path(profiles["recipients"]).exists();assert Path(profiles["organizations"]).exists();out=tmp_path/"risk_signals.parquet";result=build_signals(str(parquet),str(out),amount_z=4.5,min_group=8,frag_min=3,frag_cv=0.15,year_end_ratio=2.5);assert out.exists();assert result["signals"]>=2;kinds=set(pd.read_parquet(out)["signal_type"]);assert "POTENTIAL_FRAGMENTATION" in kinds;assert "YEAR_END_SPIKE" in kinds

def test_hybrid_search_filters_and_disk_fts(tmp_path):
    parquet=_parquet(tmp_path);result=hybrid_search(str(parquet),text="constructora",rut="76.123.456-0",year=2026,month=1,min_amount=900000,max_amount=1100000,location="Santiago",provider_only=True,limit=20);assert len(result)==3;assert set(result["rut_beneficiario"])=={"76123456-0"};db=tmp_path/"search.sqlite";count=build_fts_from_parquet(str(parquet),db);assert count==14;rows=query_fts(db,"CONSTRUCTORA",10);assert len(rows)==3
