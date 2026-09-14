"""Una sola señal describe un hecho; no propone una hipótesis.

Medido sobre `docs/data/investigation_queue.json`, 51 de las 52 hipótesis
publicadas venían de un único patrón. Eso no es un eje de tipologías: es una
señal técnica con nombre de hipótesis.
"""
import pytest

from radar_presupuesto.pattern_compatibility import (
    MIN_CORROBORATING_PATTERNS,
    PROFILES,
    best_pattern,
    score_pattern_compatibility,
)

SINGLE_SIGNAL_CASES = [
    # (señal, perfil que proponía por sí sola, score que alcanzaba)
    ("PROVIDER_CONCENTRATION", "CONCENTRACION_COMPETENCIA", 50),
    ("YEAR_END_SPIKE", "EJECUCION_TEMPORAL", 60),
    ("POTENTIAL_FRAGMENTATION", "INTEGRIDAD_DOCUMENTAL", 45),
    ("NEW_TO_SERIES_HIGH_SPEND", "IRRUPCION_CAMBIO_ESCALA", 50),
]


@pytest.mark.parametrize("signal,expected_code,expected_score", SINGLE_SIGNAL_CASES)
def test_one_signal_no_longer_proposes_a_hypothesis(signal, expected_code, expected_score):
    # El parecido sigue siendo visible y sigue puntuando por encima del umbral...
    rows = score_pattern_compatibility([signal])
    top = next(x for x in rows if x["pattern_code"] == expected_code)
    assert top["compatibility_score"] == expected_score
    assert top["compatibility_score"] >= 40
    assert top["evidence_status"] == "SIN_CORROBORAR"
    assert top["corroborated"] is False
    assert "no es una hipótesis" not in (top["corroboration_note"] or "")
    assert str(MIN_CORROBORATING_PATTERNS) in (top["corroboration_note"] or "")

    # ...pero ya no se propone como hipótesis.
    assert best_pattern([signal]) is None


def test_two_concurrent_patterns_do_sustain_the_hypothesis():
    top = best_pattern(["POTENTIAL_FRAGMENTATION", "EXACT_DUPLICATE_CANDIDATE"])
    assert top is not None
    assert top["pattern_code"] == "INTEGRIDAD_DOCUMENTAL"
    assert top["corroborated"] is True
    assert top["evidence_status"] == "CORROBORADO"
    assert top["corroboration_note"] is None
    assert top["matched_signal_count"] == 2


def test_the_raw_descriptive_ranking_is_still_reachable():
    """La regla cambia lo que el sistema afirma, no lo que puede mostrar."""
    strict = best_pattern(["PROVIDER_CONCENTRATION"])
    loose = best_pattern(["PROVIDER_CONCENTRATION"], require_corroboration=False)
    assert strict is None
    assert loose is not None
    assert loose["pattern_code"] == "CONCENTRACION_COMPETENCIA"
    assert loose["corroborated"] is False


@pytest.mark.parametrize(
    "signals",
    [
        ["PROVIDER_CONCENTRATION"],
        ["YEAR_END_SPIKE", "PAYMENT_DELAY_OUTLIER"],
        ["POTENTIAL_FRAGMENTATION", "PAYMENT_DELAY_OUTLIER"],
        ["AMOUNT_OUTLIER", "NEW_TO_SERIES_HIGH_SPEND", "YEAR_END_SPIKE"],
        [],
    ],
)
def test_corroborated_profiles_always_sort_ahead_of_uncorroborated_ones(signals):
    rows = score_pattern_compatibility(signals)
    flags = [r["corroborated"] for r in rows]
    assert flags == sorted(flags, reverse=True), "un perfil sin corroborar quedó por delante de uno corroborado"


def test_every_profile_says_what_would_discard_it_and_what_to_request_next():
    """Decir qué derriba la hipótesis es lo que la hace defendible."""
    for profile in PROFILES:
        assert len(profile.discards) >= 3, f"{profile.code} no declara criterios de descarte suficientes"
        assert all(d.strip().endswith(".") for d in profile.discards), f"{profile.code} tiene descartes sin redactar"
        assert profile.next_document.strip().endswith("."), f"{profile.code} no indica el documento a pedir"
        assert profile.review_question.strip().endswith("?"), f"{profile.code} no plantea una pregunta de revisión"


def test_discards_travel_with_every_scored_row():
    for row in score_pattern_compatibility(["PROVIDER_CONCENTRATION", "AMOUNT_OUTLIER"]):
        assert row["discards"], f"{row['pattern_code']} publicado sin criterios de descarte"
        assert row["next_document"]
        assert "no estima culpabilidad" in row["guardrail"].lower()
