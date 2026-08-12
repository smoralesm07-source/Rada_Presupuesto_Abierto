from pathlib import Path
import json

import pandas as pd

from radar_presupuesto.ids import transaction_fingerprint
from radar_presupuesto.normalize import normalize_frame, normalize_to_parquet
from radar_presupuesto.quality import audit_quality
from radar_presupuesto.analytics import build_signals
from radar_presupuesto.advanced_signals import extend_signals
from radar_presupuesto.cgr_correlation import correlate_with_cgr
from radar_presupuesto.prioritization import prioritize_signals


def _raw(rows=2):
    return pd.DataFrame({
        "PERIODO": ["2025"] * rows,"MES": ["6"] * rows,"PARTIDA": ["08"] * rows,
        "NOMBRE_PARTIDA": ["MINISTERIO EJEMPLO"] * rows,"CAPITULO": ["01"] * rows,
        "NOMBRE_CAPITULO": ["SERVICIO EJEMPLO"] * rows,"AREA": ["001"] * rows,
        "NOMBRE_AREA": ["SERVICIO EJEMPLO"] * rows,"SUBTITULO": ["22"] * rows,"ITEM": ["01"] * rows,
        "BENEFICIARIO": ["A-1"] * rows,"NOMBRE_BENEFICIARIO": ["PROVEEDOR DEMO SPA"] * rows,
        "NUMERO_DOCUMENTO": ["100"] * rows,"FECHA_DOCUMENTO": ["2025-06-01"] * rows,
        "FECHA_PAGO": ["2025-06-15"] * rows,"DEVENGO": ["1000000"] * rows,"MONTO": ["1000000"] * rows,
        "PROVEEDOR": ["1"] * rows,"PERSONA": ["0"] * rows,"REGION": ["Metropolitana"] * rows,
        "DIAS_DE_PAGO": ["14"] * rows,
    })


def test_physical_transaction_id_is_unique_but_fingerprint_can_repeat():
    out = normalize_frame(_raw(2), source_file="pagos-2025.gz")
    assert out.transaction_id.nunique() == 2
    assert out.transaction_fingerprint.nunique() == 1
    assert out.source_row_number.tolist() == [1, 2]
    assert out.transaction_fingerprint.iloc[0] == transaction_fingerprint(out.iloc[0].to_dict())


def test_row_identity_is_stable_across_chunk_sizes(tmp_path: Path):
    src = tmp_path / "bulk.csv"
    _raw(5).to_csv(src, index=False)
    a = tmp_path / "a.parquet"; b = tmp_path / "b.parquet"
    normalize_to_parquet(src, a, chunksize=1); normalize_to_parquet(src, b, chunksize=3)
    da = pd.read_parquet(a); db = pd.read_parquet(b)
    assert da.transaction_id.tolist() == db.transaction_id.tolist()
    assert da.transaction_id.nunique() == len(da)
    assert da.transaction_fingerprint.nunique() == 1


def test_quality_separates_id_integrity_from_document_repetition(tmp_path: Path):
    df = normalize_frame(_raw(3), source_file="pagos-2025.gz")
    p = tmp_path / "facts.parquet"; q = tmp_path / "quality.json"
    df.to_parquet(p, index=False)
    result = audit_quality(str(p), str(q))
    assert result["transaction_id_collision_ratio"] == 0
    assert result["repeated_fingerprint_rows"] == 2
    assert result["source_fact_repeat_ratio"] > 0


def test_cgr_exact_provider_match_is_candidate_not_fact(tmp_path: Path):
    facts = normalize_frame(_raw(1), source_file="pagos-2025.gz")
    p = tmp_path / "facts.parquet"; facts.to_parquet(p, index=False)
    silver = tmp_path / "cgr"; silver.mkdir()
    (silver / "providers.jsonl").write_text(json.dumps({
        "confidence": 0.92,"name": "Proveedor Demo SpA","normalized_name": "PROVEEDOR DEMO SPA",
        "provider_id": "ENT-CGR-DEMO","region": "Metropolitana","source_document_id": "CGR-AUD-DEMO"
    }) + "\n", encoding="utf-8")
    (silver / "organizations.jsonl").write_text("", encoding="utf-8")
    (silver / "findings.jsonl").write_text(json.dumps({
        "document_id": "CGR-AUD-DEMO","finding_id": "FND-DEMO","aml_score": 75,
        "severity": "HIGH","risk_family": "PROCUREMENT","source_url": "https://example.invalid/cgr-demo"
    }) + "\n", encoding="utf-8")
    links = tmp_path / "links.parquet"; summary_json = tmp_path / "cgr.json"
    result = correlate_with_cgr(str(p), str(silver), str(links), str(summary_json))
    assert result["provider_links"] == 1
    row = pd.read_parquet(links).iloc[0]
    assert row["status"] == "CANDIDATE"
    assert row["cgr_finding_count"] == 1
    assert "no prueba" in row["match_basis"].lower()


def test_operational_signal_pipeline_outputs_priority_queue(tmp_path: Path):
    rows = []
    for i in range(24):
        rows.append({
            "PERIODO": "2025","MES": "6","PARTIDA": "08","NOMBRE_PARTIDA": "MINISTERIO EJEMPLO",
            "CAPITULO": "01","NOMBRE_CAPITULO": "SERVICIO EJEMPLO","AREA": "001","NOMBRE_AREA": "SERVICIO EJEMPLO",
            "SUBTITULO": "22","ITEM": "01","BENEFICIARIO": f"PRV-{i}","NOMBRE_BENEFICIARIO": f"PROVEEDOR {i} SPA",
            "NUMERO_DOCUMENTO": str(1000 + i),"FECHA_DOCUMENTO": f"2025-06-{(i % 20)+1:02d}",
            "FECHA_PAGO": "2025-08-30" if i == 0 else "2025-06-30",
            "DEVENGO": "200000000" if i == 0 else str(1000000 + i * 10000),
            "MONTO": "200000000" if i == 0 else str(1000000 + i * 10000),
            "PROVEEDOR": "1","PERSONA": "0","REGION": "Metropolitana","DIAS_DE_PAGO": "120" if i == 0 else "15",
        })
    df = normalize_frame(pd.DataFrame(rows), source_file="pagos-2025.gz")
    p = tmp_path / "facts.parquet"; df.to_parquet(p, index=False)
    sig = tmp_path / "signals.parquet"
    build_signals(str(p), output_path=str(sig), min_group=20)
    result = extend_signals(str(p), signals_path=str(sig), concentration_min_providers=3,
        concentration_min_share=0.40, concentration_min_hhi=0.15, concentration_min_amount=1,
        payment_delay_min_days=60, payment_delay_min_group=20, payment_delay_quantile=0.95)
    assert result["signals"] == result["distinct_signal_ids"]
    assert "AMOUNT_OUTLIER" in result["by_type"]
    assert "PROVIDER_CONCENTRATION" in result["by_type"]
    assert "PAYMENT_DELAY_OUTLIER" in result["by_type"]

    queue_p = tmp_path / "priority.parquet"; queue_j = tmp_path / "queue.json"
    q = prioritize_signals(str(p), signals_path=str(sig), cgr_links_path=str(tmp_path / "missing.parquet"),
        output_parquet=str(queue_p), output_json=str(queue_j))
    assert q["signals"] == result["signals"]
    priority = pd.read_parquet(queue_p)
    assert priority.investigation_priority_score.between(0, 100).all()
    assert set(priority.priority_tier).issubset({"P1", "P2", "P3"})
