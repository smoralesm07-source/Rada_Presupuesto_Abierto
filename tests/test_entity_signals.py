from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from radar_presupuesto.entity_signals import (
    build_entity_signals,
    entity_risk_by_provider,
    is_placeholder_rut,
    load_enrichment,
)

ENRICHMENT = Path("docs/data/entity_enrichment_v1.json")


def _facts(rows: list[dict], tmp_path: Path) -> str:
    frame = pd.DataFrame(rows)
    frame["is_provider"] = True
    frame["is_aggregated"] = False
    out = tmp_path / "transactions_test.parquet"
    frame.to_parquet(out, index=False)
    return str(out)


def _row(rut: str, periodo: int, amount: float, doc_date: str, subtitulo: str = "22") -> dict:
    return {
        "provider_id": f"PRV-RUT-{rut}",
        "nombre_beneficiario": f"PROVEEDOR {rut}",
        "organization_id": "ORG-PA-13-06-001",
        "periodo": periodo,
        "monto_devengado": amount,
        "fecha_documento": pd.Timestamp(doc_date),
        "subtitulo": subtitulo,
    }


def test_placeholder_ruts_are_never_entities():
    assert is_placeholder_rut("55555555-5")
    assert is_placeholder_rut("44444444-4")
    assert not is_placeholder_rut("78119977-K")
    assert not is_placeholder_rut("99520000-7")


@pytest.mark.skipif(not ENRICHMENT.exists(), reason="enriquecimiento SII no disponible")
def test_placeholder_rut_excluded_from_enrichment():
    entities = load_enrichment(ENRICHMENT)
    assert entities, "el enriquecimiento publicado debe traer entidades"
    assert "55555555-5" not in entities


def test_newborn_and_capacity_signals_fire(tmp_path):
    enrichment = {
        "entities": {
            "78119977-K": {
                "rut": "78119977-K",
                "entity_id": "ENT-RUT-78119977-K",
                "legal_name": "PIRCA CONSTRUCCIONES LIMITADA",
                "start_date": "2025-07-01",
                "termination_date": "",
                "sales_band_code": 4,
                "commercial_year": 2024,
                "acteco": [{"codigo": "410010"}],
            },
            "53310473-8": {
                "rut": "53310473-8",
                "entity_id": "ENT-RUT-53310473-8",
                "legal_name": "COMUNIDAD SIN VENTAS",
                "start_date": "2020-06-30",
                "termination_date": "",
                "sales_band_code": 1,
                "commercial_year": 2024,
                "acteco": [{"codigo": "949904"}],
            },
        }
    }
    path = tmp_path / "enrichment.json"
    path.write_text(json.dumps(enrichment), encoding="utf-8")

    facts = _facts(
        [
            _row("78119977-K", 2025, 900_000_000, "2025-09-15"),
            _row("53310473-8", 2025, 400_000_000, "2025-04-02"),
        ],
        tmp_path,
    )

    result = build_entity_signals(
        facts,
        enrichment_path=path,
        output_parquet=tmp_path / "entity_signals.parquet",
        config={"uf_clp_reference": 39_000.0},
    )
    frame = pd.read_parquet(result["path"])
    kinds = set(zip(frame["provider_id"], frame["signal_type"]))

    assert ("PRV-RUT-78119977-K", "NEWBORN_SUPPLIER") in kinds
    assert ("PRV-RUT-53310473-8", "CAPACITY_MISMATCH") in kinds

    newborn = frame[frame["signal_type"] == "NEWBORN_SUPPLIER"].iloc[0]
    assert newborn["severity"] == "HIGH"
    assert "inicio de actividades" in newborn["why_flagged"]
    assert "no acredita" in newborn["assumption"]
    assert newborn["record_class"] == "DERIVED_SIGNAL"
    assert "no constituyen por sí mismos indicio" in newborn["guardrail"]

    sin_ventas = frame[frame["signal_type"] == "CAPACITY_MISMATCH"].iloc[0]
    assert "sin ventas declaradas" in sin_ventas["why_flagged"]


def test_top_sales_band_never_triggers_capacity_mismatch(tmp_path):
    enrichment = {
        "entities": {
            "99520000-7": {
                "rut": "99520000-7",
                "legal_name": "GRAN PROVEEDOR",
                "start_date": "1990-01-01",
                "sales_band_code": 13,
                "acteco": [{"codigo": "192000"}],
            }
        }
    }
    path = tmp_path / "enrichment.json"
    path.write_text(json.dumps(enrichment), encoding="utf-8")
    facts = _facts([_row("99520000-7", 2026, 48_000_000_000, "2026-01-10")], tmp_path)

    result = build_entity_signals(
        facts, enrichment_path=path, output_parquet=tmp_path / "s.parquet"
    )
    frame = pd.read_parquet(result["path"])
    assert "CAPACITY_MISMATCH" not in set(frame["signal_type"])


def test_termination_and_dormancy(tmp_path):
    enrichment = {
        "entities": {
            "76071943-9": {
                "rut": "76071943-9",
                "legal_name": "CIERRA DESPUES DE COBRAR",
                "start_date": "2015-01-01",
                "termination_date": "2026-03-01",
                "sales_band_code": 8,
                "acteco": [{"codigo": "620100"}],
            },
            "77111222-6": {
                "rut": "77111222-6",
                "legal_name": "REAPARECE",
                "start_date": "2010-01-01",
                "termination_date": "",
                "sales_band_code": 9,
                "acteco": [{"codigo": "620100"}],
            },
        }
    }
    path = tmp_path / "enrichment.json"
    path.write_text(json.dumps(enrichment), encoding="utf-8")
    facts = _facts(
        [
            _row("76071943-9", 2025, 800_000_000, "2025-11-20"),
            _row("77111222-6", 2020, 60_000_000, "2020-05-01"),
            _row("77111222-6", 2026, 700_000_000, "2026-02-01"),
        ],
        tmp_path,
    )

    result = build_entity_signals(
        facts, enrichment_path=path, output_parquet=tmp_path / "s.parquet"
    )
    frame = pd.read_parquet(result["path"])
    kinds = set(zip(frame["provider_id"], frame["signal_type"]))
    assert ("PRV-RUT-76071943-9", "TERMINATION_AFTER_PAYMENT") in kinds
    assert ("PRV-RUT-77111222-6", "DORMANT_REACTIVATION") in kinds

    dormant = frame[frame["signal_type"] == "DORMANT_REACTIVATION"].iloc[0]
    assert "sólo sobre los años efectivamente procesados" in dormant["assumption"]

    risk = entity_risk_by_provider(result["path"])
    assert set(risk["provider_id"]) == {"PRV-RUT-76071943-9", "PRV-RUT-77111222-6"}
    assert (risk["entity_risk_weight"] > 0).all()
    assert (risk["entity_risk_weight"] <= 10).all()


def test_no_enrichment_yields_no_entity_signals(tmp_path):
    path = tmp_path / "enrichment.json"
    path.write_text(json.dumps({"entities": {}}), encoding="utf-8")
    facts = _facts([_row("76071943-9", 2025, 800_000_000, "2025-11-20")], tmp_path)
    result = build_entity_signals(
        facts, enrichment_path=path, output_parquet=tmp_path / "s.parquet"
    )
    assert result["signals"] == 0
    assert result["registry_coverage"] == 0.0
