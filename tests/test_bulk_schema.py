from pathlib import Path

import pandas as pd

from radar_presupuesto.normalize import normalize_frame, normalize_to_parquet


def test_current_bulk_aliases_map_to_canonical_contract():
    raw = pd.DataFrame(
        {
            "PERIODO": ["2026"],
            "MES": ["6"],
            "PARTIDA": ["08"],
            "CAPITULO": ["01"],
            "AREA": ["001"],
            "BENEFICIARIO": ["76.123.456-K"],
            "NOMBRE_BENEFICIARIO": ["Proveedor Real Spa"],
            "MONEDA": ["CLP"],
            "MONTO": ["900000"],
            "MONTO_ORIGINAL": ["900000"],
            "DEVENGO": ["1000000"],
            "DEVENGO_ORIGINAL": ["1000000"],
            "REGION": [None],
        }
    )
    out = normalize_frame(raw)
    row = out.iloc[0]
    assert row["rut_beneficiario_normalizado"] == "76123456-K"
    assert row["monto_pago"] == 900000
    assert row["monto_devengado"] == 1000000
    assert row["monto_pago_original"] == 900000
    assert row["monto_devengado_original"] == 1000000
    assert row["moneda_presupuestaria"] == "CLP"
    assert row["region"] == ""


def test_parquet_schema_is_stable_when_text_column_changes_from_empty_to_value(tmp_path: Path):
    src = tmp_path / "bulk.csv"
    pd.DataFrame(
        {
            "PERIODO": ["2026", "2026"],
            "MES": ["1", "2"],
            "PARTIDA": ["08", "08"],
            "CAPITULO": ["01", "01"],
            "AREA": ["001", "001"],
            "BENEFICIARIO": ["76123456-K", "77654321-1"],
            "NOMBRE_BENEFICIARIO": ["A SPA", "B SPA"],
            "DEVENGO": ["100", "200"],
            "MONTO": ["100", "200"],
            "REGION": [None, "METROPOLITANA"],
            "DIAS_DE_PAGO": [None, "15"],
        }
    ).to_csv(src, index=False)

    out = tmp_path / "bulk.parquet"
    meta = normalize_to_parquet(src, out, chunksize=1)
    result = pd.read_parquet(out)
    assert meta["rows"] == 2
    assert len(result) == 2
    assert result["region"].tolist() == ["", "METROPOLITANA"]
    assert result["dias_de_pago"].tolist() == ["", "15"]
