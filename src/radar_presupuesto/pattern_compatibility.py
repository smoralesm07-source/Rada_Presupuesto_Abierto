from __future__ import annotations

from dataclasses import dataclass


GUARDRAIL = (
    "La compatibilidad de patrón describe cuánto se parece un hallazgo a una hipótesis analítica de revisión. "
    "No estima culpabilidad, corrupción, fraude, delito funcionario ni probabilidad de comisión de un ilícito."
)


@dataclass(frozen=True)
class PatternProfile:
    code: str
    label: str
    description: str
    weights: dict[str, int]
    review_question: str


PROFILES = (
    PatternProfile(
        code="INTEGRIDAD_DOCUMENTAL",
        label="Integridad documental y secuencia de pagos",
        description="Reiteración, similitud o comportamiento documental que requiere reconstruir documentos y pagos.",
        weights={
            "POTENTIAL_FRAGMENTATION": 45,
            "EXACT_DUPLICATE_CANDIDATE": 45,
            "PAYMENT_DELAY_OUTLIER": 10,
        },
        review_question="¿La secuencia documental corresponde a hitos legítimos o existen repeticiones/materialidades que requieren explicación adicional?",
    ),
    PatternProfile(
        code="CONCENTRACION_COMPETENCIA",
        label="Concentración y competencia",
        description="Concentración del gasto o cambio relevante en la posición de un proveedor frente al organismo.",
        weights={
            "PROVIDER_CONCENTRATION": 50,
            "NEW_TO_SERIES_HIGH_SPEND": 25,
            "AMOUNT_OUTLIER": 25,
        },
        review_question="¿La concentración se explica por mercado, modalidad, contrato o condiciones técnicas, o requiere revisar con mayor detalle la competencia y adjudicación?",
    ),
    PatternProfile(
        code="IRRUPCION_CAMBIO_ESCALA",
        label="Irrupción y cambio de escala",
        description="Proveedor que entra o aumenta su escala de forma material respecto de la serie observada.",
        weights={
            "NEW_TO_SERIES_HIGH_SPEND": 50,
            "AMOUNT_OUTLIER": 30,
            "PROVIDER_CONCENTRATION": 20,
        },
        review_question="¿El crecimiento observado es compatible con la adjudicación, trayectoria y capacidad observable del proveedor?",
    ),
    PatternProfile(
        code="EJECUCION_TEMPORAL",
        label="Ejecución temporal y contractual",
        description="Patrones de cierre presupuestario o plazos contractuales que requieren contexto de ejecución.",
        weights={
            "YEAR_END_SPIKE": 60,
            "PAYMENT_DELAY_OUTLIER": 40,
        },
        review_question="¿La temporalidad se explica por calendario presupuestario y contractual o existen antecedentes que justifican una revisión dirigida?",
    ),
)


def _signals(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(x) for x in value if str(x)}
    return {x for x in str(value).split("|") if x}


def score_pattern_compatibility(signal_types: object) -> list[dict]:
    """Return descriptive pattern compatibility, fully independent from priority.

    A single matching signal can never score above 60. Convergence is what drives
    higher compatibility. Scores are deliberately not calibrated probabilities.
    """
    signals = _signals(signal_types)
    results = []
    for profile in PROFILES:
        matched = sorted(signals.intersection(profile.weights))
        raw = sum(profile.weights[s] for s in matched)
        if len(matched) == 1:
            score = min(60, raw)
        else:
            score = min(100, raw)
        results.append(
            {
                "pattern_code": profile.code,
                "pattern_label": profile.label,
                "pattern_description": profile.description,
                "compatibility_score": int(score),
                "matched_signals": matched,
                "review_question": profile.review_question,
                "guardrail": GUARDRAIL,
            }
        )
    return sorted(results, key=lambda x: (-x["compatibility_score"], x["pattern_code"]))


def best_pattern(signal_types: object, minimum_score: int = 40) -> dict | None:
    rows = score_pattern_compatibility(signal_types)
    if not rows or rows[0]["compatibility_score"] < minimum_score:
        return None
    return rows[0]
