"""Un subsidio y una compra de insumos no se comparan por monto.

El nivel de atención marcaba «monto en el decil superior de la bandeja». Medido
sobre las 353 relaciones publicadas por la corrida #42, esa cola tenía esta
composición:

    transferencias   25 de 36
    adquisiciones     5 de 36

La marca de monto se había vuelto, sin que nadie lo decidiera, un detector de
transferencias. No por un error de cálculo: una transferencia corriente al
Administrador Financiero del Transantiago son 57.103 millones y una compra de
insumos clínicos son 900. Ordenadas juntas por monto, las compras no aparecen
nunca.

El efecto sobre la bandeja era el que el usuario vio: arriba, Tesorería General
de la República, el Transantiago, ENAP, Bomberos. Todas relaciones reales y
todas estructurales —el receptor lo fija la ley o la glosa presupuestaria, y hay
una sola Tesorería—, así que «concentración de proveedor» en una transferencia
describe el diseño del presupuesto, no una anomalía de contratación.

Aquí no se descarta ninguna: se comparan con sus iguales. Con el corte de monto
calculado dentro de cada naturaleza de gasto, la misma cola pasa a 24
adquisiciones y 11 transferencias, y suben relaciones que antes no cabían —
Philips en el Hospital de Puerto Montt, combustible de Petrobras en Carabineros,
aseo de LIMCHILE en el Sótero del Río, Roche en el Hospital de Iquique—, que es
el material que un monitor de anomalías de contratación pública existe para
mirar.

Es la quinta vez que este motor corrige lo mismo: un corte absoluto aplicado a
poblaciones que no son comparables entre sí.

La naturaleza no la inferimos: la declara el clasificador presupuestario
(Decreto 854), y el subtítulo ya viaja en `peer_context` de cada relación.
"""
from __future__ import annotations

ADQUISICION = "ADQUISICION"
TRANSFERENCIA = "TRANSFERENCIA"
PERSONAL = "PERSONAL"
PRESTACION = "PRESTACION_SOCIAL"
DEUDA = "SERVICIO_DE_DEUDA"
FINANCIERO = "MOVIMIENTO_FINANCIERO"
OTRO = "OTRO_GASTO_CORRIENTE"
NO_DECLARADA = "NO_DECLARADA"

# Clasificador presupuestario vigente (Decreto 854 y sus modificaciones). El
# mapa se queda corto a propósito: un subtítulo que no esté aquí no se fuerza a
# un grupo, se declara sin clasificar.
NATURE_BY_SUBTITLE = {
    "21": PERSONAL,
    "22": ADQUISICION,
    "23": PRESTACION,
    "24": TRANSFERENCIA,
    "25": OTRO,
    "26": OTRO,
    "29": ADQUISICION,
    "30": FINANCIERO,
    "31": ADQUISICION,
    "32": FINANCIERO,
    "33": TRANSFERENCIA,
    "34": DEUDA,
    "35": FINANCIERO,
}

NATURE_LABELS = {
    ADQUISICION: "adquisición de bienes, servicios o inversión",
    TRANSFERENCIA: "transferencia corriente o de capital",
    PERSONAL: "gasto en personal",
    PRESTACION: "prestación de seguridad social",
    DEUDA: "servicio de la deuda",
    FINANCIERO: "movimiento financiero",
    OTRO: "otro gasto corriente",
    NO_DECLARADA: "sin subtítulo declarado en la fuente",
}

# Dónde hay un procedimiento de contratación detrás del pago, y por lo tanto una
# orden de compra o una licitación que se puede ir a buscar. Es lo que separa a
# una relación que el monitor puede reconstruir documentalmente de una cuyo
# receptor viene fijado por la ley de presupuestos.
PROCUREMENT_EXPECTED = {ADQUISICION}

NATURE_NOTES = {
    TRANSFERENCIA: (
        "El receptor de una transferencia lo fija la ley de presupuestos o su glosa. "
        "Que un solo proveedor concentre el gasto describe el diseño del programa, no "
        "necesariamente una anomalía de contratación."
    ),
    ADQUISICION: (
        "Detrás del pago hay un procedimiento de contratación: debería existir una orden "
        "de compra o una licitación que reconstruir."
    ),
    PERSONAL: "Gasto en personal: no pasa por un procedimiento de contratación de bienes o servicios.",
    PRESTACION: "Prestación de seguridad social: el beneficiario lo define la normativa previsional.",
    DEUDA: "Servicio de la deuda: el monto responde a compromisos financieros previos.",
    FINANCIERO: "Movimiento financiero: no corresponde a una adquisición.",
    OTRO: "Otro gasto corriente: revisar el ítem antes de tratarlo como contratación.",
    NO_DECLARADA: (
        "La fuente no trae el subtítulo de esta relación, así que su naturaleza no se "
        "puede determinar y no se compara con ninguna otra población."
    ),
}

GUARDRAIL = (
    "La naturaleza del gasto ordena con qué se compara una relación. No califica el gasto "
    "ni lo exime: una transferencia puede ser irregular y una adquisición puede ser "
    "impecable."
)


def normalize_subtitle(raw: object) -> str:
    """Devuelve el subtítulo como dos dígitos, o cadena vacía si no se puede leer."""
    text = str(raw or "").strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return ""
    return digits[:2].zfill(2)


def classify(subtitle: object) -> dict:
    """Clasifica un subtítulo presupuestario, declarando cuando no lo reconoce."""
    code = normalize_subtitle(subtitle)
    nature = NATURE_BY_SUBTITLE.get(code, NO_DECLARADA if not code else None)
    if nature is None:
        # Un subtítulo real que el mapa no conoce: decirlo es más útil que
        # meterlo en «otro gasto corriente» y que nadie se entere.
        return {
            "subtitulo": code,
            "nature": NO_DECLARADA,
            "label": f"subtítulo {code}, no reconocido por el clasificador cargado",
            "procurement_expected": False,
            "note": (
                f"El subtítulo {code} no está en el clasificador cargado en este motor. "
                "Se trata como naturaleza sin determinar en vez de asignarle un grupo."
            ),
        }
    return {
        "subtitulo": code,
        "nature": nature,
        "label": NATURE_LABELS[nature],
        "procurement_expected": nature in PROCUREMENT_EXPECTED,
        "note": NATURE_NOTES[nature],
    }


def subtitle_of(row: dict) -> str:
    """El subtítulo de una relación, que viaja dentro de su contexto de pares."""
    peer = row.get("peer_context")
    if isinstance(peer, dict):
        return normalize_subtitle(peer.get("subtitulo"))
    return normalize_subtitle(row.get("subtitulo"))


def nature_of(row: dict) -> dict:
    """La naturaleza de gasto de una relación publicada."""
    return classify(subtitle_of(row))


def code_of(row: dict) -> str:
    return nature_of(row)["nature"]
