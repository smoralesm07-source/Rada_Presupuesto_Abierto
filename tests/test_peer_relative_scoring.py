"""La inversión de ranking que justifica el scoring relativo a pares.

Un pago enorme que es perfectamente corriente en su propio mercado no debería
ganarle a un pago chico que no se parece a nada de su grupo. Con tramos absolutos
en CLP y puntos fijos por tipo de señal, le ganaba.
"""
from pathlib import Path

import pandas as pd
import pytest

from radar_presupuesto.peer_groups import build_provider_peer_context
from radar_presupuesto.prioritization import prioritize_signals

COMMON = "PRV-COMBUSTIBLE-09"   # grande en plata, mediano entre sus pares, patrón ubicuo
RARE = "PRV-RARO"               # chico en plata, 27x la mediana de su grupo, patrón único


def _fact(tx, org, provider, periodo, subtitulo, item, amount):
    return {
        "transaction_id": tx,
        "organization_id": org,
        "provider_id": provider,
        "recipient_id": provider,
        "periodo": periodo,
        "mes": 6,
        "subtitulo": subtitulo,
        "item": item,
        "nombre_partida": org,
        "nombre_capitulo": org,
        "nombre_area": org,
        "nombre_beneficiario": provider,
        "monto_devengado": float(amount),
        "orden_compra": "",
        "codigo_bip": "",
        "region": "RM",
        "is_provider": True,
        "is_aggregated": False,
    }


def _signal(provider, org, tx, periodo, signal_type):
    return {
        "signal_id": f"{signal_type}-{provider}",
        "signal_type": signal_type,
        "transaction_id": tx,
        "organization_id": org,
        "recipient_id": provider,
        "provider_id": provider,
        "periodo": periodo,
        "mes": 6,
        "observed_value": 1.0,
        "expected_value": 1.0,
        "deviation": 1.0,
        "severity": "MEDIUM",
        "confidence": "MEDIUM",
        "record_class": "DERIVED_SIGNAL",
        "why_flagged": "fixture",
    }


@pytest.fixture
def scenario(tmp_path: Path):
    """Dos grupos de pares del mismo año, uno saturado de señales y otro casi limpio."""
    facts, signals = [], []

    # ORG-A, combustibles: 20 proveedores grandes y parecidos entre sí, todos con
    # AMOUNT_OUTLIER. El patrón es la norma del grupo, no la excepción.
    for i in range(20):
        pid = f"PRV-COMBUSTIBLE-{i:02d}"
        tx = f"TX-A-{i:02d}"
        facts.append(_fact(tx, "ORG-A", pid, 2026, "22", "08", 4_000_000_000 + i * 50_000_000))
        signals.append(_signal(pid, "ORG-A", tx, 2026, "AMOUNT_OUTLIER"))

    # ORG-B, servicios menores: 20 proveedores chicos; sólo uno carga la señal.
    for i in range(19):
        pid = f"PRV-SERVICIO-{i:02d}"
        facts.append(_fact(f"TX-B-{i:02d}", "ORG-B", pid, 2026, "22", "04", 1_000_000 + i * 10_000))
    facts.append(_fact("TX-B-RARO", "ORG-B", RARE, 2026, "22", "04", 30_000_000))
    signals.append(_signal(RARE, "ORG-B", "TX-B-RARO", 2026, "EXACT_DUPLICATE_CANDIDATE"))

    facts_path = tmp_path / "facts.parquet"
    signals_path = tmp_path / "signals.parquet"
    pd.DataFrame(facts).to_parquet(facts_path, index=False)
    pd.DataFrame(signals).to_parquet(signals_path, index=False)
    return tmp_path, facts_path, signals_path


def _run(tmp_path, facts_path, signals_path, peer_path, tag):
    prioritize_signals(
        str(facts_path),
        signals_path=str(signals_path),
        cgr_links_path=str(tmp_path / "missing_cgr.parquet"),
        peer_context_path=str(peer_path),
        output_parquet=str(tmp_path / f"priority_{tag}.parquet"),
        output_json=str(tmp_path / f"queue_{tag}.json"),
    )
    df = pd.read_parquet(tmp_path / f"priority_{tag}.parquet").set_index("provider_id")
    return df


