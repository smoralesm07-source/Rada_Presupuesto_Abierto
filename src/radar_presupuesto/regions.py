from __future__ import annotations

"""Catálogo canónico de regiones de Chile para lectura territorial del gasto.

La fuente Presupuesto Abierto entrega el campo ``REGION`` sin garantía de
formato: puede venir como código numérico (``13``, ``9``), como código con
cero a la izquierda (``09``) o como nombre con variantes ortográficas. Este
módulo resuelve esas formas a una identidad única y estable, preserva el
orden geográfico norte→sur (indispensable para leer Chile como franja) y
mantiene ``UNKNOWN`` como categoría explícita: ausencia no es cero.
"""

from .ids import normalize_text


def _key(value: object) -> str:
    """Clave de comparación: sin tildes, sin apóstrofos y en mayúsculas."""
    return normalize_text(value).replace("'", "").replace("\u2019", "").replace("`", "").replace("\u00b4", "")

# code, name, abbr, macrozone; el orden de la tupla es el orden norte→sur.
REGION_CATALOG: tuple[tuple[str, str, str, str], ...] = (
    ("15", "Arica y Parinacota", "AP", "NORTE_GRANDE"),
    ("01", "Tarapacá", "TA", "NORTE_GRANDE"),
    ("02", "Antofagasta", "AN", "NORTE_GRANDE"),
    ("03", "Atacama", "AT", "NORTE_CHICO"),
    ("04", "Coquimbo", "CO", "NORTE_CHICO"),
    ("05", "Valparaíso", "VA", "CENTRO"),
    ("13", "Metropolitana de Santiago", "RM", "CENTRO"),
    ("06", "Libertador General Bernardo O'Higgins", "OH", "CENTRO"),
    ("07", "Maule", "ML", "CENTRO"),
    ("16", "Ñuble", "NB", "SUR"),
    ("08", "Biobío", "BB", "SUR"),
    ("09", "La Araucanía", "AR", "SUR"),
    ("14", "Los Ríos", "LR", "SUR"),
    ("10", "Los Lagos", "LL", "SUR"),
    ("11", "Aysén del General Carlos Ibáñez del Campo", "AY", "AUSTRAL"),
    ("12", "Magallanes y de la Antártica Chilena", "MA", "AUSTRAL"),
)

UNKNOWN_REGION = {
    "region_code": "UNKNOWN",
    "region_name": "Sin región informada",
    "region_abbr": "SR",
    "macrozone": "UNKNOWN",
    "geo_order": len(REGION_CATALOG) + 1,
}

_BY_CODE: dict[str, dict[str, object]] = {
    code: {
        "region_code": code,
        "region_name": name,
        "region_abbr": abbr,
        "macrozone": macro,
        "geo_order": order,
    }
    for order, (code, name, abbr, macro) in enumerate(REGION_CATALOG, start=1)
}

# Alias adicionales observados en publicaciones del sector público.
_EXTRA_ALIASES: dict[str, str] = {
    "REGION METROPOLITANA": "13",
    "METROPOLITANA": "13",
    "RM": "13",
    "SANTIAGO": "13",
    "OHIGGINS": "06",
    "O HIGGINS": "06",
    "LIBERTADOR BERNARDO OHIGGINS": "06",
    "DEL LIBERTADOR GENERAL BERNARDO OHIGGINS": "06",
    "BIO BIO": "08",
    "DEL BIOBIO": "08",
    "ARAUCANIA": "09",
    "DE LA ARAUCANIA": "09",
    "AISEN": "11",
    "AYSEN": "11",
    "MAGALLANES": "12",
    "MAGALLANES Y ANTARTICA CHILENA": "12",
    "NUBLE": "16",
    "ARICA PARINACOTA": "15",
    "TARAPACA": "01",
    "VALPARAISO": "05",
    "LOS RIOS": "14",
}

# Reglas por subcadena para nombres cuya ortografía varía mucho en la fuente
# ("O'Higgins", "Aysén", "Antártica"): la coincidencia por token no basta.
_SUBSTRING_RULES: tuple[tuple[str, str], ...] = (
    ("HIGGINS", "06"),
    ("ARAUCANIA", "09"),
    ("MAGALLANES", "12"),
    ("ANTARTICA", "12"),
    ("AYSEN", "11"),
    ("AISEN", "11"),
    ("PARINACOTA", "15"),
    ("NUBLE", "16"),
    ("BIO BIO", "08"),
    ("BIOBIO", "08"),
    ("METROPOLITANA", "13"),
)

_ROMAN: dict[str, str] = {
    "I": "01", "II": "02", "III": "03", "IV": "04", "V": "05", "VI": "06", "VII": "07",
    "VIII": "08", "IX": "09", "X": "10", "XI": "11", "XII": "12", "XIII": "13",
    "XIV": "14", "XV": "15", "XVI": "16",
}

_BY_NAME: dict[str, str] = {}
for code, name, abbr, _macro in REGION_CATALOG:
    _BY_NAME[_key(name)] = code
    _BY_NAME[_key(abbr)] = code
    _BY_NAME[_key(f"REGION DE {name}")] = code
    _BY_NAME[_key(f"REGION DEL {name}")] = code
_BY_NAME.update({_key(k): v for k, v in _EXTRA_ALIASES.items()})


def region_code(raw: object) -> str:
    """Devuelve el código canónico de dos dígitos o ``UNKNOWN``.

    Acepta código numérico, código con cero a la izquierda, numeral romano,
    sigla y nombre con variantes ortográficas. No inventa geografía: cualquier
    valor irreconocible queda ``UNKNOWN`` para que la cobertura territorial
    sea auditable en lugar de silenciosa.
    """
    text = "" if raw is None else str(raw).strip()
    if not text or text.lower() in {"nan", "none", "null", "-", "unknown", "sin informacion"}:
        return "UNKNOWN"

    try:
        numeric = float(text.replace(",", "."))
    except ValueError:
        numeric = None
    if numeric is not None and numeric.is_integer():
        code = f"{int(numeric):02d}"
        return code if code in _BY_CODE else "UNKNOWN"

    key = _key(text)
    if key in _BY_NAME:
        return _BY_NAME[key]
    if key in _ROMAN:
        return _ROMAN[key]

    # Nombre largo con prefijos ("REGION DE LOS LAGOS", "XIV REGION DE LOS RIOS").
    tokens = [t for t in key.replace("REGION", " ").split() if t not in {"DE", "DEL", "LA", "LOS", "LAS", "Y"}]
    for candidate in (" ".join(tokens), tokens[0] if tokens else ""):
        if candidate in _BY_NAME:
            return _BY_NAME[candidate]
        if candidate in _ROMAN:
            return _ROMAN[candidate]
    stripped = " ".join(key.replace("REGION", " ").replace(" DEL ", " ").replace(" DE ", " ").split())
    if stripped in _BY_NAME:
        return _BY_NAME[stripped]
    for needle, code in _SUBSTRING_RULES:
        if needle in key:
            return code
    return "UNKNOWN"


def region_meta(raw: object) -> dict[str, object]:
    """Metadatos canónicos (nombre, sigla, macrozona, orden norte→sur)."""
    code = region_code(raw)
    return dict(_BY_CODE.get(code, UNKNOWN_REGION))


def region_reference() -> list[dict[str, object]]:
    """Catálogo completo, en orden geográfico, con ``UNKNOWN`` al final."""
    return [dict(_BY_CODE[code]) for code, *_ in REGION_CATALOG] + [dict(UNKNOWN_REGION)]
