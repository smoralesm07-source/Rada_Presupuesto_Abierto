from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import duckdb
import pandas as pd

from .ids import normalize_text

LINK_COLUMNS = [
    "evidence_link_id","local_entity_type","local_entity_id","local_name",
    "external_system","external_entity_id","external_name","external_document_id",
    "match_method","name_similarity","region_agreement","confidence","status",
    "cgr_finding_count","cgr_max_aml_score","cgr_max_severity","cgr_risk_families",
    "cgr_source_urls","match_basis",
]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _name_key(value: object) -> str:
    text = normalize_text(value)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\bSOCIEDAD ANONIMA\b", " SA ", text)
    text = re.sub(r"\bLIMITADA\b", " LTDA ", text)
    text = re.sub(r"\bE I R L\b", " EIRL ", text)
    text = re.sub(r"\bS P A\b", " SPA ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(Y|E)\s+(?=[A-Z0-9])", "", text)
    return text


def _token_jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return 0.65 * SequenceMatcher(None, a, b).ratio() + 0.35 * _token_jaccard(a, b)


def _region_agrees(a: object, b: object) -> bool | None:
    x, y = _name_key(a), _name_key(b)
    if not x or not y:
        return None
    return x in y or y in x


def _finding_index(findings: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in findings:
        doc = str(row.get("document_id") or "").strip()
        if doc:
            grouped[doc].append(row)
    out: dict[str, dict] = {}
    sev_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0}
    for doc, rows in grouped.items():
        scores = [r.get("aml_score") for r in rows if isinstance(r.get("aml_score"), (int, float))]
        severities = [str(r.get("severity") or "").upper() for r in rows]
        urls = sorted({str(r.get("source_url") or "") for r in rows if r.get("source_url")})
        families = sorted({str(r.get("risk_family") or "") for r in rows if r.get("risk_family")})
        out[doc] = {
            "count": len(rows),
            "max_aml_score": max(scores) if scores else None,
            "max_severity": max(severities, key=lambda s: sev_rank.get(s, 0), default=""),
            "risk_families": families,
            "source_urls": urls[:10],
        }
    return out


def _best_external_match(local_names: list[str], local_region: object, candidates: list[dict], external_id_field: str, fuzzy_floor: float = 0.94) -> tuple[dict | None, str, float, bool | None]:
    best: tuple[float, dict | None, str, bool | None] = (0.0, None, "", None)
    local_keys = [x for x in (_name_key(n) for n in local_names) if x]
    for ext in candidates:
        ext_key = _name_key(ext.get("normalized_name") or ext.get("name"))
        if not ext_key or not ext.get(external_id_field):
            continue
        for key in local_keys:
            sim = _similarity(key, ext_key)
            if sim > best[0]:
                best = (sim, ext, key, _region_agrees(local_region, ext.get("region")))
    if best[1] is None:
        return None, "", 0.0, None
    sim, ext, _, region_ok = best
    if sim == 1.0:
        return ext, "EXACT_NORMALIZED_NAME", sim, region_ok
    ext_key = _name_key(ext.get("normalized_name") or ext.get("name"))
    if sim >= fuzzy_floor and any(_token_jaccard(k, ext_key) >= 0.60 for k in local_keys):
        return ext, "FUZZY_NAME_HIGH", sim, region_ok
    return None, "", sim, region_ok


