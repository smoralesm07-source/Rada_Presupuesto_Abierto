from __future__ import annotations

import json
from pathlib import Path


def canon_rut(value: object) -> str:
    """Return a canonical Chilean RUT (body-DV) without inferring identity."""
    s = ''.join(ch for ch in str(value or '').upper() if ch.isdigit() or ch == 'K')
    if len(s) < 2:
        return ''
    return f'{s[:-1]}-{s[-1]}'


def rut_from_provider_id(provider_id: object) -> str:
    value = str(provider_id or '')
    prefix = 'PRV-RUT-'
    if not value.startswith(prefix):
        return ''
    return canon_rut(value[len(prefix):])


def target_ruts_from_payload(payload: dict) -> set[str]:
    """Resolve only RUTs explicitly present in a published RIGP target universe.

    Preferred input is investigative_findings.json. Legacy provider lists remain
    supported only for backwards-compatible manual runs. Names and hashes are never
    converted into RUTs.
    """
    out: set[str] = set()

    relations = payload.get('relation_findings') or []
    for row in relations:
        rut = rut_from_provider_id(row.get('provider_id'))
        if not rut:
            rut = canon_rut(row.get('provider_rut') or row.get('rut'))
        if rut:
            out.add(rut)

    # Compatibility with legacy spend-view/manual extracts. It is intentionally a
    # fallback and is ignored when relation findings are present.
    if not relations:
        for provider in payload.get('providers') or []:
            rut = canon_rut(provider.get('rut'))
            if rut:
                out.add(rut)

    return out


def target_ruts_from_file(path: str | Path) -> set[str]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding='utf-8'))
    return target_ruts_from_payload(payload)
