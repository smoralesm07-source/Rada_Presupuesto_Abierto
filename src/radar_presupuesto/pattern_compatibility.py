from __future__ import annotations

"""El segundo eje: a qué hipótesis de revisión se parece un hallazgo.

Este eje es descriptivo y es independiente de la prioridad. Una relación puede
merecer revisión por razones que nada tienen que ver con una hipótesis concreta,
y mezclar las dos cosas es lo que produce una cola encabezada por una factura de
combustible.

Dos reglas lo mantienen honesto.

Una hipótesis necesita **corroboración**: dos patrones independientes que apunten
a lo mismo. Un solo patrón describe un hecho, no una hipótesis; proponer una
tipología con una sola señal es exactamente cómo un radar empieza a acusar.

Y cada perfil declara **qué lo descartaría**. Decir qué evidencia derriba la
hipótesis es lo que separa un producto analítico de una máquina de sospechas, y
es lo primero que pregunta quien recibe el expediente.
"""

from dataclasses import dataclass


GUARDRAIL = (
    "La compatibilidad de patrón describe cuánto se parece un hallazgo a una hipótesis analítica de revisión. "
    "No estima culpabilidad, corrupción, fraude, delito funcionario ni probabilidad de comisión de un ilícito."
)

# Una hipótesis se sostiene con dos patrones independientes, no con uno. Bajar
# este número reabre la puerta a proponer una tipología desde una sola señal.
MIN_CORROBORATING_PATTERNS = 2

CORROBORATION_NOTE = (
    "Un solo patrón coincidente describe un hecho aislado, no una hipótesis. "
    f"Se requieren al menos {MIN_CORROBORATING_PATTERNS} patrones concurrentes para proponer la hipótesis como línea de revisión."
)


