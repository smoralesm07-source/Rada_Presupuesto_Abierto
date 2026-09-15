from __future__ import annotations

"""Señales de la capa de entidad, derivadas del enriquecimiento SII publicado.

Estas señales describen a la **contraparte**, no a la transacción: qué edad
tiene la empresa cuando empieza a recibir dinero público, si su capacidad de
ventas declarada es consistente con lo que se le paga, si su giro registrado es
inusual para la línea presupuestaria, y si termina giro poco después de cobrar.

Por qué importan más allá de sí mismas
--------------------------------------
Hasta ahora las siete señales del radar venían todas de la capa de transacción.
Una hipótesis que exige dos patrones concurrentes (`pattern_compatibility`) casi
nunca se sostenía, porque los patrones disponibles no eran independientes entre
sí: miraban el mismo pago desde ángulos parecidos. Esta capa aporta evidencia de
**otra naturaleza**, que es lo que permite que una concentración de gasto y un
proveedor recién creado se corroboren mutuamente.

Ninguna de estas señales afirma irregularidad. Un proveedor joven, uno pequeño o
uno que cierra son hechos ordinarios del mundo. Ordenan prioridad de revisión
documental, nada más, y cada fila declara el supuesto sobre el que se calculó.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .ids import normalize_rut

ENRICHMENT_PATH = "docs/data/entity_enrichment_v1.json"
OUTPUT_PARQUET = "data/signals/entity_signals.parquet"
OUTPUT_JSON = "docs/data/entity_signals.json"
RISK_SIGNALS_PATH = "data/signals/risk_signals.parquet"

ENTITY_SIGNAL_TYPES = (
    "NEWBORN_SUPPLIER",
    "CAPACITY_MISMATCH",
    "ACTIVITY_MISMATCH",
    "TERMINATION_AFTER_PAYMENT",
    "DORMANT_REACTIVATION",
)

GUARDRAIL = (
    "Señal de contraparte derivada de datos registrales publicados. Antigüedad, "
    "tamaño, giro o término de giro no constituyen por sí mismos indicio de "
    "irregularidad; ordenan prioridad de revisión documental."
)

HYPOTHESIS = (
    "Característica registral de la contraparte que requiere explicación "
    "documental; no implica irregularidad por sí sola."
)

# El SII publica el tamaño del contribuyente en tramos de ventas anuales
# expresados en UF. El techo de cada tramo se usa sólo como referencia de
# capacidad declarada; el tramo superior no tiene techo y por eso nunca genera
# señal.
SALES_BAND_UPPER_UF: dict[int, float | None] = {
    1: 0.0,
    2: 200.0,
    3: 600.0,
    4: 2_400.0,
    5: 5_000.0,
    6: 10_000.0,
    7: 25_000.0,
    8: 50_000.0,
    9: 100_000.0,
    10: 200_000.0,
    11: 600_000.0,
    12: 1_000_000.0,
    13: None,
}

DEFAULT_UF_CLP = 39_000.0


ACTIVITY_BREADTH_PERCENTILE = 0.90
ACTIVITY_BREADTH_FLOOR = 4
ACTIVITY_BREADTH_MIN_PEERS = 12
ACTIVITY_BREADTH_FALLBACK = 6


def activity_breadth_thresholds(counts_by_band: dict[int, list[int]]) -> dict[int, int]:
    """Umbral de amplitud de giros medido dentro del propio tramo de ventas.

    Un umbral absoluto —«seis actividades o más»— no mide rareza sino tamaño:
    sobre las 848 entidades con tramo publicado dispara en el 21% de los tramos
    11 a 13 y en el 12% de los tramos 1 a 8. Nueve giros son corrientes en un
    conglomerado y llamativos en una sociedad pequeña, y el umbral no puede ser
    el mismo para los dos. Se usa el percentil 90 del propio tramo, con un piso
    para que un tramo homogéneo no marque a cualquiera, y con el umbral fijo de
    respaldo cuando el tramo tiene pocos pares para medir.
    """
    thresholds: dict[int, int] = {}
    for band, counts in counts_by_band.items():
        if len(counts) < ACTIVITY_BREADTH_MIN_PEERS:
            thresholds[band] = ACTIVITY_BREADTH_FALLBACK
            continue
        ordered = sorted(counts)
        index = min(len(ordered) - 1, int(ACTIVITY_BREADTH_PERCENTILE * len(ordered)))
        thresholds[band] = max(ACTIVITY_BREADTH_FLOOR, ordered[index])
    return thresholds


def band_median(counts: list[int]) -> int:
    ordered = sorted(counts)
    return ordered[len(ordered) // 2] if ordered else 0


def is_placeholder_rut(rut: str) -> bool:
    """Los RUT comodín agregan receptores sin RUT propio: son cubos contables.

    Cualquier señal de contraparte sobre ellos es ruido por construcción.
    """
    body = str(rut or "").split("-", 1)[0]
    return bool(body) and len(set(body)) == 1 and len(body) >= 7


def _signal_id(kind: str, key: str) -> str:
    digest = hashlib.sha256(f"{kind}|{key}".encode()).hexdigest()[:20].upper()
    return f"SIG-ENT-{kind}-{digest}"


def _rut_from_provider_id(provider_id: object) -> str:
    token = str(provider_id or "")
    if "RUT-" not in token:
        return ""
    return normalize_rut(token.split("RUT-", 1)[1])


def _months_between(later: object, earlier: object) -> float | None:
    a, b = pd.to_datetime(later, errors="coerce"), pd.to_datetime(earlier, errors="coerce")
    if pd.isna(a) or pd.isna(b):
        return None
    return (a - b).days / 30.4375


def load_enrichment(path: str | Path = ENRICHMENT_PATH) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    payload = json.loads(p.read_text(encoding="utf-8"))
    entities = payload.get("entities") or {}
    out: dict[str, dict] = {}
    for raw_rut, entity in entities.items():
        rut = normalize_rut(entity.get("rut") or raw_rut)
        if rut and not is_placeholder_rut(rut):
            out[rut] = entity
    return out


def provider_payment_profile(parquet_glob: str) -> pd.DataFrame:
    """Pagos públicos observados, agregados por proveedor y año."""
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            WITH base AS (
              SELECT provider_id,
                     periodo,
                     try_cast(monto_devengado AS DOUBLE) AS amount,
                     try_cast(fecha_documento AS DATE) AS doc_date,
                     nombre_beneficiario AS provider_name,
                     organization_id,
                     coalesce(subtitulo,'') AS subtitulo
              FROM read_parquet('{parquet_glob}', union_by_name=true)
              WHERE is_provider = TRUE
                AND coalesce(provider_id,'') <> ''
                AND coalesce(is_aggregated, FALSE) = FALSE
                AND try_cast(monto_devengado AS DOUBLE) > 0
            )
            SELECT provider_id,
                   any_value(provider_name) AS provider_name,
                   periodo,
                   sum(amount) AS amount_year,
                   min(doc_date) AS first_doc_date,
                   max(doc_date) AS last_doc_date,
                   count(*) AS tx_count,
                   count(DISTINCT organization_id) AS organizations,
                   string_agg(DISTINCT subtitulo, '|') AS subtitulos
            FROM base
            GROUP BY provider_id, periodo
            """
        ).df()
    finally:
        con.close()


