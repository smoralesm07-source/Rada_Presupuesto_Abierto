from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text.upper()).strip()
    return text


def normalize_rut(value: object) -> str:
    raw = re.sub(r"[^0-9Kk]", "", str(value or ""))
    if len(raw) < 2:
        return ""
    return f"{raw[:-1]}-{raw[-1].upper()}"


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


def provider_id(rut: object, name: object = "") -> str:
    nrut = normalize_rut(rut)
    if nrut:
        return f"PRV-RUT-{nrut}"
    return f"PRV-PA-{_digest(name)}"


def transaction_id(row: dict) -> str:
    return "TRX-PA-" + _digest(
        row.get("periodo"), row.get("mes"), row.get("partida"), row.get("capitulo"),
        row.get("area"), row.get("rut_beneficiario"), row.get("numero_documento"),
        row.get("folio"), row.get("fecha_documento"), row.get("monto_devengado"),
        row.get("fecha_pago"), row.get("monto_pago"), length=24,
    )