@dataclass(frozen=True)
class PatternProfile:
    code: str
    label: str
    description: str
    weights: dict[str, int]
    review_question: str
    discards: tuple[str, ...]
    next_document: str


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
        discards=(
            "Los pagos son cuotas de un mismo contrato con calendario pactado: la repetición es el contrato, no una anomalía.",
            "La repetición documental viene de un mismo devengo registrado en más de una etapa presupuestaria.",
            "Los montos similares corresponden a precio unitario fijo de convenio marco, donde la uniformidad es esperable.",
            "Los pagos están respaldados por estados de pago distintos, con recepción conforme en fechas distintas.",
        ),
        next_document="Contrato o convenio vigente con su calendario de pagos, y las facturas y órdenes de pago del período.",
    ),
    PatternProfile(
        code="CONCENTRACION_COMPETENCIA",
        label="Concentración y competencia",
        description="Concentración del gasto o cambio relevante en la posición de un proveedor frente al organismo.",
        weights={
            "PROVIDER_CONCENTRATION": 50,
            "NEW_TO_SERIES_HIGH_SPEND": 25,
            "AMOUNT_OUTLIER": 25,
            "NEWBORN_SUPPLIER": 20,
            "CAPACITY_MISMATCH": 20,
        },
        review_question="¿La concentración se explica por mercado, modalidad, contrato o condiciones técnicas, o requiere revisar con mayor detalle la competencia y adjudicación?",
        discards=(
            "El rubro tiene un único proveedor habilitado o es monopolio natural en el territorio: la concentración es del mercado, no del organismo.",
            "La compra viene de convenio marco, donde el organismo no selecciona al proveedor.",
            "Hubo licitación pública con más de un oferente admisible en el período.",
            "El proveedor es otro organismo del Estado o una universidad estatal, donde la competencia no aplica.",
        ),
        next_document="Acto administrativo de adjudicación y acta de apertura con la nómina de oferentes.",
    ),
    PatternProfile(
        code="IRRUPCION_CAMBIO_ESCALA",
        label="Irrupción y cambio de escala",
        description="Proveedor que entra o aumenta su escala de forma material respecto de la serie observada.",
        weights={
            "NEW_TO_SERIES_HIGH_SPEND": 50,
            "AMOUNT_OUTLIER": 30,
            "PROVIDER_CONCENTRATION": 20,
            "NEWBORN_SUPPLIER": 35,
            "CAPACITY_MISMATCH": 25,
            "DORMANT_REACTIVATION": 25,
        },
        review_question="¿El crecimiento observado es compatible con la adjudicación, trayectoria y capacidad observable del proveedor?",
        discards=(
            "El proveedor cambió de RUT por fusión, división o cambio de razón social: la serie previa existe bajo otro identificador.",
            "El aumento coincide con una ampliación presupuestaria o un programa nuevo documentado.",
            "Es nuevo para este organismo pero tiene trayectoria adjudicada en otros servicios del Estado.",
            "La irrupción es el primer año de un contrato plurianual adjudicado por licitación.",
        ),
        next_document="Ficha del proveedor en Mercado Público con su historial de adjudicaciones, y la resolución que crea o amplía el programa.",
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
        discards=(
            "La concentración de fin de año es devengo contable de servicios prestados a lo largo del ejercicio.",
            "El plazo de pago se explica por observaciones documentadas a la factura o por rechazo y reemisión.",
            "Existe una reprogramación o modificación presupuestaria formal en el período.",
            "El organismo recibió la transferencia de fondos tarde y el pago siguió al ingreso efectivo.",
        ),
        next_document="Estado de pago con fecha de recepción conforme, y el decreto de modificación presupuestaria del período.",
    ),
    PatternProfile(
        code="CAPACIDAD_Y_TRAYECTORIA",
        label="Capacidad y trayectoria de la contraparte",
        description="Características registrales del proveedor que no encajan con la magnitud o el objeto de lo contratado.",
        weights={
            "CAPACITY_MISMATCH": 45,
            "TERMINATION_AFTER_PAYMENT": 40,
            "NEWBORN_SUPPLIER": 30,
            "ACTIVITY_MISMATCH": 25,
            "DORMANT_REACTIVATION": 20,
        },
        review_question="¿La capacidad declarada, el giro y la trayectoria registral del proveedor son consistentes con el objeto y la magnitud de lo contratado?",
        discards=(
            "El proveedor es intermediario o distribuidor autorizado: el tramo de ventas refleja margen, no el volumen que factura al Estado.",
            "El tramo SII corresponde a un año comercial anterior al pago y la empresa creció en el intervalo.",
            "El término de giro es una reorganización societaria con continuidad de obligaciones en otra sociedad.",
            "El giro fue ampliado formalmente antes de contratar y el registro publicado está desactualizado.",
            "La ausencia previa es del radar, no del proveedor: los años intermedios no están en la ventana procesada.",
        ),
        next_document="Carpeta tributaria con giros vigentes y tramo del año comercial pagado, más la escritura de constitución o el aviso de término de giro.",
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

    A single matching signal can never score above 60 and is never corroborated.
    Convergence is what drives higher compatibility. Scores are deliberately not
    calibrated probabilities.
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
        corroborated = len(matched) >= MIN_CORROBORATING_PATTERNS
        results.append(
            {
                "pattern_code": profile.code,
                "pattern_label": profile.label,
                "pattern_description": profile.description,
                "compatibility_score": int(score),
                "matched_signals": matched,
                "matched_signal_count": len(matched),
                "corroborated": corroborated,
                "evidence_status": "CORROBORADO" if corroborated else "SIN_CORROBORAR",
                "corroboration_note": None if corroborated else CORROBORATION_NOTE,
                "review_question": profile.review_question,
                "discards": list(profile.discards),
                "next_document": profile.next_document,
                "guardrail": GUARDRAIL,
            }
        )
    return sorted(
        results,
        key=lambda x: (not x["corroborated"], -x["compatibility_score"], x["pattern_code"]),
    )


def best_pattern(
    signal_types: object,
    minimum_score: int = 40,
    require_corroboration: bool = True,
) -> dict | None:
    """Return the leading hypothesis, or None when nothing corroborates one.

    `require_corroboration` exists so a caller that deliberately wants the raw
    descriptive ranking can ask for it. Publication never should: proposing a
    typology from a single signal is how a radar starts making accusations.
    """
    rows = score_pattern_compatibility(signal_types)
    if not rows:
        return None
    top = rows[0]
    if top["compatibility_score"] < minimum_score:
        return None
    if require_corroboration and not top["corroborated"]:
        return None
    return top
