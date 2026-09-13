from __future__ import annotations

"""The LA/FT axis: from technical signals to typologies an analyst reasons with.

An analyst does not think in `AMOUNT_OUTLIER`. They think "is this a shell
supplier?", "is this a split to stay under the threshold?", "is the buyer
captured?". This layer does that translation, and it does it with three things
attached to every typology, not one: what would **sustain** the hypothesis, what
would **rule it out**, and which **document** to request next.

Two design rules keep it honest.

The score never reaches its ceiling on evidence the radar cannot yet see. Each
typology declares which of its patterns are observable today; a typology that
depends on procurement or ownership data the radar has not integrated is capped
and reports the gap, instead of quietly scoring low and looking like a negative
result.

And this axis is computed apart from review priority. A relation can be worth
reviewing for reasons that have nothing to do with laundering, and mixing the two
is what produced a queue led by a fuel invoice.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .relation_context import build_relation_context, classify_opacity, relation_patterns

# ---------------------------------------------------------------------------
# Which layer each pattern comes from, and whether the radar can observe it yet.
# ---------------------------------------------------------------------------

LAYER_TRANSACTION = "TRANSACCION"
LAYER_ENTITY = "ENTIDAD"
LAYER_CONTEXT = "CONTEXTO_RELACION"
LAYER_PROCUREMENT = "PROCESO_DE_COMPRA"
LAYER_OWNERSHIP = "PROPIEDAD_Y_CONTROL"

PATTERN_LAYER: dict[str, str] = {
    "AMOUNT_OUTLIER": LAYER_TRANSACTION,
    "POTENTIAL_FRAGMENTATION": LAYER_TRANSACTION,
    "EXACT_DUPLICATE_CANDIDATE": LAYER_TRANSACTION,
    "PROVIDER_CONCENTRATION": LAYER_TRANSACTION,
    "NEW_TO_SERIES_HIGH_SPEND": LAYER_TRANSACTION,
    "PAYMENT_DELAY_OUTLIER": LAYER_TRANSACTION,
    "YEAR_END_SPIKE": LAYER_TRANSACTION,
    "NEWBORN_SUPPLIER": LAYER_ENTITY,
    "CAPACITY_MISMATCH": LAYER_ENTITY,
    "ACTIVITY_MISMATCH": LAYER_ENTITY,
    "TERMINATION_AFTER_PAYMENT": LAYER_ENTITY,
    "DORMANT_REACTIVATION": LAYER_ENTITY,
    "OPAQUE_COUNTERPARTY": LAYER_CONTEXT,
    "HONORARIUM_CONCENTRATION": LAYER_CONTEXT,
    "PERSON_RECIPIENT": LAYER_CONTEXT,
    "NO_PURCHASE_ORDER_TRAIL": LAYER_CONTEXT,
    "SINGLE_BIDDER": LAYER_PROCUREMENT,
    "BID_ROTATION": LAYER_PROCUREMENT,
    "COVER_BIDDING": LAYER_PROCUREMENT,
    "SPEC_TAILORING": LAYER_PROCUREMENT,
    "DIRECT_AWARD_DEPENDENCE": LAYER_PROCUREMENT,
    "DIRECT_AWARD_RECURRENCE": LAYER_PROCUREMENT,
    "EMERGENCY_ABUSE": LAYER_PROCUREMENT,
    "THRESHOLD_HUGGING": LAYER_PROCUREMENT,
    "SPLIT_PROCUREMENT": LAYER_PROCUREMENT,
    "AWARD_TO_PAYMENT_INFLATION": LAYER_PROCUREMENT,
    "SERIAL_AMENDMENT": LAYER_PROCUREMENT,
    "SPEED_ANOMALY": LAYER_PROCUREMENT,
    "PHANTOM_COMPETITION": LAYER_PROCUREMENT,
    "SHARED_INFRASTRUCTURE": LAYER_OWNERSHIP,
    "RELATED_PARTY": LAYER_OWNERSHIP,
    "REVOLVING_DOOR": LAYER_OWNERSHIP,
}

# Layers the radar actually produces today. `PROCESO_DE_COMPRA` turns on when the
# Mercado Público adapter is connected; `PROPIEDAD_Y_CONTROL` when the ownership
# sources are integrated. Until then the typologies that need them say so.
OBSERVABLE_LAYERS = {LAYER_TRANSACTION, LAYER_ENTITY, LAYER_CONTEXT}

PATTERN_LABEL: dict[str, str] = {
    "AMOUNT_OUTLIER": "Monto fuera del patrón de su grupo de pares",
    "POTENTIAL_FRAGMENTATION": "Pagos similares en secuencia corta",
    "EXACT_DUPLICATE_CANDIDATE": "Documentos potencialmente repetidos",
    "PROVIDER_CONCENTRATION": "Concentración del gasto en un proveedor",
    "NEW_TO_SERIES_HIGH_SPEND": "Proveedor nuevo en la serie con gasto alto",
    "PAYMENT_DELAY_OUTLIER": "Plazo de pago atípico",
    "YEAR_END_SPIKE": "Concentración del gasto al cierre del año",
    "NEWBORN_SUPPLIER": "Adjudicación a poco del inicio de actividades",
    "CAPACITY_MISMATCH": "Monto desproporcionado frente a la capacidad declarada",
    "ACTIVITY_MISMATCH": "Giro registrado ajeno al objeto contratado",
    "TERMINATION_AFTER_PAYMENT": "Término de giro poco después del último pago",
    "DORMANT_REACTIVATION": "Reaparece tras un periodo sin pagos",
    "OPAQUE_COUNTERPARTY": "Contraparte pseudonimizada por la fuente",
    "HONORARIUM_CONCENTRATION": "Gasto concentrado en honorarios",
    "PERSON_RECIPIENT": "Receptor persona natural",
    "NO_PURCHASE_ORDER_TRAIL": "Pagos materiales sin orden de compra asociada",
    "SINGLE_BIDDER": "Licitación con un único oferente admisible",
    "BID_ROTATION": "Rotación del adjudicatario entre los mismos oferentes",
    "COVER_BIDDING": "Ofertas perdedoras de cobertura",
    "SPEC_TAILORING": "Bases ajustadas a un oferente",
    "DIRECT_AWARD_DEPENDENCE": "Dependencia del trato directo frente a pares",
    "DIRECT_AWARD_RECURRENCE": "Trato directo reiterado con el mismo proveedor",
    "EMERGENCY_ABUSE": "Causal de emergencia fuera de ventana",
    "THRESHOLD_HUGGING": "Adjudicaciones justo bajo el umbral",
    "SPLIT_PROCUREMENT": "Objeto dividido en procesos sucesivos",
    "AWARD_TO_PAYMENT_INFLATION": "Pagado muy por sobre lo adjudicado",
    "SERIAL_AMENDMENT": "Modificaciones sucesivas del contrato",
    "SPEED_ANOMALY": "Secuencia adjudicación-pago inverosímilmente rápida",
    "PHANTOM_COMPETITION": "Oferentes vinculados entre sí",
    "SHARED_INFRASTRUCTURE": "Representante, domicilio o contacto compartido",
    "RELATED_PARTY": "Vínculo societario o familiar con el comprador",
    "REVOLVING_DOOR": "Decisor público que pasa al proveedor",
}

GUARDRAIL = (
    "La compatibilidad con una tipología es una hipótesis de trabajo, no una imputación. "
    "Mide cuántos patrones propios de esa tipología están presentes, no la probabilidad de "
    "que exista lavado de activos ni la responsabilidad de ninguna persona o entidad. "
    "Una tipología sólo puede sostenerse con evidencia documental externa al radar."
)


@dataclass(frozen=True)
class Typology:
    code: str
    name: str
    question: str
    anchors: tuple[tuple[str, ...], ...]
    reinforcing: tuple[str, ...]
    sustains: tuple[str, ...]
    discards: tuple[str, ...]
    documents: tuple[str, ...]
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def patterns(self) -> tuple[str, ...]:
        flat = [p for group in self.anchors for p in group]
        return tuple(dict.fromkeys(flat + list(self.reinforcing)))

    def weight(self, pattern: str) -> float:
        return float(self.weights.get(pattern, 1.0))

    @property
    def missing_layers(self) -> tuple[str, ...]:
        layers = {PATTERN_LAYER.get(p, LAYER_TRANSACTION) for p in self.patterns}
        return tuple(sorted(layers - OBSERVABLE_LAYERS))

    @property
    def evidence_ceiling(self) -> float:
        """How high this typology can score with the data the radar has today."""
        total = sum(self.weight(p) for p in self.patterns)
        if total <= 0:
            return 0.0
        observable = sum(
            self.weight(p)
            for p in self.patterns
            if PATTERN_LAYER.get(p, LAYER_TRANSACTION) in OBSERVABLE_LAYERS
        )
        return round(observable / total, 4)

    @property
    def anchorable_now(self) -> bool:
        """A typology is reachable only if every anchor has an observable option."""
        return all(
            any(PATTERN_LAYER.get(p, LAYER_TRANSACTION) in OBSERVABLE_LAYERS for p in group)
            for group in self.anchors
        )


TYPOLOGIES: tuple[Typology, ...] = (
    Typology(
        code="PROVEEDOR_FACHADA",
        name="Proveedor de fachada",
        question="¿El adjudicatario tiene existencia económica propia o es un vehículo de facturación?",
        anchors=(
            ("NEWBORN_SUPPLIER", "DORMANT_REACTIVATION"),
            ("CAPACITY_MISMATCH", "ACTIVITY_MISMATCH"),
        ),
        reinforcing=(
            "PROVIDER_CONCENTRATION",
            "NEW_TO_SERIES_HIGH_SPEND",
            "NO_PURCHASE_ORDER_TRAIL",
            "TERMINATION_AFTER_PAYMENT",
            "SINGLE_BIDDER",
        ),
        sustains=(
            "Sin trabajadores ni activos observables frente al monto contratado.",
            "Domicilio, representante o contacto compartido con otros oferentes.",
            "Sin historial comercial fuera del comprador público que lo contrata.",
        ),
        discards=(
            "Es una filial o vehículo nuevo de un grupo con trayectoria acreditada.",
            "Subcontrata de forma documentada y el giro cubre el objeto contratado.",
            "El tramo de ventas SII corresponde a un año anterior al del contrato.",
        ),
        documents=(
            "Escritura de constitución y modificaciones societarias vigentes al adjudicar",
            "Certificado de inicio de actividades y carpeta tributaria",
            "Contrato, recepciones conformes y nómina de personal o subcontratos",
        ),
        weights={"CAPACITY_MISMATCH": 1.5, "NEWBORN_SUPPLIER": 1.5},
    ),
    Typology(
        code="FRACCIONAMIENTO_CONTROL",
        name="Fraccionamiento para evadir control",
        question="¿Se dividió un mismo objeto para no cruzar el umbral que obliga a licitar?",
        anchors=(
            ("POTENTIAL_FRAGMENTATION", "SPLIT_PROCUREMENT", "THRESHOLD_HUGGING"),
        ),
        reinforcing=(
            "EXACT_DUPLICATE_CANDIDATE",
            "DIRECT_AWARD_RECURRENCE",
            "NO_PURCHASE_ORDER_TRAIL",
            "PROVIDER_CONCENTRATION",
        ),
        sustains=(
            "Los procesos comparten objeto, especificaciones y plazo de ejecución.",
            "La suma en ventana corta cruza el umbral que habría exigido otra modalidad.",
            "Las adjudicaciones se agrupan justo por debajo del umbral.",
        ),
        discards=(
            "Corresponde a facturación periódica de un contrato único ya licitado.",
            "Son pagos parciales o hitos de un mismo contrato vigente.",
            "Los objetos son técnicamente distintos aunque el proveedor sea el mismo.",
        ),
        documents=(
            "Órdenes de compra y contratos del periodo con su objeto detallado",
            "Resoluciones fundadas de trato directo, si las hubiere",
            "Programación anual de compras del organismo",
        ),
        weights={"POTENTIAL_FRAGMENTATION": 1.5, "SPLIT_PROCUREMENT": 1.5},
    ),
    Typology(
        code="EXTRACCION_Y_DISOLUCION",
        name="Extracción y disolución",
        question="¿La sociedad se cierra una vez cobrado, sin dejar rastro patrimonial?",
        anchors=(("TERMINATION_AFTER_PAYMENT",),),
        reinforcing=(
            "AMOUNT_OUTLIER",
            "CAPACITY_MISMATCH",
            "NEWBORN_SUPPLIER",
            "PROVIDER_CONCENTRATION",
            "NO_PURCHASE_ORDER_TRAIL",
        ),
        sustains=(
            "Término de giro con obligaciones contractuales aún pendientes.",
            "Los socios reaparecen en otras sociedades que contratan con el mismo comprador.",
            "No hay activos ni continuidad operativa tras el último pago.",
        ),
        discards=(
            "Cierre por fusión, absorción o reorganización societaria documentada.",
            "El contrato terminó normalmente y el giro se cerró por causas ajenas.",
        ),
        documents=(
            "Aviso de término de giro y balance final",
            "Estado de cumplimiento del contrato y garantías",
            "Sociedades posteriores de los mismos socios o representantes",
        ),
        weights={"TERMINATION_AFTER_PAYMENT": 2.0},
    ),
    Typology(
        code="INTERPOSICION_DE_PERSONAS",
        name="Interposición de personas",
        question="¿Se usan personas naturales para recibir fondos que no les corresponden económicamente?",
        anchors=(("HONORARIUM_CONCENTRATION", "PERSON_RECIPIENT"),),
        reinforcing=(
            "PROVIDER_CONCENTRATION",
            "AMOUNT_OUTLIER",
            "OPAQUE_COUNTERPARTY",
            "POTENTIAL_FRAGMENTATION",
            "REVOLVING_DOOR",
            "RELATED_PARTY",
        ),
        sustains=(
            "Los honorarios no corresponden a una prestación personal verificable.",
            "La persona tiene vínculo con el decisor o con el proveedor principal.",
            "Los montos superan lo razonable para la función declarada.",
        ),
        discards=(
            "Corresponde a personal a honorarios con funciones y productos acreditados.",
            "Es un programa que paga prestaciones individuales por diseño.",
        ),
        documents=(
            "Convenios a honorarios, informes de actividad y productos entregados",
            "Declaraciones de intereses y patrimonio del decisor pertinente",
            "Registro de asistencia o cumplimiento asociado al pago",
        ),
        weights={"HONORARIUM_CONCENTRATION": 1.5},
    ),
    Typology(
        code="SOBREPRECIO_Y_DESVIO",
        name="Sobreprecio y desvío",
        question="¿Se pagó por encima de lo adjudicado o del valor de mercado comparable?",
        anchors=(("AWARD_TO_PAYMENT_INFLATION", "AMOUNT_OUTLIER"),),
        reinforcing=(
            "SINGLE_BIDDER",
            "SERIAL_AMENDMENT",
            "SPEC_TAILORING",
            "CAPACITY_MISMATCH",
            "PAYMENT_DELAY_OUTLIER",
        ),
        sustains=(
            "Lo pagado excede lo adjudicado sin modificación contractual que lo explique.",
            "El precio unitario supera de forma sostenida al de pares comparables.",
            "Las modificaciones aumentan el monto sin ampliar el alcance.",
        ),
        discards=(
            "Hay modificaciones contractuales aprobadas que explican la diferencia.",
            "El alza responde a reajustes, tipo de cambio o insumos regulados.",
            "El objeto no es comparable con el de los pares usados como referencia.",
        ),
        documents=(
            "Acto de adjudicación y contrato con sus anexos de precio",
            "Modificaciones contractuales y sus fundamentos",
            "Estados de pago y recepciones conformes",
        ),
        weights={"AWARD_TO_PAYMENT_INFLATION": 2.0},
    ),
    Typology(
        code="CAPTURA_DEL_COMPRADOR",
        name="Captura del comprador",
        question="¿La relación con este proveedor dejó de ser competitiva por diseño?",
        anchors=(("DIRECT_AWARD_DEPENDENCE", "PROVIDER_CONCENTRATION"),),
        reinforcing=(
            "SPEC_TAILORING",
            "RELATED_PARTY",
            "REVOLVING_DOOR",
            "DIRECT_AWARD_RECURRENCE",
            "SINGLE_BIDDER",
            "NEW_TO_SERIES_HIGH_SPEND",
        ),
        sustains=(
            "La concentración crece mientras existen alternativas de mercado.",
            "Las bases incorporan requisitos que sólo el incumbente satisface.",
            "Hay vínculo personal, societario o funcional con quien decide.",
        ),
        discards=(
            "Monopolio técnico, convenio marco o concesión que explica la exclusividad.",
            "Contrato plurianual único adjudicado competitivamente en su origen.",
            "El mercado relevante efectivamente no tiene otros oferentes.",
        ),
        documents=(
            "Bases de licitación y actas de evaluación del periodo",
            "Resoluciones de trato directo y sus fundamentos",
            "Declaraciones de intereses de la autoridad que adjudica",
        ),
        weights={"DIRECT_AWARD_DEPENDENCE": 1.5},
    ),
    Typology(
        code="COLUSION_DE_OFERENTES",
        name="Colusión de oferentes",
        question="¿Los oferentes compiten de verdad o se reparten las adjudicaciones?",
        anchors=(("BID_ROTATION", "COVER_BIDDING", "PHANTOM_COMPETITION"),),
        reinforcing=(
            "SHARED_INFRASTRUCTURE",
            "SINGLE_BIDDER",
            "RELATED_PARTY",
            "PROVIDER_CONCENTRATION",
        ),
        sustains=(
            "El ganador rota de forma regular entre un grupo estable de oferentes.",
            "Las ofertas perdedoras comparten errores, formato o estructura de precios.",
            "Los oferentes comparten representante, domicilio o contacto.",
        ),
        discards=(
            "El mercado tiene pocos actores y la rotación es estadísticamente esperable.",
            "Las diferencias de precio responden a capacidad instalada distinta.",
        ),
        documents=(
            "Ofertas completas de todos los participantes, no sólo del adjudicado",
            "Actas de apertura y evaluación",
            "Antecedentes societarios de los oferentes",
        ),
        weights={"BID_ROTATION": 2.0},
    ),
)

TYPOLOGY_BY_CODE = {t.code: t for t in TYPOLOGIES}


# Un patrón aislado no es una tipología. Sin al menos dos patrones concurrentes
# la hipótesis no se propone: mostrar "sobreprecio y desvío" porque hay un monto
# atípico sobre-afirma, y sobre-afirmar es exactamente lo que estos guardrails
# existen para impedir.
MIN_CORROBORATING_PATTERNS = 2


def alignment_level(score: float) -> str:
    if score >= 70:
        return "ALTO"
    if score >= 45:
        return "MEDIO"
    if score >= 25:
        return "BAJO"
    return "NULO"


def match_typology(typology: Typology, patterns: set[str]) -> dict | None:
    """Score one typology against the patterns observed on a relation."""
    if not all(any(p in patterns for p in group) for group in typology.anchors):
        return None
    total = sum(typology.weight(p) for p in typology.patterns)
    matched = [p for p in typology.patterns if p in patterns]
    if len(matched) < MIN_CORROBORATING_PATTERNS:
        return None
    got = sum(typology.weight(p) for p in matched)
    coverage = got / total if total else 0.0
    ceiling = typology.evidence_ceiling
    score = round(100 * coverage, 2)
    capped = round(min(score, 100 * ceiling), 2)
    missing_observable = [
        p
        for p in typology.patterns
        if p not in patterns and PATTERN_LAYER.get(p) in OBSERVABLE_LAYERS
    ]
    blocked = [p for p in typology.patterns if PATTERN_LAYER.get(p) not in OBSERVABLE_LAYERS]
    return {
        "typology": typology.code,
        "typology_name": typology.name,
        "question": typology.question,
        "score": capped,
        "raw_coverage": round(coverage, 4),
        "evidence_ceiling": ceiling,
        "matched_patterns": matched,
        "matched_labels": [PATTERN_LABEL.get(p, p) for p in matched],
        "missing_observable_patterns": missing_observable,
        "patterns_pending_integration": blocked,
        "missing_layers": list(typology.missing_layers),
        "sustains": list(typology.sustains),
        "discards": list(typology.discards),
        "documents": list(typology.documents),
    }


def match_all(patterns: set[str]) -> list[dict]:
    matches = [m for t in TYPOLOGIES if (m := match_typology(t, patterns))]
    matches.sort(key=lambda m: (-m["score"], m["typology"]))
    return matches


def _signal_patterns_by_relation(prioritized_path: str) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            SELECT organization_id,
                   coalesce(provider_id,'') AS provider_id,
                   periodo,
                   string_agg(DISTINCT signal_type, '|') AS signal_types,
                   max(review_priority_score) AS max_review_priority,
                   any_value(organization_name) AS organization_name,
                   any_value(provider_or_recipient_name) AS provider_name
            FROM read_parquet('{prioritized_path}')
            WHERE coalesce(organization_id,'') <> ''
            GROUP BY organization_id, coalesce(provider_id,''), periodo
            """
        ).df()
    finally:
        con.close()


