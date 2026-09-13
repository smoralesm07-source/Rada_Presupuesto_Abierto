from __future__ import annotations

"""Entity-layer signals derived from the published SII enrichment.

These signals describe the *counterparty*, not the transaction: how old the
company is when it starts receiving public money, whether its declared sales
capacity is consistent with what it is paid, whether its registered economic
activity is unusual for the budget line, and whether it is wound up shortly
after being paid.

Every record stays a `DERIVED_SIGNAL` with an explicit assumption trail. None of
them asserts wrongdoing: a young supplier, a small supplier or a supplier that
closes are all ordinary events. They earn review priority, nothing more.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .ids import normalize_rut

ENRICHMENT_PATH = "docs/data/entity_enrichment_v1.json"
OUTPUT_PARQUET = "data/signals/entity_signals.parquet"
OUTPUT_JSON = "docs/data/entity_signals.json"

GUARDRAIL = (
    "Señal de contraparte derivada de datos registrales publicados. Antigüedad, "
    "tamaño, giro o término de giro no constituyen por sí mismos indicio de "
    "irregularidad; ordenan prioridad de revisión documental."
)

# SII publica el tamaño del contribuyente en tramos de ventas anuales expresados
# en UF. El techo de cada tramo se usa sólo como referencia de capacidad
# declarada; el tramo superior no tiene techo y por eso nunca genera señal.
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

# Las fuentes presupuestarias usan RUT comodín para agregar receptores que no
# tienen uno propio (por ejemplo "extranjeros sin RUT"). Son cubos contables, no
# entidades, y cualquier señal de contraparte sobre ellos es ruido por
# construcción.
def is_placeholder_rut(rut: str) -> bool:
    body = str(rut or "").split("-", 1)[0]
    return bool(body) and len(set(body)) == 1 and len(body) >= 7


def _signal_id(kind: str, key: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"{kind}|{key}".encode()).hexdigest()[:20].upper()
    return f"SIG-PA-{kind}-{digest}"


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
    """Aggregate observed public payments per provider and per provider-year."""
    con = duckdb.connect()
    try:
        df = con.execute(
            f"""
            WITH base AS (
              SELECT provider_id,
                     periodo,
                     try_cast(monto_devengado AS DOUBLE) AS amount,
                     try_cast(fecha_documento AS DATE) AS doc_date,
                     any_value(nombre_beneficiario) OVER (PARTITION BY provider_id) AS provider_name,
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
                   any_value(organization_id) AS organization_id,
                   string_agg(DISTINCT subtitulo, '|') AS subtitulos
            FROM base
            GROUP BY provider_id, periodo
            """
        ).df()
    finally:
        con.close()
    return df


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
    """Learn, per subtítulo, which ACTECO divisions actually carry the spend.

    The reference set is empirical: it is what providers in that budget line
    normally do, not an external taxonomy. A provider outside it is a candidate
    for review, never a conclusion.
    """
    totals: dict[str, float] = {}
    by_division: dict[str, dict[str, float]] = {}
    for row in profile.itertuples():
        rut = _rut_from_provider_id(row.provider_id)
        entity = enrichment.get(rut)
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
        if total <= 0:
            continue
        reference[sub] = {d for d, v in bucket.items() if v / total >= share_floor}
    return reference


def build_entity_signals(
    parquet_glob: str,
    enrichment_path: str | Path = ENRICHMENT_PATH,
    output_parquet: str | Path = OUTPUT_PARQUET,
    config: dict | None = None,
    output_json: str | Path | None = OUTPUT_JSON,
) -> dict:
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

    by_provider = profile.sort_values("periodo").groupby("provider_id")
    for provider, group in by_provider:
        rut = _rut_from_provider_id(provider)
        entity = enrichment.get(rut)
        if not entity:
            continue
        provider_name = str(group["provider_name"].iloc[0] or provider)
        first_doc = pd.to_datetime(group["first_doc_date"], errors="coerce").min()
        last_doc = pd.to_datetime(group["last_doc_date"], errors="coerce").max()
        total_amount = float(group["amount_year"].sum())
        years = sorted(int(y) for y in group["periodo"].dropna().unique())
        organization_id = str(group["organization_id"].iloc[0] or "")

        common = {
            "provider_id": provider,
            "provider_name": provider_name,
            "rut": rut,
            "organization_id": organization_id,
            "entity_id": entity.get("entity_id") or f"ENT-RUT-{rut}",
            "record_class": "DERIVED_SIGNAL",
            "confidence": "MEDIUM",
            "guardrail": GUARDRAIL,
        }

        start_date = entity.get("start_date") or ""
        months_old = _months_between(first_doc, start_date) if start_date else None
        max_months = float(newborn.get("max_months_since_start", 12))
        if (
            months_old is not None
            and months_old <= max_months
            and total_amount >= float(newborn.get("min_amount", 20_000_000))
        ):
            rows.append(
                {
                    **common,
                    "signal_id": _signal_id("NEWBORN_SUPPLIER", provider),
                    "signal_type": "NEWBORN_SUPPLIER",
                    "severity": "HIGH" if months_old <= 6 else "MEDIUM",
                    "periodo": years[0] if years else None,
                    "observed_value": round(float(months_old), 2),
                    "expected_value": max_months,
                    "why_flagged": (
                        f"Primer pago público a {round(months_old)} meses del inicio de "
                        f"actividades declarado ({start_date}), por "
                        f"${total_amount:,.0f} acumulados."
                    ),
                    "assumption": "Inicio de actividades según snapshot SII publicado; no acredita fecha de constitución societaria.",
                    "recommended_checks": json.dumps(
                        [
                            "Revisar la adjudicación o el acto que originó el primer pago",
                            "Verificar constitución societaria y socios al momento de adjudicar",
                            "Comparar con otros proveedores nuevos del mismo organismo",
                        ],
                        ensure_ascii=False,
                    ),
                }
            )

        band = entity.get("sales_band_code")
        band_code = int(band) if isinstance(band, (int, float)) and not pd.isna(band) else None
        min_capacity_amount = float(capacity.get("min_amount", 20_000_000))
        min_ratio = float(capacity.get("min_ratio", 3.0))
        for row in group.itertuples():
            amount_year = float(row.amount_year or 0)
            if band_code is None or amount_year < min_capacity_amount:
                continue
            upper_uf = SALES_BAND_UPPER_UF.get(band_code, None)
            if upper_uf is None:
                continue  # tramo superior sin techo declarado
            ceiling_clp = upper_uf * uf_clp
            if band_code == 1:
                ratio = None
                severity = "HIGH"
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
                    f"Recibe ${amount_year:,.0f} en {int(row.periodo)}, "
                    f"{ratio:.1f}x el techo de ventas del tramo SII {band_code} "
                    f"(~${ceiling_clp:,.0f})."
                )
            rows.append(
                {
                    **common,
                    "signal_id": _signal_id("CAPACITY_MISMATCH", f"{provider}|{row.periodo}"),
                    "signal_type": "CAPACITY_MISMATCH",
                    "severity": severity,
                    "periodo": int(row.periodo) if not pd.isna(row.periodo) else None,
                    "observed_value": amount_year,
                    "expected_value": ceiling_clp or None,
                    "deviation": ratio,
                    "why_flagged": why,
                    "assumption": (
                        f"Techo de tramo convertido a CLP con UF de referencia ${uf_clp:,.0f}. "
                        f"El tramo corresponde al año comercial {entity.get('commercial_year')} publicado, "
                        "que puede no coincidir con el año del pago."
                    ),
                    "recommended_checks": json.dumps(
                        [
                            "Contrastar el tramo con el año comercial efectivamente pagado",
                            "Revisar si el proveedor subcontrata o actúa como intermediario",
                            "Verificar capacidad operativa: trabajadores, activos, domicilio",
                        ],
                        ensure_ascii=False,
                    ),
                }
            )

        divisions = _activity_divisions(entity)
        min_activity_amount = float(activity.get("min_amount", 50_000_000))
        if divisions and total_amount >= min_activity_amount:
            subs = {s.strip() for s in "|".join(group["subtitulos"].fillna("")).split("|") if s.strip()}
            mismatched = [s for s in subs if reference.get(s) and not (divisions & reference[s])]
            if mismatched and subs:
                rows.append(
                    {
                        **common,
                        "signal_id": _signal_id("ACTIVITY_MISMATCH", provider),
                        "signal_type": "ACTIVITY_MISMATCH",
                        "severity": "MEDIUM",
                        "periodo": years[-1] if years else None,
                        "observed_value": float(len(mismatched)),
                        "why_flagged": (
                            "El giro registrado (divisiones ACTECO "
                            + ", ".join(sorted(divisions))
                            + ") no aparece entre las actividades que concentran el gasto "
                            + "en los subtítulos "
                            + ", ".join(sorted(mismatched))
                            + "."
                        ),
                        "assumption": "El perfil de actividades esperadas se aprende del propio gasto observado, no de una taxonomía externa.",
                        "recommended_checks": json.dumps(
                            [
                                "Revisar el objeto efectivamente contratado",
                                "Verificar si el giro fue ampliado antes o después de contratar",
                                "Descartar intermediación o reventa legítima",
                            ],
                            ensure_ascii=False,
                        ),
                    }
                )

        termination_date = entity.get("termination_date") or ""
        if termination_date:
            months_after = _months_between(termination_date, last_doc)
            max_after = float(termination.get("max_months_after_last_payment", 12))
            if (
                months_after is not None
                and 0 <= months_after <= max_after
                and total_amount >= float(termination.get("min_amount", 20_000_000))
            ):
                rows.append(
                    {
                        **common,
                        "signal_id": _signal_id("TERMINATION_AFTER_PAYMENT", provider),
                        "signal_type": "TERMINATION_AFTER_PAYMENT",
                        "severity": "HIGH",
                        "periodo": years[-1] if years else None,
                        "observed_value": round(float(months_after), 2),
                        "expected_value": max_after,
                        "why_flagged": (
                            f"Término de giro el {termination_date}, "
                            f"{round(months_after)} meses después del último pago público "
                            f"registrado, tras ${total_amount:,.0f} acumulados."
                        ),
                        "assumption": "Término de giro según snapshot SII publicado; la fecha registral puede diferir del cese operativo.",
                        "recommended_checks": json.dumps(
                            [
                                "Revisar si quedaron obligaciones contractuales pendientes",
                                "Verificar destino de los activos y continuidad de los socios en otras sociedades",
                                "Contrastar con recepciones conformes y garantías",
                            ],
                            ensure_ascii=False,
                        ),
                    }
                )

        min_gap = int(dormant.get("min_gap_years", 2))
        min_dormant_amount = float(dormant.get("min_amount", 50_000_000))
        for index in range(1, len(years)):
            gap = years[index] - years[index - 1]
            if gap <= min_gap:
                continue
            amount_after = float(
                group.loc[group["periodo"] == years[index], "amount_year"].sum()
            )
            if amount_after < min_dormant_amount:
                continue
            rows.append(
                {
                    **common,
                    "signal_id": _signal_id("DORMANT_REACTIVATION", f"{provider}|{years[index]}"),
                    "signal_type": "DORMANT_REACTIVATION",
                    "severity": "MEDIUM",
                    "periodo": years[index],
                    "observed_value": float(gap),
                    "expected_value": float(min_gap),
                    "why_flagged": (
                        f"Sin pagos públicos observados entre {years[index - 1]} y "
                        f"{years[index]}, y reaparece con ${amount_after:,.0f}."
                    ),
                    "assumption": "La ausencia se mide sólo sobre los años efectivamente procesados por el radar, no sobre toda la historia del proveedor.",
                    "recommended_checks": json.dumps(
                        [
                            "Confirmar la ausencia en la serie completa disponible",
                            "Revisar cambios de propiedad o administración en el intervalo",
                            "Revisar el acto que originó el reingreso",
                        ],
                        ensure_ascii=False,
                    ),
                }
            )

    return _write(rows, output_parquet, enrichment, profile, uf_clp, output_json)


def _write(
    rows: list[dict],
    output_parquet: str | Path,
    enrichment: dict,
    profile: pd.DataFrame,
    uf_clp: float,
    output_json: str | Path | None = None,
) -> dict:
    columns = [
        "signal_id", "signal_type", "provider_id", "provider_name", "rut", "entity_id",
        "organization_id", "periodo", "severity", "confidence", "record_class",
        "observed_value", "expected_value", "deviation", "why_flagged", "assumption",
        "recommended_checks", "guardrail",
    ]
    df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)
    for col in ("observed_value", "expected_value", "deviation"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["detected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = Path(output_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    providers_in_scope = int(profile["provider_id"].nunique()) if not profile.empty else 0
    matched = 0
    if not profile.empty:
        matched = sum(
            1
            for pid in profile["provider_id"].unique()
            if _rut_from_provider_id(pid) in enrichment
        )
    result = {
        "path": str(out),
        "signals": int(len(df)),
        "by_type": df["signal_type"].value_counts().to_dict() if len(df) else {},
        "providers_in_scope": providers_in_scope,
        "providers_with_registry_profile": matched,
        "registry_coverage": round(matched / providers_in_scope, 6) if providers_in_scope else 0.0,
        "uf_clp_reference": uf_clp,
    }

    if output_json:
        # Publicación compacta: lo que la capa de tipologías necesita para operar
        # en el navegador sin volver a leer los hechos.
        by_provider: dict[str, dict] = {}
        for row in rows:
            entry = by_provider.setdefault(
                str(row["provider_id"]),
                {
                    "provider_id": row["provider_id"],
                    "provider_name": row["provider_name"],
                    "rut": row["rut"],
                    "signals": [],
                },
            )
            entry["signals"].append(
                {
                    "signal_type": row["signal_type"],
                    "severity": row["severity"],
                    "periodo": row["periodo"],
                    "why": row["why_flagged"],
                    "assumption": row["assumption"],
                }
            )
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


def entity_risk_by_provider(entity_signals_path: str | Path = OUTPUT_PARQUET) -> pd.DataFrame:
    """Collapse entity signals to one review-weight row per provider."""
    path = Path(entity_signals_path)
    empty = pd.DataFrame(
        columns=["provider_id", "entity_signal_count", "entity_signal_types", "entity_risk_weight"]
    )
    if not path.exists():
        return empty
    df = pd.read_parquet(path)
    if df.empty:
        return empty
    weights = {
        "NEWBORN_SUPPLIER": 4,
        "CAPACITY_MISMATCH": 4,
        "TERMINATION_AFTER_PAYMENT": 3,
        "ACTIVITY_MISMATCH": 2,
        "DORMANT_REACTIVATION": 2,
    }
    df["_w"] = df["signal_type"].map(weights).fillna(1) * df["severity"].map(
        {"HIGH": 1.0, "MEDIUM": 0.7, "LOW": 0.4}
    ).fillna(0.7)
    grouped = df.groupby("provider_id").agg(
        entity_signal_count=("signal_id", "count"),
        entity_signal_types=("signal_type", lambda s: "|".join(sorted(set(s)))),
        entity_risk_weight=("_w", "sum"),
    ).reset_index()
    grouped["entity_risk_weight"] = grouped["entity_risk_weight"].map(
        lambda v: round(min(10.0, float(v)), 4)
    )
    return grouped


def summarize(result: dict) -> str:
    return (
        f"entidades cubiertas={result['providers_with_registry_profile']:,}/"
        f"{result['providers_in_scope']:,} "
        f"({result['registry_coverage']:.1%}) · señales={result['signals']:,} "
        f"· {result['by_type']}"
    )
