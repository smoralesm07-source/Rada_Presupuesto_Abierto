from __future__ import annotations

from pathlib import Path

import pandas as pd

from radar_presupuesto.spend_view import build_spend_view_v2


def test_spend_view_v2_builds_l12_and_flows(tmp_path: Path):
    rows = []
    periods = pd.period_range("2024-09", "2026-08", freq="M")
    for i, period in enumerate(periods):
        for org, org_name, provider, provider_name, base in [
            ("ORG-1", "SERVICIO UNO", "PRV-1", "PROVEEDOR UNO", 100_000),
            ("ORG-2", "SERVICIO DOS", "PRV-2", "PROVEEDOR DOS", 60_000),
        ]:
            rows.append(
                {
                    "periodo": period.year,
                    "mes": period.month,
                    "monto_devengado": float(base + i * 1_000),
                    "is_provider": True,
                    "provider_id": provider,
                    "transaction_id": f"TRX-{org}-{provider}-{period}",
                    "organization_id": org,
                    "nombre_area": org_name,
                    "nombre_capitulo": "",
                    "nombre_partida": "PARTIDA TEST",
                    "region": "13",
                    "nombre_subtitulo": "BIENES Y SERVICIOS",
                    "subtitulo": "22",
                    "nombre_beneficiario": provider_name,
                    "rut_beneficiario": "76000000-0",
                    "orden_compra": f"OC-{i}",
                }
            )
    parquet = tmp_path / "facts.parquet"
    pd.DataFrame(rows).to_parquet(parquet, index=False)
    output = tmp_path / "spend_view_v2.json"

    payload = build_spend_view_v2(
        str(parquet),
        output=str(output),
        prioritized_path=None,
        service_limit=20,
        provider_limit=20,
        flow_limit=100,
        flows_per_service=8,
    )

    assert payload["schema"] == "PRESUPUESTO_SPEND_VIEW_V2"
    assert payload["mode"] == "REAL"
    assert payload["window"]["start_month"] == "2025-09-01"
    assert payload["window"]["end_month"] == "2026-08-01"
    assert len(payload["window"]["months"]) == 12
    assert len(payload["services"]) == 2
    assert len(payload["providers"]) == 2
    assert len(payload["flows"]) == 2
    assert all(len(row["monthly"]) == 12 for row in payload["flows"])
    assert payload["overview"]["organizations_l12"] == 2
    assert payload["published"]["flows_per_service_cap"] == 8
    assert output.exists()
