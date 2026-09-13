from radar_presupuesto.pattern_compatibility import best_pattern, score_pattern_compatibility


def test_single_signal_does_not_create_extreme_typology_score():
    rows = score_pattern_compatibility(["PROVIDER_CONCENTRATION"])
    top = rows[0]
    assert top["pattern_code"] == "CONCENTRACION_COMPETENCIA"
    assert top["compatibility_score"] <= 60
    assert "no estima culpabilidad" in top["guardrail"].lower()


def test_convergence_increases_descriptive_compatibility():
    top = best_pattern(
        ["PROVIDER_CONCENTRATION", "NEW_TO_SERIES_HIGH_SPEND", "AMOUNT_OUTLIER"]
    )
    assert top is not None
    assert top["pattern_code"] in {"CONCENTRACION_COMPETENCIA", "IRRUPCION_CAMBIO_ESCALA"}
    assert top["compatibility_score"] >= 90
    assert len(top["matched_signals"]) == 3


def test_priority_is_not_an_input_to_pattern_compatibility():
    a = best_pattern(["POTENTIAL_FRAGMENTATION", "EXACT_DUPLICATE_CANDIDATE"])
    b = best_pattern("POTENTIAL_FRAGMENTATION|EXACT_DUPLICATE_CANDIDATE")
    assert a == b
    assert a["pattern_code"] == "INTEGRIDAD_DOCUMENTAL"


def test_unknown_signals_do_not_invent_a_pattern():
    assert best_pattern(["UNSUPPORTED_SIGNAL"]) is None
