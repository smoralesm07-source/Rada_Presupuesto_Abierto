from __future__ import annotations

"""Dónde ocurren desórdenes administrativos, según quien fiscaliza.

Cruzar los proveedores de la CGR con los del presupuesto es difícil: son
empresas, cambian de nombre y la fuente no publica RUT. Cruzar el **organismo
auditado** es otra cosa. Los servicios públicos son pocos, tienen razón social
canónica y el presupuesto ya los identifica por partida y capítulo.

Esta capa responde una pregunta más modesta y más sólida que la anterior: en qué
servicios públicos la Contraloría ha observado desórdenes administrativos. Eso
no acusa a nadie —una observación de auditoría no es un delito, y la mayoría
nunca lo será— pero es una base razonable para decidir dónde mirar primero.

La regla de seguridad
---------------------
El riesgo aquí no es no cruzar: es cruzar mal. `SERVICIO LOCAL DE EDUCACIÓN
PÚBLICA DE AYSÉN` se parece un 85% a `SERVICIO LOCAL DE EDUCACIÓN PÚBLICA DE
HUASCO`, y atribuirle a uno la auditoría del otro sería peor que no decir nada.

Por eso un parecido alto no basta. Cuando dos nombres comparten el prefijo
institucional pero difieren en la cola —el territorio, el nombre propio— se
exige que esa cola coincida. Si no coincide, son entidades distintas de la misma
familia y no se enlazan, por mucho que se parezcan.
"""

import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .cgr_correlation import _name_key, _read_jsonl, _similarity

SCHEMA = "RIGP-PUBLIC-SERVICE-AUDITS-v1"

GUARDRAIL = (
    "Una observación de auditoría de la Contraloría describe un desorden administrativo "
    "constatado por el órgano fiscalizador. No acredita delito, fraude ni responsabilidad "
    "penal de ninguna persona, y la mayoría de las observaciones nunca deriva en uno. "
    "Esta capa ordena dónde mirar primero, no a quién acusar."
)

MATCH_EXACT = "NOMBRE_EXACTO"
MATCH_ACRONYM = "SIGLA_EXPANDIDA"
MATCH_PARENT = "OFICINA_DE_SERVICIO"
MATCH_NONE = "SIN_CRUCE"

# Municipios y corporaciones municipales no forman parte del presupuesto de la
# Nación: rinden por otra vía. No es que el cruce falle, es que no aplica, y la
# diferencia importa para no leer su ausencia como cobertura incompleta.
OUT_OF_SCOPE_TYPES = {
    "MUNICIPALITY": (
        "Los municipios no integran el presupuesto de la Nación; su ejecución se "
        "reporta por otra vía y no existe un capítulo presupuestario que cruzar."
    ),
}

# Por qué un organismo real puede no tener capítulo propio. Una ausencia
# explicada vale mucho más que una genérica: dice si falta cobertura o si la
# entidad simplemente no ejecuta presupuesto de la Nación.
UNMATCHED_REASON = {
    "STATE_UNIVERSITY": (
        "Las universidades estatales no son capítulos del presupuesto de la Nación: "
        "reciben transferencias y ejecutan presupuesto propio. La auditoría es real; "
        "lo que no existe es un capítulo que cruzar."
    ),
    "HOSPITAL": (
        "Los hospitales públicos no son capítulos presupuestarios: ejecutan dentro del "
        "servicio de salud al que pertenecen. Para ubicar el gasto habría que resolver "
        "primero a qué servicio de salud corresponde, y esa relación no está en estos datos."
    ),
    "": (
        "Ningún capítulo presupuestario corresponde a este organismo. Puede ser una "
        "entidad que no ejecuta presupuesto propio o una fuera del presupuesto de la Nación."
    ),
}

# Siglas que la Contraloría usa y el presupuesto no. Es conocimiento de dominio,
# deliberadamente corto y explícito: cada entrada se puede verificar a mano.
ACRONYMS = {
    "INDAP": "INSTITUTO DE DESARROLLO AGROPECUARIO",
    "INJUV": "INSTITUTO NACIONAL DE LA JUVENTUD",
    "CONAF": "CORPORACION NACIONAL FORESTAL",
    "SERNAMEG": "SERVICIO NACIONAL DE LA MUJER Y LA EQUIDAD DE GENERO",
    "SENAME": "SERVICIO NACIONAL DE MENORES",
    "SENADIS": "SERVICIO NACIONAL DE LA DISCAPACIDAD",
    "SENCE": "SERVICIO NACIONAL DE CAPACITACION Y EMPLEO",
    "JUNAEB": "JUNTA NACIONAL DE AUXILIO ESCOLAR Y BECAS",
    "JUNJI": "JUNTA NACIONAL DE JARDINES INFANTILES",
    "SERVIU": "SERVICIO DE VIVIENDA Y URBANIZACION",
    "CORFO": "CORPORACION DE FOMENTO DE LA PRODUCCION",
    "DGA": "DIRECCION GENERAL DE AGUAS",
    "IPS": "INSTITUTO DE PREVISION SOCIAL",
    "SLEP": "SERVICIO LOCAL DE EDUCACION",
}