def test_peer_context_inverts_the_absolute_amount_ranking(scenario):
    tmp_path, facts_path, signals_path = scenario

    # Sin contexto de pares: tramos absolutos en CLP y puntos fijos por tipo.
    before = _run(tmp_path, facts_path, signals_path, tmp_path / "no_peers.parquet", "sin")
    assert set(before.scoring_basis) == {"PRIOR_POR_TIPO"}
    assert before.loc[COMMON, "investigation_priority_score"] > before.loc[RARE, "investigation_priority_score"]

    # Con contexto de pares: rareza empírica y materialidad relativa a la mediana.
    peer_path = tmp_path / "peers.parquet"
    build_provider_peer_context(str(facts_path), str(peer_path), min_peer_providers=5)
    after = _run(tmp_path, facts_path, signals_path, peer_path, "con")
    assert set(after.scoring_basis) == {"PARES"}
    assert after.loc[RARE, "investigation_priority_score"] > after.loc[COMMON, "investigation_priority_score"]


def test_ubiquitous_pattern_earns_no_rarity_and_typical_size_earns_no_materiality(scenario):
    tmp_path, facts_path, signals_path = scenario
    peer_path = tmp_path / "peers.parquet"
    build_provider_peer_context(str(facts_path), str(peer_path), min_peer_providers=5)
    after = _run(tmp_path, facts_path, signals_path, peer_path, "con")

    common = after.loc[COMMON]
    assert common.peer_signal_prevalence == pytest.approx(1.0)
    assert common.rarity_component == 0
    assert common.relative_materiality_component == 0
    assert common.transaction_amount >= 1_000_000_000  # seguía siendo un pago enorme

    rare = after.loc[RARE]
    assert rare.peer_signal_prevalence == pytest.approx(0.05)
    assert rare.rarity_component >= 9
    assert rare.relative_materiality_component >= 7
    assert rare.transaction_amount < 100_000_000  # y este seguía siendo un pago chico


def test_explanation_names_the_peer_group_or_declares_it_could_not_measure(scenario):
    tmp_path, facts_path, signals_path = scenario
    peer_path = tmp_path / "peers.parquet"
    build_provider_peer_context(str(facts_path), str(peer_path), min_peer_providers=5)
    after = _run(tmp_path, facts_path, signals_path, peer_path, "con")

    explained = after.loc[RARE, "priority_explanation"]
    assert "1 de 20 proveedores del grupo PEER-" in explained
    assert "la mediana del grupo" in explained

    before = _run(tmp_path, facts_path, signals_path, tmp_path / "no_peers.parquet", "sin")
    fallback = before.loc[RARE, "priority_explanation"]
    assert "sin pares suficientes para medirla" in fallback
    assert "sin grupo de pares comparable" in fallback


def test_small_peer_group_falls_back_instead_of_faking_a_comparison(tmp_path: Path):
    facts = [
        _fact(f"TX-{i}", "ORG-C", f"PRV-{i}", 2026, "22", "08", 1_000_000 * (i + 1))
        for i in range(3)
    ]
    signals = [_signal("PRV-0", "ORG-C", "TX-0", 2026, "AMOUNT_OUTLIER")]
    facts_path = tmp_path / "facts.parquet"
    signals_path = tmp_path / "signals.parquet"
    pd.DataFrame(facts).to_parquet(facts_path, index=False)
    pd.DataFrame(signals).to_parquet(signals_path, index=False)

    peer_path = tmp_path / "peers.parquet"
    build_provider_peer_context(str(facts_path), str(peer_path), min_peer_providers=5)
    df = _run(tmp_path, facts_path, signals_path, peer_path, "chico")

    # El grupo existe pero no alcanza a ser comparable: la fila lo declara.
    assert df.loc["PRV-0", "scoring_basis"] == "PRIOR_POR_TIPO"
    assert df.loc["PRV-0", "rarity_component"] == 15  # prior del tipo AMOUNT_OUTLIER
    assert "sin pares suficientes" in df.loc["PRV-0", "priority_explanation"]
