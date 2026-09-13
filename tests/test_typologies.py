from __future__ import annotations

import json

import pandas as pd
import pytest

from radar_presupuesto.typologies import (
    GUARDRAIL,
    OBSERVABLE_LAYERS,
    PATTERN_LAYER,
    TYPOLOGIES,
    TYPOLOGY_BY_CODE,
    alignment_level,
    match_all,
    match_typology,
)


def test_every_typology_says_what_would_rule_it_out():
    """Una tipología sin criterio de descarte es una acusación, no una hipótesis."""
    for typology in TYPOLOGIES:
        assert typology.sustains, f"{typology.code} sin criterios que la sostengan"
        assert typology.discards, f"{typology.code} sin criterios que la descarten"
        assert typology.documents, f"{typology.code} sin documentos que pedir"
        assert typology.question.endswith("?")


def test_shell_supplier_matches_from_entity_layer_alone():
    patterns = {"NEWBORN_SUPPLIER", "CAPACITY_MISMATCH", "PROVIDER_CONCENTRATION"}
    match = match_typology(TYPOLOGY_BY_CODE["PROVEEDOR_FACHADA"], patterns)
    assert match is not None
    assert match["score"] > 0
    assert "NEWBORN_SUPPLIER" in match["matched_patterns"]
    assert match["discards"]
    assert match["documents"]


def test_anchor_is_required_not_merely_reinforcing():
    # Sólo refuerzos, sin ningún ancla: no debe configurarse la tipología.
    assert match_typology(TYPOLOGY_BY_CODE["PROVEEDOR_FACHADA"], {"PROVIDER_CONCENTRATION"}) is None
    # Un ancla incompleta tampoco basta: exige ambos grupos.
    assert match_typology(TYPOLOGY_BY_CODE["PROVEEDOR_FACHADA"], {"NEWBORN_SUPPLIER"}) is None


def test_typologies_needing_procurement_declare_the_gap():
    colusion = TYPOLOGY_BY_CODE["COLUSION_DE_OFERENTES"]
    assert not colusion.anchorable_now, (
        "colusión depende del proceso de compra y no debe poder configurarse todavía"
    )
    assert "PROCESO_DE_COMPRA" in colusion.missing_layers
    assert colusion.evidence_ceiling < 1.0
    # Ni siquiera con todos sus patrones simulados debe aparecer como alcanzable hoy.
    assert match_typology(colusion, set(colusion.patterns))["score"] <= 100 * colusion.evidence_ceiling


def test_score_never_exceeds_the_evidence_ceiling():
    for typology in TYPOLOGIES:
        match = match_typology(typology, set(typology.patterns))
        if match is None:
            continue
        assert match["score"] <= 100 * typology.evidence_ceiling + 1e-6, typology.code


def test_fully_observable_typology_can_reach_the_top():
    extraccion = TYPOLOGY_BY_CODE["EXTRACCION_Y_DISOLUCION"]
    assert extraccion.anchorable_now
    match = match_typology(extraccion, set(extraccion.patterns))
    assert match["score"] >= 70
    assert alignment_level(match["score"]) == "ALTO"


def test_pattern_layers_are_complete():
    for typology in TYPOLOGIES:
        for pattern in typology.patterns:
            assert pattern in PATTERN_LAYER, f"{pattern} sin capa declarada"


def test_match_all_orders_by_score():
    matches = match_all(
        {
            "NEWBORN_SUPPLIER",
            "CAPACITY_MISMATCH",
            "TERMINATION_AFTER_PAYMENT",
            "PROVIDER_CONCENTRATION",
            "AMOUNT_OUTLIER",
        }
    )
    assert len(matches) >= 2
    scores = [m["score"] for m in matches]
    assert scores == sorted(scores, reverse=True)
    for match in matches:
        assert match["sustains"] and match["discards"] and match["documents"]


def test_alignment_levels():
    assert alignment_level(85) == "ALTO"
    assert alignment_level(50) == "MEDIO"
    assert alignment_level(30) == "BAJO"
    assert alignment_level(0) == "NULO"


def test_guardrail_refuses_to_imply_guilt():
    lowered = GUARDRAIL.lower()
    assert "hipótesis de trabajo" in lowered
    assert "no una imputación" in lowered
    assert "no la probabilidad" in lowered
    assert "responsabilidad" in lowered


def test_a_single_pattern_never_proposes_a_typology():
    """Sobre-afirmar es el riesgo principal de esta capa.

    Un monto atípico aislado no es 'sobreprecio y desvío': sin un segundo patrón
    concurrente la tipología no se propone, y la relación queda sin hipótesis.
    """
    assert match_typology(TYPOLOGY_BY_CODE["SOBREPRECIO_Y_DESVIO"], {"AMOUNT_OUTLIER"}) is None
    assert match_all({"AMOUNT_OUTLIER"}) == []
    assert match_typology(TYPOLOGY_BY_CODE["EXTRACCION_Y_DISOLUCION"], {"TERMINATION_AFTER_PAYMENT"}) is None

    # Con un segundo patrón concurrente sí se configura.
    corroborated = match_typology(
        TYPOLOGY_BY_CODE["SOBREPRECIO_Y_DESVIO"], {"AMOUNT_OUTLIER", "CAPACITY_MISMATCH"}
    )
    assert corroborated is not None
    assert len(corroborated["matched_patterns"]) >= 2
