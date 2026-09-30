from __future__ import annotations

import json

import pandas as pd

from radar_presupuesto.public_funds_export import build_public_funds_export


def test_public_funds_export_uses_paid_non_intra_state_rows(tmp_path):
    parquet = tmp_path / "facts.parquet"
    output = tmp_path / "public_funds.json"
    rows = [
        {
            "periodo": 2026, "mes": 7, "monto_pago": 100.0,
            "rut_beneficiario": "76.123.456-7", "organization_id": "ORG-PA-01-01",
            "nombre_capitulo": "Servicio A", "nombre_area": "", "nombre_partida": "Partida A",
            "is_provider": False, "is_intra_state": False,
        },
        {
            "periodo": 2026, "mes": 8, "monto_pago": 50.0,
            "rut_beneficiario": "76.123.456-7", "organization_id": "ORG-PA-01-01",
            "nombre_capitulo": "Servicio A", "nombre_area": "", "nombre_partida": "Partida A",
            "is_provider": True, "is_intra_state": False,
        },
        {
            "periodo": 2026, "mes": 8, "monto_pago": 999.0,
            "rut_beneficiario": "76.123.456-7", "organization_id": "ORG-PA-02-01",
            "nombre_capitulo": "Servicio B", "nombre_area": "", "nombre_partida": "Partida B",
            "is_provider": False, "is_intra_state": True,
        },
        {
            "periodo": 2026, "mes": 8, "monto_pago": 0.0,
            "rut_beneficiario": "77.000.000-1", "organization_id": "ORG-PA-03-01",
            "nombre_capitulo": "Servicio C", "nombre_area": "", "nombre_partida": "Partida C",
            "is_provider": False, "is_intra_state": False,
        },
    ]
    pd.DataFrame(rows).to_parquet(parquet, index=False)

    payload = build_public_funds_export(str(parquet), str(output), "PF-202608-abcdef123456")

    assert payload["schema"] == "ATLAS_PUBLIC_FUNDS_V1"
    assert payload["semantics"]["amount_basis"] == "POSITIVE_MONTO_PAGO"
    assert payload["semantics"]["intra_state"] == "EXCLUDED"
    assert len(payload["entity"]) == 1
    assert payload["entity"][0]["rut"] == "76.123.456-7"
    assert payload["entity"][0]["amount_total"] == 150.0
    assert payload["entity"][0]["payer_count"] == 1

    yearly = payload["year"][0]
    assert yearly["amount_total"] == 150.0
    assert yearly["amount_transfer"] == 100.0
    assert yearly["amount_supplier"] == 50.0

    roles = {(r["role"], r["amount"]) for r in payload["payer_year"]}
    assert roles == {("RECIPIENT", 100.0), ("SUPPLIER", 50.0)}
    assert json.loads(output.read_text(encoding="utf-8"))["snapshot_id"] == "PF-202608-abcdef123456"