# Palabras que no distinguen a una entidad de otra de su misma familia.
STOPWORDS = {
    "DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "EN", "A", "PARA", "POR",
    "SERVICIO", "SERVICIOS", "INSTITUTO", "DIRECCION", "REGIONAL", "NACIONAL",
    "PUBLICA", "PUBLICO", "CORPORACION", "COMISION", "JUNTA", "SUBSECRETARIA",
    "HOSPITAL", "UNIVERSIDAD", "MUNICIPALIDAD", "SALUD", "EDUCACION", "LOCAL",
    "OFICINA", "GENERAL", "CHILE", "AGENCIA", "SUPERINTENDENCIA",
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _tokens(name: str) -> list[str]:
    return [t for t in _strip_accents(_name_key(name)).split() if t]


def expand_acronyms(name: str) -> str:
    """Reemplaza siglas conocidas por la razón social que usa el presupuesto."""
    out = []
    for token in _tokens(name):
        out.append(ACRONYMS.get(token, token))
    return " ".join(out)


def discriminators(name: str) -> set[str]:
    """Lo que distingue a esta entidad de otra de su misma familia.

    De `SERVICIO LOCAL DE EDUCACIÓN PÚBLICA DE AYSÉN` queda `{AYSEN}`: el resto
    lo comparte con cualquier otro SLEP del país.
    """
    return {t for t in _tokens(name) if t not in STOPWORDS and not t.isdigit()}


def same_entity(audited: str, candidate: str) -> tuple[bool, str]:
    """¿Son la misma entidad, o dos de la misma familia?

    Devuelve además por qué, porque un enlace que no explica su base no es
    verificable.
    """
    a, b = discriminators(audited), discriminators(candidate)
    if not a and not b:
        return True, "ninguna de las dos aporta un distintivo; el nombre institucional es todo"
    if not b:
        # El presupuesto nombra al servicio y la CGR a una de sus oficinas.
        return True, f"el organismo auditado añade {sorted(a)} sobre el servicio presupuestario"
    if not a:
        return True, f"el servicio presupuestario añade {sorted(b)} sobre el organismo auditado"
    # Subconjunto, no intersección. Compartir un distintivo no basta: `INJUV
    # VALPARAÍSO` e `INJUV ANTOFAGASTA` comparten «JUVENTUD» y son servicios
    # distintos. Sólo cuando los distintivos de uno contienen a los del otro
    # estamos ante la misma entidad vista con más o menos detalle.
    if a <= b:
        return True, f"el servicio presupuestario precisa {sorted(b - a)} sobre el organismo auditado"
    if b <= a:
        return True, f"el organismo auditado precisa {sorted(a - b)} sobre el servicio presupuestario"
    return False, (
        f"distintivos incompatibles: el auditado dice {sorted(a - b)} y el candidato {sorted(b - a)}. "
        "Son entidades distintas de la misma familia."
    )


def service_catalog(parquet_glob: str) -> list[dict]:
    """Servicios públicos del presupuesto, a nivel de partida y capítulo.

    El capítulo es el servicio; el área es un programa suyo. La Contraloría
    audita servicios, así que es ahí donde hay que cruzar.
    """
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT
              'SRV-PA-' || lpad(cast(partida AS VARCHAR),2,'0') || '-'
                        || lpad(cast(capitulo AS VARCHAR),2,'0') AS service_id,
              any_value(nombre_capitulo) AS service_name,
              any_value(nombre_partida) AS ministry_name,
              count(DISTINCT organization_id) AS programs,
              count(DISTINCT provider_id) FILTER (WHERE coalesce(provider_id,'')<>'') AS providers,
              sum(coalesce(try_cast(monto_devengado AS DOUBLE),0)) AS amount_clp,
              min(try_cast(periodo AS INTEGER)) AS first_year,
              max(try_cast(periodo AS INTEGER)) AS last_year
            FROM read_parquet('{parquet_glob}', union_by_name=true)
            WHERE coalesce(nombre_capitulo,'')<>''
            GROUP BY 1
            HAVING any_value(nombre_capitulo) IS NOT NULL
            """
        ).df()
    finally:
        con.close()
    return rows.to_dict("records")


def match_audited_body(audited: dict, catalog: list[dict]) -> dict:
    """Cruza un organismo auditado con un servicio presupuestario, o explica por qué no."""
    name = str(audited.get("name") or "")
    kind = str(audited.get("organization_type") or "")

    if kind in OUT_OF_SCOPE_TYPES:
        return {"method": MATCH_NONE, "service": None, "out_of_scope": True,
                "why": OUT_OF_SCOPE_TYPES[kind]}

    audited_key = _name_key(name)
    audited_expanded = expand_acronyms(name)

    best = None
    for service in catalog:
        service_name = str(service.get("service_name") or "")
        if not service_name:
            continue
        service_key = _name_key(service_name)
        for candidate_key, method in ((audited_key, MATCH_EXACT), (_name_key(audited_expanded), MATCH_ACRONYM)):
            similarity = _similarity(candidate_key, service_key)
            compared = audited_expanded if method == MATCH_ACRONYM else name
            ok, why = same_entity(compared, service_name)
            if not ok:
                continue
            # Dos caminos al cruce. El léxico exige parecido de cadenas; el
            # estructural se apoya en que los distintivos del servicio estén
            # contenidos en los del organismo auditado, que es evidencia más
            # fuerte que el parecido textual: «Dirección Regional Metropolitana
            # del INDAP» se parece un 60% a «Instituto de Desarrollo
            # Agropecuario» y es exactamente ese servicio.
            service_marks = discriminators(service_name)
            structural = len(service_marks) >= 2 and service_marks <= discriminators(compared)
            if similarity < 0.72 and not structural:
                continue
            grade = MATCH_EXACT if similarity >= 0.99 else (
                MATCH_ACRONYM if method == MATCH_ACRONYM else MATCH_PARENT
            )
            score = (similarity, method == MATCH_EXACT)
            if best is None or score > best[0]:
                best = (score, {"method": grade, "service": service, "out_of_scope": False,
                                "similarity": round(float(similarity), 4), "why": why})
    if best:
        return best[1]
    return {"method": MATCH_NONE, "service": None, "out_of_scope": False,
            "why": UNMATCHED_REASON.get(kind, UNMATCHED_REASON[""])}


def build_public_service_audits(
    parquet_glob: str,
    cgr_silver_dir: str = "external/radar-cgr/data/silver",
    output_json: str = "docs/data/public_service_audits.json",
) -> dict:
    """Publica en qué servicios públicos la Contraloría observó desórdenes."""
    silver = Path(cgr_silver_dir)
    audited = _read_jsonl(silver / "organizations.jsonl")
    findings = _read_jsonl(silver / "findings.jsonl")
    by_document: dict[str, list[dict]] = {}
    for row in findings:
        by_document.setdefault(str(row.get("document_id") or ""), []).append(row)

    catalog = service_catalog(parquet_glob) if audited else []
    services: dict[str, dict] = {}
    unmatched: list[dict] = []
    out_of_scope: list[dict] = []

    for body in audited:
        result = match_audited_body(body, catalog)
        document = str(body.get("source_document_id") or "")
        observations = by_document.get(document, [])
        record = {
            "audited_name": body.get("name"),
            "organization_type": body.get("organization_type"),
            "region": body.get("region") or None,
            "commune": body.get("commune") or None,
            "source_document_id": document or None,
            "observation_count": len(observations),
            "match_method": result["method"],
            "match_reason": result["why"],
        }
        if result["out_of_scope"]:
            out_of_scope.append(record)
            continue
        if result["service"] is None:
            unmatched.append(record)
            continue

        service = result["service"]
        entry = services.setdefault(str(service["service_id"]), {
            "service_id": service["service_id"],
            "service_name": service["service_name"],
            "ministry_name": service.get("ministry_name"),
            "programs": int(service.get("programs") or 0),
            "providers": int(service.get("providers") or 0),
            "amount_clp": float(service.get("amount_clp") or 0),
            "audited_bodies": [],
            "observation_count": 0,
        })
        entry["audited_bodies"].append({**record, "similarity": result.get("similarity")})
        entry["observation_count"] += len(observations)

    ordered = sorted(
        services.values(),
        key=lambda s: (-s["observation_count"], -len(s["audited_bodies"]), s["service_name"]),
    )
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guardrail": GUARDRAIL,
        "method": (
            "Se cruza el organismo auditado por la Contraloría con el servicio del "
            "presupuesto a nivel de partida y capítulo. Un parecido alto no basta: cuando "
            "dos nombres comparten el prefijo institucional y difieren en la cola, se exige "
            "que los distintivos de uno contengan a los del otro, para no atribuirle a un "
            "servicio la auditoría de otro de su misma familia."
        ),
        "coverage": {
            "audited_bodies": len(audited),
            "matched_bodies": sum(len(s["audited_bodies"]) for s in ordered),
            "services_with_observations": len(ordered),
            "out_of_scope_bodies": len(out_of_scope),
            "unmatched_bodies": len(unmatched),
            "budget_services": len(catalog),
        },
        "services": ordered,
        # Lo que no se pudo cruzar se publica con su razón, para que la ausencia de
        # un servicio en la lista no se lea como ausencia de observaciones.
        "out_of_scope": out_of_scope,
        "unmatched": unmatched,
    }
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload
