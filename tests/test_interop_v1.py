import pandas as pd
from radar_presupuesto.normalize import normalize_frame

def test_valid_id():
    row=normalize_frame(pd.DataFrame([{"RUT_BENEFICIARIO":"96.921.130-0","NOMBRE_BENEFICIARIO":"Ejemplo","PROVEEDOR":"SI"}])).iloc[0]
    assert row["entity_id"]=="ENT-RUT-96921130-0"
    assert row["recipient_id"]
    assert row["provider_id"]

def test_invalid_id():
    row=normalize_frame(pd.DataFrame([{"RUT_BENEFICIARIO":"96.921.130-1","NOMBRE_BENEFICIARIO":"Ejemplo"}])).iloc[0]
    assert pd.isna(row["entity_id"])
    assert row["identity_status"]=="UNRESOLVED"
