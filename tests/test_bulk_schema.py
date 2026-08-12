from pathlib import Path
import pandas as pd
from radar_presupuesto.normalize import normalize_frame,normalize_to_parquet


def test_current_bulk_aliases_and_pseudonymous_identity():
    raw=pd.DataFrame({"PERIODO":["2026","2026"],"MES":["6","6"],"PARTIDA":["08","08"],"CAPITULO":["01","01"],"AREA":["001","001"],"BENEFICIARIO":["96.875.230-8","d58d17bb171b8f33cb09ef4eadb4dfe0f34921ae"],"NOMBRE_BENEFICIARIO":["RUTA DEL MAIPO S.A.","PERSONA EJEMPLO"],"MONEDA":["CLP","CLP"],"MONTO":["900000","100000"],"MONTO_ORIGINAL":["900000","100000"],"DEVENGO":["1000000","100000"],"DEVENGO_ORIGINAL":["1000000","100000"],"PROVEEDOR":["1","0"],"PERSONA":["0","1"],"REGION":[None,None]})
    out=normalize_frame(raw); a=out.iloc[0]; b=out.iloc[1]
    assert a["rut_beneficiario"]=="96875230-8";assert a["provider_id"]=="PRV-RUT-96875230-8";assert a["recipient_id"]=="RCV-RUT-96875230-8"
    assert b["rut_beneficiario"]=="";assert b["beneficiario_id_type"]=="HASH_SHA1";assert b["provider_id"]=="";assert b["recipient_id"].startswith("RCV-SHA1-")
    assert a["monto_pago"]==900000;assert a["monto_devengado"]==1000000;assert a["region"]==""


def test_parquet_schema_is_stable_when_text_column_changes_from_empty_to_value(tmp_path:Path):
    src=tmp_path/"bulk.csv";pd.DataFrame({"PERIODO":["2026","2026"],"MES":["1","2"],"PARTIDA":["08","08"],"CAPITULO":["01","01"],"AREA":["001","001"],"BENEFICIARIO":["96875230-8","96934730-K"],"NOMBRE_BENEFICIARIO":["A SPA","B SPA"],"DEVENGO":["100","200"],"MONTO":["100","200"],"REGION":[None,"METROPOLITANA"],"DIAS_DE_PAGO":[None,"15"],"PROVEEDOR":["1","1"]}).to_csv(src,index=False)
    out=tmp_path/"bulk.parquet";meta=normalize_to_parquet(src,out,chunksize=1);result=pd.read_parquet(out);assert meta["rows"]==2;assert result["region"].tolist()==["","METROPOLITANA"];assert result["dias_de_pago"].tolist()==["","15"]