def _entity_patterns_by_provider(entity_signals_path: str) -> dict[str, set[str]]:
    path = Path(entity_signals_path)
    if not path.exists():
        return {}
    frame = pd.read_parquet(path)
    if frame.empty:
        return {}
    out: dict[str, set[str]] = {}
    for row in frame.itertuples():
        out.setdefault(str(row.provider_id), set()).add(str(row.signal_type))
    return out


def build_typologies(
    parquet_glob: str,
    prioritized_path: str = "data/signals/prioritized_signals.parquet",
    entity_signals_path: str = "data/signals/entity_signals.parquet",
    output_parquet: str = "data/signals/typology_matches.parquet",
    output_json: str | None = "docs/data/typology_context.json",
) -> dict:
    signals = _signal_patterns_by_relation(prioritized_path)
    entity = _entity_patterns_by_provider(entity_signals_path)
    context = build_relation_context(parquet_glob)

    context_index = {
        (str(r.organization_id), str(r.provider_id), int(r.periodo)): r
        for r in context.itertuples()
        if not pd.isna(r.periodo)
    }

    rows: list[dict] = []
    for row in signals.itertuples():
        key = (str(row.organization_id), str(row.provider_id), int(row.periodo))
        patterns: set[str] = {
            s for s in str(row.signal_types or "").split("|") if s
        }
        patterns |= entity.get(str(row.provider_id), set())
        ctx = context_index.get(key)
        opaque_share = 0.0
        relation_amount = 0.0
        if ctx is not None:
            patterns |= set(relation_patterns(pd.Series(ctx._asdict())))
            opaque_share = float(ctx.opaque_amount_share or 0)
            relation_amount = float(ctx.relation_amount or 0)

        matches = match_all(patterns)
        best = matches[0] if matches else None
        rows.append(
            {
                "organization_id": key[0],
                "provider_id": key[1],
                "periodo": key[2],
                "organization_name": row.organization_name,
                "provider_name": row.provider_name,
                "relation_amount": relation_amount,
                "opaque_amount_share": round(opaque_share, 6),
                "opacity_level": classify_opacity(opaque_share),
                "observed_patterns": "|".join(sorted(patterns)),
                "laft_compatibility_score": float(best["score"]) if best else 0.0,
                "laft_alignment": alignment_level(float(best["score"]) if best else 0.0),
                "top_typology": best["typology"] if best else "",
                "top_typology_name": best["typology_name"] if best else "",
                "typology_count": len(matches),
                "typologies": json.dumps(matches, ensure_ascii=False),
                "guardrail": GUARDRAIL,
            }
        )

    frame = pd.DataFrame(
        rows,
        columns=[
            "organization_id", "provider_id", "periodo", "organization_name", "provider_name",
            "relation_amount", "opaque_amount_share", "opacity_level", "observed_patterns",
            "laft_compatibility_score", "laft_alignment", "top_typology", "top_typology_name",
            "typology_count", "typologies", "guardrail",
        ],
    )
    out = Path(output_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)

    by_typology: dict[str, int] = {}
    for row in rows:
        if row["top_typology"]:
            by_typology[row["top_typology"]] = by_typology.get(row["top_typology"], 0) + 1

    catalog = [
        {
            "code": t.code,
            "name": t.name,
            "question": t.question,
            "anchors": [list(group) for group in t.anchors],
            "anchor_labels": [[PATTERN_LABEL.get(p, p) for p in group] for group in t.anchors],
            "reinforcing": list(t.reinforcing),
            "sustains": list(t.sustains),
            "discards": list(t.discards),
            "documents": list(t.documents),
            "evidence_ceiling": t.evidence_ceiling,
            "reachable_today": t.anchorable_now,
            "missing_layers": list(t.missing_layers),
        }
        for t in TYPOLOGIES
    ]
    payload = {
        "schema": "RIGP-TYPOLOGY-CONTEXT-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guardrail": GUARDRAIL,
        "observable_layers": sorted(OBSERVABLE_LAYERS),
        "pending_layers": sorted(set(PATTERN_LAYER.values()) - OBSERVABLE_LAYERS),
        "coverage_note": (
            "Las tipologías que dependen del proceso de compra o de propiedad y control "
            "no pueden alcanzar su puntaje máximo mientras esas fuentes no estén integradas. "
            "El techo de evidencia de cada una lo declara explícitamente."
        ),
        "catalog": catalog,
        "pattern_layers": PATTERN_LAYER,
        "pattern_labels": PATTERN_LABEL,
        "alignment_levels": {
            "ALTO": "Están presentes la mayor parte de los patrones observables de la tipología.",
            "MEDIO": "Hay coincidencia parcial suficiente para una revisión dirigida.",
            "BAJO": "Coincidencia mínima; mantener como contexto.",
            "NULO": "No se configura ninguna tipología con los patrones observados.",
        },
        "relations_evaluated": len(rows),
        "relations_with_typology": sum(1 for r in rows if r["top_typology"]),
        "by_typology": by_typology,
    }
    if output_json:
        json_path = Path(output_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    return {
        "path": str(out),
        "relations_evaluated": len(rows),
        "relations_with_typology": payload["relations_with_typology"],
        "by_typology": by_typology,
        "reachable_today": [t.code for t in TYPOLOGIES if t.anchorable_now],
        "blocked_until_integration": [t.code for t in TYPOLOGIES if not t.anchorable_now],
    }