def _make_link(local_type: str, local_id: str, local_name: str, ext: dict, ext_id_field: str, method: str, similarity: float, region_ok: bool | None, findings_by_doc: dict[str, dict]) -> dict:
    ext_id = str(ext.get(ext_id_field) or "")
    doc = str(ext.get("source_document_id") or "")
    cgr_conf = float(ext.get("confidence") or 0.75)
    base = 0.92 if method == "EXACT_NORMALIZED_NAME" else 0.82
    if region_ok is True:
        base += 0.03
    elif region_ok is False:
        base -= 0.07
    confidence = max(0.0, min(0.93, base * (0.75 + 0.25 * cgr_conf)))
    finding = findings_by_doc.get(doc, {})
    payload = f"{local_type}|{local_id}|{ext_id}|{doc}|{method}"
    link_id = "EVL-PA-CGR-" + hashlib.sha256(payload.encode()).hexdigest()[:24].upper()
    return {
        "evidence_link_id": link_id,
        "local_entity_type": local_type,
        "local_entity_id": local_id,
        "local_name": local_name,
        "external_system": "RADAR_CGR",
        "external_entity_id": ext_id,
        "external_name": str(ext.get("name") or ""),
        "external_document_id": doc,
        "match_method": method,
        "name_similarity": round(float(similarity), 6),
        "region_agreement": region_ok,
        "confidence": round(confidence, 6),
        "status": "CANDIDATE",
        "cgr_finding_count": int(finding.get("count") or 0),
        "cgr_max_aml_score": finding.get("max_aml_score"),
        "cgr_max_severity": finding.get("max_severity") or "",
        "cgr_risk_families": json.dumps(finding.get("risk_families") or [], ensure_ascii=False),
        "cgr_source_urls": json.dumps(finding.get("source_urls") or [], ensure_ascii=False),
        "match_basis": json.dumps({"name": method,"similarity": round(float(similarity), 6),"region_agreement": region_ok,"note": "Coincidencia de entidad candidata; no prueba que una transacción específica corresponda al hallazgo CGR."}, ensure_ascii=False),
    }


def correlate_with_cgr(parquet_glob: str, cgr_silver_dir: str = "external/radar-cgr/data/silver", output_parquet: str = "data/evidence/cgr_evidence_links.parquet", output_json: str = "docs/data/cgr_correlation.json") -> dict:
    cgr = Path(cgr_silver_dir)
    cgr_providers = _read_jsonl(cgr / "providers.jsonl")
    cgr_orgs = _read_jsonl(cgr / "organizations.jsonl")
    findings = _read_jsonl(cgr / "findings.jsonl")
    finding_map = _finding_index(findings)

    con = duckdb.connect()
    con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)")
    pa_providers = con.execute("""
        SELECT provider_id,any_value(nombre_beneficiario) nombre,
               any_value(region) region,any_value(rut_beneficiario) rut
        FROM facts WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' GROUP BY 1
    """).df()
    pa_orgs = con.execute("""
        SELECT organization_id,any_value(nombre_area) area,
               any_value(nombre_capitulo) servicio,any_value(nombre_partida) institucion,
               any_value(region) region FROM facts GROUP BY 1
    """).df()
    con.close()

    links: list[dict] = []
    for row in pa_providers.to_dict("records"):
        ext, method, sim, region_ok = _best_external_match([str(row.get("nombre") or "")], row.get("region"), cgr_providers, "provider_id")
        if ext:
            links.append(_make_link("PROVIDER", str(row["provider_id"]), str(row.get("nombre") or ""), ext, "provider_id", method, sim, region_ok, finding_map))

    for row in pa_orgs.to_dict("records"):
        names = [str(row.get("area") or ""),str(row.get("servicio") or ""),str(row.get("institucion") or "")]
        ext, method, sim, region_ok = _best_external_match(names, row.get("region"), cgr_orgs, "organization_id")
        if ext:
            local_name = next((n for n in names if n), str(row["organization_id"]))
            links.append(_make_link("ORGANIZATION", str(row["organization_id"]), local_name, ext, "organization_id", method, sim, region_ok, finding_map))

    out_parquet = Path(output_parquet)
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    if links:
        pd.DataFrame(links, columns=LINK_COLUMNS).to_parquet(out_parquet, index=False)
    elif out_parquet.exists():
        out_parquet.unlink()

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "external_system": "RADAR_CGR",
        "status": "OK" if cgr_providers or cgr_orgs else "NO_CGR_DATA",
        "links": len(links),
        "provider_links": sum(x["local_entity_type"] == "PROVIDER" for x in links),
        "organization_links": sum(x["local_entity_type"] == "ORGANIZATION" for x in links),
        "links_with_findings": sum(x["cgr_finding_count"] > 0 for x in links),
        "high_confidence_links": sum(float(x["confidence"]) >= 0.88 for x in links),
        "methodology": "Cruce conservador por nombre normalizado y, cuando está disponible, región. Cada enlace permanece CANDIDATE; no atribuye un hallazgo CGR a una transacción específica.",
        "top_links": sorted(links, key=lambda x: (float(x.get("confidence") or 0),int(x.get("cgr_max_aml_score") or 0),int(x.get("cgr_finding_count") or 0)), reverse=True)[:50],
    }
    out_json = Path(output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