def provider_relations(parquet_glob: str) -> pd.DataFrame:
    """Las relaciones organismo-proveedor-año a las que alcanza una señal.

    Una señal de entidad es un hecho del proveedor, no de un organismo. Debe
    llegar a todas sus relaciones del período, o la corroboración dependería de
    a qué organismo le tocó el `any_value`.
    """
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            SELECT DISTINCT provider_id, organization_id, periodo
            FROM read_parquet('{parquet_glob}', union_by_name=true)
            WHERE is_provider = TRUE
              AND coalesce(provider_id,'') <> ''
              AND coalesce(organization_id,'') <> ''
              AND coalesce(is_aggregated, FALSE) = FALSE
              AND try_cast(monto_devengado AS DOUBLE) > 0
            """
        ).df()
    finally:
        con.close()


def _activity_divisions(entity: dict) -> set[str]:
    out: set[str] = set()
    for act in entity.get("acteco") or []:
        code = str(act.get("codigo") or "").strip()
        if len(code) >= 2 and code[:2].isdigit():
            out.add(code[:2])
    return out


def _peer_activity_profile(
    profile: pd.DataFrame, enrichment: dict[str, dict], share_floor: float
) -> dict[str, set[str]]:
    """Aprende, por subtítulo, qué divisiones ACTECO cargan realmente el gasto.

    El conjunto de referencia es empírico: es lo que hacen normalmente los
    proveedores de esa línea presupuestaria, no una taxonomía externa. Un
    proveedor fuera de él es candidato a revisión, nunca una conclusión.
    """
    totals: dict[str, float] = {}
    by_division: dict[str, dict[str, float]] = {}
    for row in profile.itertuples():
        entity = enrichment.get(_rut_from_provider_id(row.provider_id))
        if not entity:
            continue
        divisions = _activity_divisions(entity)
        if not divisions:
            continue
        amount = float(row.amount_year or 0)
        for sub in str(row.subtitulos or "").split("|"):
            sub = sub.strip()
            if not sub:
                continue
            totals[sub] = totals.get(sub, 0.0) + amount
            bucket = by_division.setdefault(sub, {})
            for div in divisions:
                bucket[div] = bucket.get(div, 0.0) + amount / len(divisions)
    reference: dict[str, set[str]] = {}
    for sub, bucket in by_division.items():
        total = totals.get(sub, 0.0)
        if total > 0:
            reference[sub] = {d for d, v in bucket.items() if v / total >= share_floor}
    return reference


def build_entity_signals(
    parquet_glob: str,
    enrichment_path: str | Path = ENRICHMENT_PATH,
    output_parquet: str | Path = OUTPUT_PARQUET,
    output_json: str | Path | None = OUTPUT_JSON,
    config: dict | None = None,
) -> dict:
    """Detecta señales de contraparte y las publica como capa propia."""
    cfg = config or {}
    newborn = cfg.get("newborn_supplier", {})
    capacity = cfg.get("capacity_mismatch", {})
    activity = cfg.get("activity_mismatch", {})
    termination = cfg.get("termination_after_payment", {})
    dormant = cfg.get("dormant_reactivation", {})
    uf_clp = float(cfg.get("uf_clp_reference", DEFAULT_UF_CLP))

    enrichment = load_enrichment(enrichment_path)
    profile = provider_payment_profile(parquet_glob)
    rows: list[dict] = []

    if profile.empty or not enrichment:
        return _write(rows, output_parquet, enrichment, profile, uf_clp, output_json)

    reference = _peer_activity_profile(
        profile, enrichment, float(activity.get("peer_division_share_floor", 0.02))
    )

    for provider, group in profile.sort_values("periodo").groupby("provider_id"):
        rut = _rut_from_provider_id(provider)
        entity = enrichment.get(rut)
        if not entity:
            continue
        provider_name = str(group["provider_name"].iloc[0] or provider)
        first_doc = pd.to_datetime(group["first_doc_date"], errors="coerce").min()
        last_doc = pd.to_datetime(group["last_doc_date"], errors="coerce").max()
        total_amount = float(group["amount_year"].sum())
        years = sorted(int(y) for y in group["periodo"].dropna().unique())

        common = {
            "provider_id": provider,
            "provider_name": provider_name,
            "rut": rut,
            "entity_id": entity.get("entity_id") or f"ENT-RUT-{rut}",
            "record_class": "DERIVED_SIGNAL",
            "confidence": "MEDIUM",
            "guardrail": GUARDRAIL,
        }

        # --- Proveedor recién creado al recibir su primer pago ---------------
        start_date = entity.get("start_date") or ""
        months_old = _months_between(first_doc, start_date) if start_date else None
        max_months = float(newborn.get("max_months_since_start", 12))
        if (
            months_old is not None
            and 0 <= months_old <= max_months
            and total_amount >= float(newborn.get("min_amount", 20_000_000))
        ):
            rows.append({
                **common,
                "signal_type": "NEWBORN_SUPPLIER",
                "severity": "HIGH" if months_old <= 6 else "MEDIUM",
                "periodo": years[0] if years else None,
                "observed_value": round(float(months_old), 2),
                "expected_value": max_months,
                "deviation": None,
                "why_flagged": (
                    f"Primer pago público a {round(months_old)} meses del inicio de "
                    f"actividades declarado ({start_date}), por ${total_amount:,.0f} acumulados."
                ),
                "assumption": (
                    "Inicio de actividades según snapshot SII publicado; no acredita "
                    "fecha de constitución societaria."
                ),
                "recommended_checks": [
                    "Revisar la adjudicación o el acto que originó el primer pago",
                    "Verificar constitución societaria y socios al momento de adjudicar",
                    "Comparar con otros proveedores nuevos del mismo organismo",
                ],
            })

        # --- Capacidad declarada incompatible con lo pagado ------------------
        band = entity.get("sales_band_code")
        band_code = int(band) if isinstance(band, (int, float)) and not pd.isna(band) else None
        min_capacity_amount = float(capacity.get("min_amount", 20_000_000))
        min_ratio = float(capacity.get("min_ratio", 3.0))
        for row in group.itertuples():
            amount_year = float(row.amount_year or 0)
            if band_code is None or amount_year < min_capacity_amount:
                continue
            upper_uf = SALES_BAND_UPPER_UF.get(band_code)
            if upper_uf is None:
                continue  # tramo superior sin techo declarado: nunca genera señal
            ceiling_clp = upper_uf * uf_clp
            if band_code == 1:
                ratio, severity = None, "HIGH"
                why = (
                    f"Recibe ${amount_year:,.0f} en {int(row.periodo)} y el SII lo "
                    "publica en el tramo sin ventas declaradas."
                )
            else:
                if ceiling_clp <= 0 or amount_year / ceiling_clp < min_ratio:
                    continue
                ratio = amount_year / ceiling_clp
                severity = "HIGH" if ratio >= min_ratio * 2 else "MEDIUM"
                why = (
                    f"Recibe ${amount_year:,.0f} en {int(row.periodo)}, {ratio:.1f}x el "
                    f"techo de ventas del tramo SII {band_code} (~${ceiling_clp:,.0f})."
                )
            rows.append({
                **common,
                "signal_type": "CAPACITY_MISMATCH",
                "severity": severity,
                "periodo": int(row.periodo) if not pd.isna(row.periodo) else None,
                "observed_value": amount_year,
                "expected_value": ceiling_clp or None,
                "deviation": ratio,
                "why_flagged": why,
                "assumption": (
                    f"Techo de tramo convertido a CLP con UF de referencia ${uf_clp:,.0f}. "
                    f"El tramo corresponde al año comercial {entity.get('commercial_year')} "
                    "publicado, que puede no coincidir con el año del pago."
                ),
                "recommended_checks": [
                    "Contrastar el tramo con el año comercial efectivamente pagado",
                    "Revisar si el proveedor subcontrata o actúa como intermediario",
                    "Verificar capacidad operativa: trabajadores, activos, domicilio",
                ],
            })

        # --- Giro registrado ajeno a la línea presupuestaria -----------------
        divisions = _activity_divisions(entity)
        if divisions and total_amount >= float(activity.get("min_amount", 50_000_000)):
            subs = {s.strip() for s in "|".join(group["subtitulos"].fillna("")).split("|") if s.strip()}
            mismatched = [s for s in subs if reference.get(s) and not (divisions & reference[s])]
            if mismatched:
                rows.append({
                    **common,
                    "signal_type": "ACTIVITY_MISMATCH",
                    "severity": "MEDIUM",
                    "periodo": years[-1] if years else None,
                    "observed_value": float(len(mismatched)),
                    "expected_value": None,
                    "deviation": None,
                    "why_flagged": (
                        "El giro registrado (divisiones ACTECO "
                        + ", ".join(sorted(divisions))
                        + ") no aparece entre las actividades que concentran el gasto en los "
                        "subtítulos " + ", ".join(sorted(mismatched)) + "."
                    ),
                    "assumption": (
                        "El perfil de actividades esperadas se aprende del propio gasto "
                        "observado, no de una taxonomía externa."
                    ),
                    "recommended_checks": [
                        "Revisar el objeto efectivamente contratado",
                        "Verificar si el giro fue ampliado antes o después de contratar",
                        "Descartar intermediación o reventa legítima",
                    ],
                })

        # --- Término de giro poco después de cobrar --------------------------
        termination_date = entity.get("termination_date") or ""
        if termination_date:
            months_after = _months_between(termination_date, last_doc)
            max_after = float(termination.get("max_months_after_last_payment", 12))
            if (
                months_after is not None
                and 0 <= months_after <= max_after
                and total_amount >= float(termination.get("min_amount", 20_000_000))
            ):
                rows.append({
                    **common,
                    "signal_type": "TERMINATION_AFTER_PAYMENT",
                    "severity": "HIGH",
                    "periodo": years[-1] if years else None,
                    "observed_value": round(float(months_after), 2),
                    "expected_value": max_after,
                    "deviation": None,
                    "why_flagged": (
                        f"Término de giro el {termination_date}, {round(months_after)} meses "
                        f"después del último pago público registrado, tras "
                        f"${total_amount:,.0f} acumulados."
                    ),
                    "assumption": (
                        "Término de giro según snapshot SII publicado; la fecha registral "
                        "puede diferir del cese operativo."
                    ),
                    "recommended_checks": [
                        "Revisar si quedaron obligaciones contractuales pendientes",
                        "Verificar destino de los activos y continuidad de los socios",
                        "Contrastar con recepciones conformes y garantías",
                    ],
                })

        # --- Reaparición tras una ausencia larga -----------------------------
        min_gap = int(dormant.get("min_gap_years", 2))
        min_dormant_amount = float(dormant.get("min_amount", 50_000_000))
        for index in range(1, len(years)):
            gap = years[index] - years[index - 1]
            if gap <= min_gap:
                continue
            amount_after = float(group.loc[group["periodo"] == years[index], "amount_year"].sum())
            if amount_after < min_dormant_amount:
                continue
            rows.append({
                **common,
                "signal_type": "DORMANT_REACTIVATION",
                "severity": "MEDIUM",
                "periodo": years[index],
                "observed_value": float(gap),
                "expected_value": float(min_gap),
                "deviation": None,
                "why_flagged": (
                    f"Sin pagos públicos observados entre {years[index - 1]} y "
                    f"{years[index]}, y reaparece con ${amount_after:,.0f}."
                ),
                "assumption": (
                    "La ausencia se mide sólo sobre los años efectivamente procesados por "
                    "el radar, no sobre toda la historia del proveedor."
                ),
                "recommended_checks": [
                    "Confirmar la ausencia en la serie completa disponible",
                    "Revisar cambios de propiedad o administración en el intervalo",
                    "Revisar el acto que originó el reingreso",
                ],
            })

    return _write(rows, output_parquet, enrichment, profile, uf_clp, output_json)


COLUMNS = [
    "signal_id", "signal_type", "provider_id", "provider_name", "rut", "entity_id",
    "periodo", "severity", "confidence", "record_class", "observed_value",
    "expected_value", "deviation", "why_flagged", "assumption", "recommended_checks",
    "guardrail", "detected_at",
]


def _write(
    rows: list[dict],
    output_parquet: str | Path,
    enrichment: dict,
    profile: pd.DataFrame,
    uf_clp: float,
    output_json: str | Path | None,
) -> dict:
    for row in rows:
        row["signal_id"] = _signal_id(
            row["signal_type"], f"{row['provider_id']}|{row.get('periodo')}"
        )
        row["recommended_checks"] = json.dumps(row["recommended_checks"], ensure_ascii=False)

    df = pd.DataFrame(rows, columns=COLUMNS) if rows else pd.DataFrame(columns=COLUMNS)
    for col in ("observed_value", "expected_value", "deviation"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["periodo"] = pd.to_numeric(df.get("periodo"), errors="coerce").astype("Int64")
    df["detected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out = Path(output_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    providers_in_scope = int(profile["provider_id"].nunique()) if not profile.empty else 0
    matched = 0
    if not profile.empty:
        matched = sum(
            1 for pid in profile["provider_id"].unique()
            if _rut_from_provider_id(pid) in enrichment
        )
    result = {
        "path": str(out),
        "signals": int(len(df)),
        "distinct_signal_ids": int(df["signal_id"].nunique()) if len(df) else 0,
        "by_type": df["signal_type"].value_counts().to_dict() if len(df) else {},
        "providers_in_scope": providers_in_scope,
        "providers_with_registry_profile": matched,
        "registry_coverage": round(matched / providers_in_scope, 6) if providers_in_scope else 0.0,
        "uf_clp_reference": uf_clp,
    }

    if output_json:
        by_provider: dict[str, dict] = {}
        for row in rows:
            entry = by_provider.setdefault(str(row["provider_id"]), {
                "provider_id": row["provider_id"],
                "provider_name": row["provider_name"],
                "rut": row["rut"],
                "signals": [],
            })
            entry["signals"].append({
                "signal_type": row["signal_type"],
                "severity": row["severity"],
                "periodo": row["periodo"],
                "why": row["why_flagged"],
                "assumption": row["assumption"],
            })
        payload = {
            "schema": "RIGP-ENTITY-SIGNALS-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "guardrail": GUARDRAIL,
            "uf_clp_reference": uf_clp,
            "coverage": {
                "providers_in_scope": providers_in_scope,
                "providers_with_registry_profile": matched,
                "registry_coverage": result["registry_coverage"],
            },
            "by_type": result["by_type"],
            "providers": by_provider,
        }
        json_path = Path(output_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        result["json"] = str(json_path)
    return result


def merge_into_risk_signals(
    parquet_glob: str,
    entity_signals_path: str | Path = OUTPUT_PARQUET,
    signals_path: str | Path = RISK_SIGNALS_PATH,
) -> dict:
    """Lleva las señales de entidad a la cola común, una por relación alcanzada.

    Sin este paso la capa existiría como producto aparte y no participaría ni de
    la priorización ni de la corroboración de tipologías, que es justamente para
    lo que se portó.

    El abanico es a todas las relaciones organismo-proveedor del período de la
    señal: el hecho registral es del proveedor y alcanza por igual a cada
    organismo que le pagó ese año.
    """
    entity_path, target = Path(entity_signals_path), Path(signals_path)
    if not entity_path.exists() or not target.exists():
        return {"merged": 0, "reason": "capa de entidad o cola de señales ausente"}

    entity = pd.read_parquet(entity_path)
    if entity.empty:
        return {"merged": 0, "reason": "sin señales de entidad"}

    relations = provider_relations(parquet_glob)
    if relations.empty:
        return {"merged": 0, "reason": "sin relaciones organismo-proveedor"}

    relations["periodo"] = pd.to_numeric(relations["periodo"], errors="coerce").astype("Int64")
    fanned = entity.merge(relations, on=["provider_id", "periodo"], how="inner")
    if fanned.empty:
        return {"merged": 0, "reason": "ninguna señal de entidad cae en un período con relaciones"}

    fanned["signal_id"] = [
        _signal_id(str(t), f"{p}|{o}|{y}")
        for t, p, o, y in zip(
            fanned["signal_type"], fanned["provider_id"],
            fanned["organization_id"], fanned["periodo"],
        )
    ]
    fanned["transaction_id"] = None
    fanned["mes"] = pd.Series([pd.NA] * len(fanned), dtype="Int64")
    fanned["recipient_id"] = fanned["provider_id"]
    fanned["investigation_hypothesis"] = HYPOTHESIS

    con = duckdb.connect()
    try:
        con.execute(f"CREATE OR REPLACE TABLE merged AS SELECT * FROM read_parquet('{target.as_posix()}')")
        existing = {d[0] for d in con.execute("SELECT * FROM merged LIMIT 0").description}
        # `INSERT ... BY NAME` no tolera columnas que la tabla no tiene: la capa de
        # entidad carga campos propios (rut, entity_id, assumption) que viven en su
        # propio parquet y no en la cola común.
        payload = fanned[[c for c in fanned.columns if c in existing]]
        con.register("fanned", payload)
        con.execute("INSERT INTO merged BY NAME SELECT * FROM fanned")
        con.execute(f"COPY merged TO '{target.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        total, distinct = con.execute(
            f"SELECT count(*),count(DISTINCT signal_id) FROM read_parquet('{target.as_posix()}')"
        ).fetchone()
        by_type = dict(con.execute(
            f"SELECT signal_type,count(*) FROM read_parquet('{target.as_posix()}') GROUP BY 1"
        ).fetchall())
    finally:
        con.close()

    return {
        "path": str(target),
        "merged": int(len(payload)),
        "relations_reached": int(payload.groupby(["organization_id", "provider_id", "periodo"], dropna=False).ngroups),
        "signals": int(total),
        "distinct_signal_ids": int(distinct),
        "by_type": by_type,
        "dropped_columns": sorted(set(fanned.columns) - existing),
    }


def summarize(result: dict) -> str:
    return (
        f"entidades cubiertas={result['providers_with_registry_profile']:,}/"
        f"{result['providers_in_scope']:,} ({result['registry_coverage']:.1%})"
        f" · señales={result['signals']:,} · {result['by_type']}"
    )
