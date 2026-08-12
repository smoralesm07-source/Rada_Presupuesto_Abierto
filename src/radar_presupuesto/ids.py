from __future__ import annotations

import hashlib
import re
import unicodedata

SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text.upper()).strip()
    return text


def _rut_dv(body: str) -> str:
    total = 0
    multiplier = 2
    for digit in reversed(body):
        total += int(digit) * multiplier
        multiplier = multiplier + 1 if multiplier < 7 else 2
    result = 11 - (total % 11)
    if result == 11:
        return "0"
    if result == 10:
        return "K"
    return str(result)


def normalize_rut(value: object) -> str:
    """Return a canonical Chilean RUT only when format and check digit are valid.

    Current Presupuesto Abierto bulk files also use 40-char SHA1-like identifiers for
    some natural persons/aggregates. Those must never be converted into pseudo-RUTs.
    """
    text = str(value or "").strip()
    if not text or SHA1_RE.fullmatch(text):
        return ""
    # Only digits, punctuation/space and K are legal in a candidate RUT.
    if re.search(r"[A-JL-Za-jl-z]", text):
        return ""
    compact = re.sub(r"[^0-9Kk]", "", text).upper()
    if not re.fullmatch(r"\d{1,8}[0-9K]", compact):
        return ""
    body, dv = compact[:-1], compact[-1]
    if _rut_dv(body) != dv:
        return ""
    canonical_body = str(int(body)) if body else "0"
    return f"{canonical_body}-{dv}"


def source_identifier_type(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "MISSING"
    if normalize_rut(raw):
        return "RUT"
    if SHA1_RE.fullmatch(raw):
        return "HASH_SHA1"
    return "SOURCE_ID"


def flag_is_true(value: object) -> bool:
    return normalize_text(value) in {"1", "TRUE", "T", "SI", "SÍ", "YES", "Y"}


def _digest(*parts: object, length: int = 18) -> str:
    payload = "|".join(normalize_text(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length].upper()


def organization_id(partida: object, capitulo: object, area: object, name: object = "") -> str:
    p = str(partida or "").zfill(2)
    c = str(capitulo or "").zfill(2)
    a = str(area or "").zfill(3)
    if p.strip("0") or c.strip("0") or a.strip("0"):
        return f"ORG-PA-{p}-{c}-{a}"
    return f"ORG-PA-{_digest(name)}"


def recipient_id(source_identifier: object, name: object = "", organization: object = "") -> str:
    raw = str(source_identifier or "").strip()
    rut = normalize_rut(raw)
    if rut:
        return f"RCV-RUT-{rut}"
    if SHA1_RE.fullmatch(raw):
        return f"RCV-SHA1-{raw.upper()}"
    if raw:
        return f"RCV-PA-{_digest(raw, name, organization, length=24)}"
    return f"RCV-NAME-{_digest(name, organization, length=24)}"


def provider_id(
    source_identifier: object,
    name: object = "",
    provider_flag: object = False,
    organization: object = "",
) -> str:
    """Create supplier ID only when the bulk `proveedor` flag says it is a supplier."""
    if not flag_is_true(provider_flag):
        return ""
    raw = str(source_identifier or "").strip()
    rut = normalize_rut(raw)
    if rut:
        return f"PRV-RUT-{rut}"
    if SHA1_RE.fullmatch(raw):
        return f"PRV-SHA1-{raw.upper()}"
    return f"PRV-PA-{_digest(raw, name, organization, length=24)}"


def transaction_id(row: dict) -> str:
    return "TRX-PA-" + _digest(
        row.get("periodo"),
        row.get("mes"),
        row.get("partida"),
        row.get("capitulo"),
        row.get("area"),
        row.get("beneficiario_source_id") or row.get("rut_beneficiario"),
        row.get("numero_documento"),
        row.get("folio"),
        row.get("fecha_documento"),
        row.get("monto_devengado"),
        row.get("fecha_pago"),
        row.get("monto_pago"),
        length=24,
    )
