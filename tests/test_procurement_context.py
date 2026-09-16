import json
from pathlib import Path

import pandas as pd

from radar_presupuesto.procurement_context import build_procurement_context


def test_builds_purchase_order_context_for_published_finding(tmp_path: Path):
    facts = pd.DataFrame(
        [
            {
                "organization_id": "ORG-A",
                "provider_id": "PRV-X",
                "periodo": 2026,
                "orden_compra": "1234-10-SE26",
                "monto_devengado": 10_000_000,
                "fecha_documento": "2026-01-15",
                "is_aggregated": False,
            },
            {
                "organization_id": "ORG-A",
                "provider_id": "PRV-X",
                "periodo": 2026,
                "orden_compra": "1234-11-SE26",
                "monto_devengado": 20_000_000,
                "fecha_documento": "2026-02-20",
                "is_aggregated": False,
            },
            {
                "organization_id": "ORG-A",
                "provider_id": "PRV-X",
                "periodo": 2026,
                "orden_compra": "",
                "monto_devengado": 5_000_000,
                "fecha_documento": "2026-03-02",
                "is_aggregated": False,
            },
        ]
    )
    parquet = tmp_path / "facts.parquet"
    facts.to_parquet(parquet, index=False)
    findings = tmp_path / "findings.json"
    findings.write_text(
        json.dumps(
            {
                "relation_findings": [
                    {
                        "finding_id": "HAL-1",
                        "organization_id": "ORG-A",
                        "provider_id": "PRV-X",
                        "periodo": 2026,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "procurement.json"

    coverage = build_procurement_context(
        parquet_glob=str(parquet),
        findings_json=str(findings),
        output_json=str(out),
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    row = payload["findings"][0]

    assert coverage["findings_requested"] == 1
    assert coverage["findings_with_purchase_order"] == 1
    assert row["purchase_order_count"] == 2
    assert set(row["purchase_order_examples"]) == {"1234-10-SE26", "1234-11-SE26"}
    assert row["source_rows"] == 3
    assert row["rows_with_purchase_order"] == 2
    assert 0.66 < row["purchase_order_row_coverage"] < 0.67
    assert "no acredita" in row["guardrail"].lower()


def test_empty_findings_writes_valid_payload(tmp_path: Path):
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps({"relation_findings": []}), encoding="utf-8")
    out = tmp_path / "procurement.json"

    coverage = build_procurement_context(
        parquet_glob=str(tmp_path / "missing-*.parquet"),
        findings_json=str(findings),
        output_json=str(out),
    )
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert coverage["findings_requested"] == 0
    assert payload["schema"] == "RIGP-PROCUREMENT-CONTEXT-v2"
    assert payload["findings"] == []
