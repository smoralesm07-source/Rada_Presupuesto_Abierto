from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from radar_presupuesto.prioritization import DEFAULT_TOP_N, prioritize_signals

SIGNAL_COLUMNS = [
    "signal_id", "signal_type", "transaction_id", "organization_id", "recipient_id",
    "provider_id", "periodo", "mes", "observed_value", "expected_value", "deviation",
    "severity", "confidence", "record_class", "why_flagged", "investigation_hypothesis",
    "recommended_checks",
]


def _fact(org: str, provider: str, amount: float, tx: str, subtitulo: str = "22") -> dict:
    return {
        "transaction_id": tx,
        "organization_id": org,
        "provider_id": provider,
        "recipient_id": provider.replace("PRV", "RCV"),
        "periodo": 2026,
        "mes": 6,
        "subtitulo": subtitulo,
        "monto_devengado": amount,
        "nombre_beneficiario": provider,
        "nombre_area": org,
        "nombre_capitulo": org,
        "nombre_partida": org,
        "orden_compra": "",
        "codigo_bip": "",
        "region": "13",
        "is_aggregated": False,
    }


def _signal(kind: str, org: str, provider: str, tx: str, severity: str = "HIGH") -> dict:
    return {
        "signal_id": f"SIG-{kind}-{org}-{provider}",
        "signal_type": kind,
        "transaction_id": tx,
        "organization_id": org,
        "recipient_id": provider.replace("PRV", "RCV"),
        "provider_id": provider,
        "periodo": 2026,
        "mes": 6,
        "observed_value": 1.0,
        "expected_value": 1.0,
        "deviation": 1.0,
        "severity": severity,
        "confidence": "MEDIUM",
        "record_class": "DERIVED_SIGNAL",
        "why_flagged": "test",
        "investigation_hypothesis": "test",
        "recommended_checks": "[]",
    }


def _build_world(tmp_path: Path):
    """A large ordinary payment against a genuinely rare one.

    ORG-BIG mirrors the COPEC case: a high-spend body where large payments and
    amount outliers are completely normal. ORG-SMALL is a modest body where the
    same pattern almost never happens.
    """
    facts: list[dict] = []
    signals: list[dict] = []

    for i in range(40):
        provider = f"PRV-RUT-BIG{i:02d}"
        tx = f"TRX-BIG-{i:02d}"
        facts.append(_fact("ORG-BIG", provider, 1_000_000_000, tx))
        if i < 30:  # el patrón es la norma en este grupo de pares
            signals.append(_signal("AMOUNT_OUTLIER", "ORG-BIG", provider, tx))

    for i in range(40):
        provider = f"PRV-RUT-SML{i:02d}"
        tx = f"TRX-SML-{i:02d}"
        amount = 300_000_000 if i == 0 else 5_000_000
        facts.append(_fact("ORG-SMALL", provider, amount, tx))
    signals.append(_signal("AMOUNT_OUTLIER", "ORG-SMALL", "PRV-RUT-SML00", "TRX-SML-00"))

    facts_path = tmp_path / "transactions.parquet"
    pd.DataFrame(facts).to_parquet(facts_path, index=False)
    signals_path = tmp_path / "risk_signals.parquet"
    pd.DataFrame(signals, columns=SIGNAL_COLUMNS).to_parquet(signals_path, index=False)
    return str(facts_path), str(signals_path)


def test_rare_pattern_outranks_large_ordinary_payment(tmp_path):
    facts, signals = _build_world(tmp_path)
    prioritize_signals(
        facts,
        signals_path=signals,
        cgr_links_path=str(tmp_path / "absent.parquet"),
        entity_signals_path=str(tmp_path / "absent_entity.parquet"),
        output_parquet=str(tmp_path / "prioritized.parquet"),
        output_json=str(tmp_path / "queue.json"),
    )
    frame = pd.read_parquet(tmp_path / "prioritized.parquet")
    big = frame[frame["organization_id"] == "ORG-BIG"]
    small = frame[frame["organization_id"] == "ORG-SMALL"].iloc[0]

    # El patrón frecuente en su grupo de pares casi no aporta rareza.
    assert big["pattern_prevalence"].max() <= 0.80
    assert small["pattern_prevalence"] < 0.05
    assert small["rarity_component"] > big["rarity_component"].max()
    assert small["review_priority_score"] > big["review_priority_score"].max(), (
        "un patrón raro en su grupo de pares debe superar a uno frecuente"
    )


