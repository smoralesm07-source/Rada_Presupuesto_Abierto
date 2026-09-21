"""Una marca que aparece en casi todo dejó de ser una marca.

El nivel de atención se decidía con un umbral absoluto:

    (signal_family_count >= 2 AND max_priority_score >= 70)  →  ATENCION_INMEDIATA

Medido sobre las 390 relaciones publicadas, esa sola condición dispara en el
**95,1%**. No es un error de umbral: es un error de población. La selección para
publicar ya eligió las relaciones de score alto —el score va de 53 a 92 con
mediana 87—, así que volver a cortarlas en 70 no distingue nada. Un nivel que
aplica a 372 de 390 es una etiqueta, no una prioridad, y el analista pierde el
único orden que el sistema le ofrecía.

Es el mismo defecto que este motor ya corrigió dos veces: un corte absoluto
sobre una población preseleccionada por ser extrema.

Aquí el nivel se decide por **marcas distintivas**, y una marca sólo cuenta si
es rara en la bandeja que se está publicando. La prevalencia se mide en cada
corrida, así que si una marca se vuelve común deja de contar sola, sin que nadie
edite un número. Es lo contrario de un umbral fijo: la regla se entera de que
dejó de discriminar.

Las marcas y su prevalencia observada el 2026-09-21:

    tres o más familias de señal      4,6%
    cruce candidato con la CGR       10,0%
    tres o más tipos de señal        17,7%
    prioridad en el decil superior   ~10%
    monto en el decil superior       ~10%
"""
from __future__ import annotations

IMMEDIATE = "ATENCION_INMEDIATA"
PRIORITY = "REVISION_PRIORITARIA"
FOLLOW = "SEGUIMIENTO"

# Una marca presente en más de un tercio de la bandeja no separa a nadie de
# nadie. Por sobre este techo se declara agotada y deja de sumar.
RARITY_CEILING = 0.33

# Los cortes por cola se calculan sobre la bandeja publicada, no sobre un valor
# fijo: lo que es un monto alto depende de qué se publicó esta vez.
TAIL_QUANTILE = 0.90

# Bajo esta cantidad de relaciones, «raro en la bandeja» no significa nada: en
# una bandeja de una sola fila toda marca aparece en el 100%. Por debajo del
# mínimo las marcas estructurales —familias, tipos, evidencia externa— cuentan
# por sí mismas, porque son propiedades de la relación y no de la población; las
# marcas de cola no se aplican, porque son relativas por definición.
MIN_ROWS_FOR_RARITY = 20

STRUCTURAL_MARKS = ("FAMILIAS_MULTIPLES", "TIPOS_MULTIPLES", "EVIDENCIA_EXTERNA")

# Dos marcas independientes para el nivel superior. Una sola puede ser una
# coincidencia; dos que no se implican mutuamente son una convergencia.
MARKS_FOR_IMMEDIATE = 2

MARK_LABELS = {
    "FAMILIAS_MULTIPLES": "tres o más familias de señal distintas",
    "TIPOS_MULTIPLES": "tres o más tipos de señal distintos",
    "EVIDENCIA_EXTERNA": "cruce candidato con una auditoría de la CGR",
    "PRIORIDAD_EN_LA_COLA": "prioridad de revisión en el decil superior de la bandeja",
    "MONTO_EN_LA_COLA": "monto máximo en el decil superior de la bandeja",
}

LEVEL_MEANING = {
    IMMEDIATE: (
        "Dos o más marcas distintivas independientes convergen en esta relación, y cada "
        "una de ellas es rara en la bandeja publicada."
    ),
    PRIORITY: "Una marca distintiva rara en la bandeja publicada.",
    FOLLOW: (
        "Ninguna marca la distingue del resto de la bandeja. Se mantiene como contexto y "
        "vuelve a mirarse si aparecen nuevas señales o mayor materialidad."
    ),
}

GUARDRAIL = (
    "El nivel ordena el trabajo del analista dentro de la bandeja publicada. No mide "
    "gravedad ni acredita irregularidad: una relación en seguimiento no está descartada, "
    "y una en atención inmediata no está imputada."
)


def _num(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _quantile(values: list[float], q: float) -> float:
    """Corte por cuantil sobre los valores observados, sin interpolar."""
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return float("inf")
    idx = min(len(ordered) - 1, int(len(ordered) * q))
    return ordered[idx]


def marks_for(row: dict, cuts: dict) -> set[str]:
    """Qué marcas lleva una relación, antes de saber si alguna cuenta."""
    found = set()
    if _num(row, "signal_family_count") >= 3:
        found.add("FAMILIAS_MULTIPLES")
    if _num(row, "signal_type_count") >= 3:
        found.add("TIPOS_MULTIPLES")
    if _num(row, "cgr_match_count") > 0:
        found.add("EVIDENCIA_EXTERNA")
    if _num(row, "max_priority_score") >= cuts.get("max_priority_score", float("inf")):
        found.add("PRIORIDAD_EN_LA_COLA")
    if _num(row, "max_transaction_amount") >= cuts.get("max_transaction_amount", float("inf")):
        found.add("MONTO_EN_LA_COLA")
    return found


def calibrate(rows: list[dict], rarity_ceiling: float = RARITY_CEILING,
              tail_quantile: float = TAIL_QUANTILE,
              min_rows: int = MIN_ROWS_FOR_RARITY) -> dict:
    """Mide, sobre la bandeja que se va a publicar, qué marcas siguen distinguiendo."""
    total = len(rows or [])
    if not total:
        return {"published_rows": 0, "cuts": {}, "marks": {}, "counting_marks": [],
                "rarity_state": "SIN_BANDEJA"}

    measurable = total >= int(min_rows)
    cuts = (
        {key: _quantile([_num(r, key) for r in rows], tail_quantile)
         for key in ("max_priority_score", "max_transaction_amount")}
        if measurable else {}
    )

    prevalence: dict[str, int] = {name: 0 for name in MARK_LABELS}
    for row in rows:
        for name in marks_for(row, cuts):
            prevalence[name] += 1

    marks = {}
    for name, count in prevalence.items():
        share = count / total
        if not measurable:
            counts = name in STRUCTURAL_MARKS
            why = (
                f"La bandeja tiene {total} relaciones: bajo {int(min_rows)} la rareza no se "
                "puede medir. Las marcas estructurales cuentan por sí mismas; las de cola no "
                "se aplican."
            )
        else:
            counts = 0 < share <= rarity_ceiling
            why = (
                f"Presente en el {share:.1%} de la bandeja: deja de distinguir y no suma."
                if share > rarity_ceiling else
                "Ninguna relación la lleva en esta corrida."
                if count == 0 else
                f"Presente en el {share:.1%} de la bandeja."
            )
        marks[name] = {"label": MARK_LABELS[name], "rows": count,
                       "share": round(share, 6), "counts": counts, "why": why}
    return {
        "published_rows": total,
        "rarity_state": "MEDIDA" if measurable else "NO_MEDIBLE_POR_TAMANO",
        "min_rows_for_rarity": int(min_rows),
        "rarity_ceiling": rarity_ceiling,
        "tail_quantile": tail_quantile,
        "cuts": cuts,
        "marks": marks,
        "counting_marks": sorted(n for n, m in marks.items() if m["counts"]),
    }


def level_for(row: dict, calibration: dict) -> dict:
    """El nivel de una relación, con las marcas que lo justifican a la vista."""
    counting = set(calibration.get("counting_marks") or [])
    present = marks_for(row, calibration.get("cuts") or {})
    earned = sorted(present & counting)
    level = (IMMEDIATE if len(earned) >= MARKS_FOR_IMMEDIATE
             else PRIORITY if earned else FOLLOW)
    return {
        "attention_level": level,
        "attention_marks": earned,
        "attention_why": (
            "; ".join(MARK_LABELS[m] for m in earned) if earned
            else "Ninguna marca la distingue del resto de la bandeja."
        ),
        "attention_meaning": LEVEL_MEANING[level],
    }


def assign(rows: list[dict], **kwargs) -> dict:
    """Calibra contra la bandeja y devuelve el bloque que se publica.

    Muta cada fila con su nivel: el llamador ya tiene las relaciones en memoria y
    duplicarlas sólo para no tocarlas costaría más de lo que aclara.
    """
    calibration = calibrate(rows or [], **kwargs)
    tally: dict[str, int] = {IMMEDIATE: 0, PRIORITY: 0, FOLLOW: 0}
    for row in rows or []:
        verdict = level_for(row, calibration)
        row.update(verdict)
        tally[verdict["attention_level"]] += 1
    calibration["levels"] = tally
    calibration["guardrail"] = GUARDRAIL
    calibration["method"] = (
        "El nivel cuenta marcas distintivas, y una marca sólo cuenta si es rara en la "
        "bandeja publicada. La prevalencia se mide en cada corrida: una marca que se "
        "vuelve común deja de sumar sola, sin editar ningún umbral."
    )
    return calibration
