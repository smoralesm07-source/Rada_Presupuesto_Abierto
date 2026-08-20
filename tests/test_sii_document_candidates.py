from pathlib import Path

import pandas as pd

from radar_presupuesto.sii_document_candidates import build_sii_document_candidates


def test_build_sii_document_candidates_keeps_latest_eligible_document(tmp_path: Path):
    rows = pd.DataFrame([
        {
            "entity_id": "ENT-RUT-76123456-0",
            "rut_beneficiario": "76123456-0",
            "nombre_beneficiario": "PROVEEDOR UNO SPA",
            "tipo_documento": "FACTURA ELECTRONICA",
            "numero_documento": "100",
            "folio": "",
            "fecha_documento": pd.Timestamp("2026-01-10"),
            "transaction_id": "T1",
            "transaction_fingerprint": "F1",
            "periodo": 2026,
            "mes": 1,
            "source_file": "a.csv",
            "source_row_number": 1,
            "is_provider": True,
            "is_intra_state": False,
            "is_person": False,
        },
        {
            "entity_id": "ENT-RUT-76123456-0",
            "rut_beneficiario": "76123456-0",
            "nombre_beneficiario": "PROVEEDOR UNO SPA",
            "tipo_documento": "FACTURA ELECTRONICA",
            "numero_documento": "200",
            "folio": "",
            "fecha_documento": pd.Timestamp("2026-08-10"),
            "transaction_id": "T2",
            "transaction_fingerprint": "F2",
            "periodo": 2026,
            "mes": 8,
            "source_file": "b.csv",
            "source_row_number": 2,
            "is_provider": True,
            "is_intra_state": False,
            "is_person": False,
        },
        {
            "entity_id": "ENT-RUT-76543210-8",
            "rut_beneficiario": "76543210-8",
            "nombre_beneficiario": "ORGANISMO PUBLICO",
            "tipo_documento": "FACTURA ELECTRONICA",
            "numero_documento": "300",
            "folio": "",
            "fecha_documento": pd.Timestamp("2026-08-12"),
            "transaction_id": "T3",
            "transaction_fingerprint": "F3",
            "periodo": 2026,
            "mes": 8,
            "source_file": "c.csv",
            "source_row_number": 3,
            "is_provider": True,
            "is_intra_state": True,
            "is_person": False,
        },
    ])
    source = tmp_path / "transactions.parquet"
    out = tmp_path / "candidates.parquet"
    meta = tmp_path / "status.json"
    rows.to_parquet(source, index=False)

    result = build_sii_document_candidates(str(source), str(out), str(meta))
    candidates = pd.read_parquet(out)

    assert result["rows"] == 1
    assert result["entities"] == 1
    assert candidates.iloc[0]["entity_id"] == "ENT-RUT-76123456-0"
    assert candidates.iloc[0]["numero_documento"] == "200"
    assert candidates.iloc[0]["observation_intent"] == "SPECIFIC_DOCUMENT_VERIFICATION_CANDIDATE"
    assert result["semantic"] == "CANDIDATES_ONLY_NOT_SII_AUTHORIZATION"