def test_absolute_amount_alone_does_not_win(tmp_path):
    """El pago grande es 3x el pago raro y aun así no debe encabezar la cola."""
    facts, signals = _build_world(tmp_path)
    prioritize_signals(
        facts,
        signals_path=signals,
        cgr_links_path=str(tmp_path / "absent.parquet"),
        entity_signals_path=str(tmp_path / "absent_entity.parquet"),
        output_parquet=str(tmp_path / "prioritized.parquet"),
        output_json=str(tmp_path / "queue.json"),
    )
    queue = json.loads((tmp_path / "queue.json").read_text(encoding="utf-8"))
    top = queue["queue"][0]
    assert top["organization_id"] == "ORG-SMALL"
    assert float(top["transaction_amount"]) < 1_000_000_000


def test_peer_group_and_prevalence_are_explained(tmp_path):
    facts, signals = _build_world(tmp_path)
    prioritize_signals(
        facts,
        signals_path=signals,
        cgr_links_path=str(tmp_path / "absent.parquet"),
        entity_signals_path=str(tmp_path / "absent_entity.parquet"),
        output_parquet=str(tmp_path / "prioritized.parquet"),
        output_json=str(tmp_path / "queue.json"),
    )
    queue = json.loads((tmp_path / "queue.json").read_text(encoding="utf-8"))
    explanation = queue["queue"][0]["priority_explanation"]
    assert "rareza=" in explanation
    assert "prevalencia" in explanation
    assert "materialidad_relativa=" in explanation
    assert queue["schema"] == "RIGP-INVESTIGATION-QUEUE-v2"
    assert "no acredita irregularidad" in queue["guardrail"].lower()
    assert queue["peer_group_definition"]
    assert "laft_compatibility_score" in queue["axes"]


def test_publication_keeps_every_family_alive(tmp_path):
    """El corte por score no puede borrar familias completas de la cola."""
    facts: list[dict] = []
    signals: list[dict] = []
    for i in range(60):
        provider = f"PRV-RUT-A{i:02d}"
        tx = f"TRX-A-{i:02d}"
        facts.append(_fact("ORG-A", provider, 900_000_000, tx))
        signals.append(_signal("AMOUNT_OUTLIER", "ORG-A", provider, tx))
    # Una familia entera, individualmente más débil, que antes desaparecía.
    for i in range(20):
        provider = f"PRV-RUT-B{i:02d}"
        tx = f"TRX-B-{i:02d}"
        facts.append(_fact("ORG-A", provider, 4_000_000, tx))
        signals.append(
            _signal("POTENTIAL_FRAGMENTATION", "ORG-A", provider, tx, severity="MEDIUM")
        )

    facts_path = tmp_path / "f.parquet"
    pd.DataFrame(facts).to_parquet(facts_path, index=False)
    signals_path = tmp_path / "s.parquet"
    pd.DataFrame(signals, columns=SIGNAL_COLUMNS).to_parquet(signals_path, index=False)

    result = prioritize_signals(
        str(facts_path),
        signals_path=str(signals_path),
        cgr_links_path=str(tmp_path / "absent.parquet"),
        entity_signals_path=str(tmp_path / "absent_entity.parquet"),
        output_parquet=str(tmp_path / "p.parquet"),
        output_json=str(tmp_path / "q.json"),
        top_n=20,
    )
    families = result["published_families"]
    assert "DOCUMENTOS_Y_PAGOS" in families, (
        "la cuota por familia debe impedir que una familia entera desaparezca"
    )
    assert families["DOCUMENTOS_Y_PAGOS"] >= 1
    assert result["published_signals"] == 20


def test_default_publication_is_not_capped_at_250():
    assert DEFAULT_TOP_N == 5000
