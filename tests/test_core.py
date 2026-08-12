from pathlib import Path
import pandas as pd
from radar_presupuesto.ids import normalize_rut,source_identifier_type
from radar_presupuesto.normalize import normalize_frame
from radar_presupuesto.anomalies import detect_all
from radar_presupuesto.search import build_fts,query_fts
FIX=Path(__file__).parent/"fixtures"/"sample_transactions.csv"

def test_rut_validation_and_hash_separation():
    assert normalize_rut("76.123.456-0")=="76123456-0"
    assert normalize_rut("76.123.456-k")==""
    hashed="d58d17bb171b8f33cb09ef4eadb4dfe0f34921ae"
    assert normalize_rut(hashed)==""
    assert source_identifier_type(hashed)=="HASH_SHA1"

def test_normalization_ids_are_stable():
    raw=pd.read_csv(FIX,dtype=str);a=normalize_frame(raw);b=normalize_frame(raw)
    assert a.transaction_id.tolist()==b.transaction_id.tolist();assert a.provider_id.str.startswith("PRV-RUT-").all();assert a.recipient_id.str.startswith("RCV-RUT-").all();assert a.organization_id.str.startswith("ORG-").all()

def test_signals_include_fragmentation_and_year_end_spike():
    df=normalize_frame(pd.read_csv(FIX,dtype=str));signals=detect_all(df,{"amount_outlier":{"threshold":4.5,"min_group":8},"potential_fragmentation":{"min_count":3,"max_cv":0.15},"year_end_spike":{"ratio_threshold":2.5}});kinds=set(signals.signal_type);assert "POTENTIAL_FRAGMENTATION" in kinds;assert "YEAR_END_SPIKE" in kinds

def test_fts_search(tmp_path):
    df=normalize_frame(pd.read_csv(FIX,dtype=str));db=tmp_path/"search.sqlite";build_fts(df,db);rows=query_fts(db,"CONSTRUCTORA",10);assert rows;assert any("CONSTRUCTORA" in r["beneficiary"] for r in rows)
