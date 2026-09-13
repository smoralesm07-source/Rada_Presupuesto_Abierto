from __future__ import annotations

"""Capa 2: the procurement process, joined to payments through `orden_compra`.

Presupuesto Abierto answers *who was paid how much*. It cannot answer *how the
buyer decided to contract them*, and in public procurement that is where the
LA/FT signal lives: a single admissible bidder, a direct award repeated with the
same supplier, an object split to stay under the threshold that would have forced
an open tender.

`normalize.py` has always carried `ORDEN_DE_COMPRA` into the canonical schema and
never used it as anything but a search field. It is the join key, and this module
is what it joins to.

The detectors here are complete and tested. What is not wired is the feed: this
environment has no egress to Mercado Público, so `fetch` is a thin, isolated
client that a scheduled workflow calls, and everything below it operates on a
local snapshot. Connecting the source is configuration, not new analysis code.

Until a snapshot exists, `typologies.py` reports `PROCESO_DE_COMPRA` as a pending
layer and caps every typology that depends on it, rather than scoring those
typologies low and looking like a negative result.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

SCHEMA = "RIGP-PROCUREMENT-v1"
DEFAULT_SNAPSHOT = "data/processed/procurement.parquet"

# Canonical shape a procurement snapshot must satisfy, whatever produced it.
CANONICAL_COLUMNS = [
    "purchase_order_id",      # la llave de unión con orden_compra
    "tender_id",
    "buyer_id",
    "buyer_name",
    "supplier_rut",
    "supplier_name",
    "modality",               # LICITACION_PUBLICA | LICITACION_PRIVADA | TRATO_DIRECTO | CONVENIO_MARCO | COMPRA_AGIL
    "modality_code",          # L1 | LE | LP | LQ | LR | ...
    "bidders_count",
    "admissible_bidders_count",
    "estimated_amount_clp",
    "awarded_amount_clp",
    "currency",
    "published_at",
    "awarded_at",
    "purchase_order_at",
    "item_category",
    "object_description",
    "amendments_count",
    "emergency_ground",
    "source_url",
    "retrieved_at",
]

DIRECT_MODALITIES = {"TRATO_DIRECTO", "COMPRA_AGIL"}

GUARDRAIL = (
    "Las señales de proceso describen cómo se decidió contratar. Una modalidad excepcional, "
    "un único oferente o una adjudicación cercana a un umbral pueden ser enteramente regulares. "
    "Ninguna de estas señales acredita irregularidad, colusión ni lavado de activos."
)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "purchase_order_id": ("Codigo", "codigo", "purchase_order_id", "orden_compra", "CodigoOC"),
    "tender_id": ("CodigoLicitacion", "tender_id", "codigo_licitacion"),
    "buyer_id": ("CodigoOrganismo", "buyer_id", "codigo_organismo"),
    "buyer_name": ("NombreOrganismo", "buyer_name", "nombre_organismo"),
    "supplier_rut": ("RutProveedor", "supplier_rut", "rut_proveedor"),
    "supplier_name": ("NombreProveedor", "supplier_name", "nombre_proveedor"),
    "modality_code": ("TipoLicitacion", "modality_code", "tipo_licitacion"),
    "bidders_count": ("CantidadOferentes", "bidders_count", "cantidad_oferentes"),
    "admissible_bidders_count": ("OferentesAdmisibles", "admissible_bidders_count"),
    "estimated_amount_clp": ("MontoEstimado", "estimated_amount_clp", "monto_estimado"),
    "awarded_amount_clp": ("MontoAdjudicado", "Total", "awarded_amount_clp", "monto_adjudicado"),
    "currency": ("Moneda", "currency", "moneda"),
    "published_at": ("FechaPublicacion", "published_at", "fecha_publicacion"),
    "awarded_at": ("FechaAdjudicacion", "awarded_at", "fecha_adjudicacion"),
    "purchase_order_at": ("FechaEnvio", "FechaCreacion", "purchase_order_at", "fecha_oc"),
    "item_category": ("Categoria", "item_category", "categoria"),
    "object_description": ("Nombre", "Descripcion", "object_description", "descripcion"),
    "amendments_count": ("CantidadModificaciones", "amendments_count"),
    "emergency_ground": ("CausalEmergencia", "emergency_ground", "causal"),
    "source_url": ("source_url", "url"),
}

MODALITY_BY_CODE = {
    "L1": "LICITACION_PUBLICA",
    "LE": "LICITACION_PUBLICA",
    "LP": "LICITACION_PUBLICA",
    "LQ": "LICITACION_PUBLICA",
    "LR": "LICITACION_PUBLICA",
    "LS": "LICITACION_PUBLICA",
    "B2": "LICITACION_PRIVADA",
    "H2": "LICITACION_PRIVADA",
    "I2": "LICITACION_PRIVADA",
    "CM": "CONVENIO_MARCO",
    "TD": "TRATO_DIRECTO",
    "CA": "COMPRA_AGIL",
}


def _pick(record: dict, field: str):
    for alias in FIELD_ALIASES.get(field, ()):  # primero el nombre nativo de la fuente
        if alias in record and record[alias] not in (None, ""):
            return record[alias]
    return None


def normalize_purchase_orders(records: list[dict]) -> pd.DataFrame:
    """Bring any supported source shape into the canonical procurement schema."""
    rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for record in records:
        row = {column: _pick(record, column) for column in CANONICAL_COLUMNS}
        code = str(row.get("modality_code") or "").strip().upper()
        row["modality_code"] = code
        row["modality"] = record.get("modality") or MODALITY_BY_CODE.get(code, "NO_DETERMINADA")
        row["retrieved_at"] = record.get("retrieved_at") or now
        rows.append(row)
    frame = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)
    for column in ("bidders_count", "admissible_bidders_count", "amendments_count"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in ("estimated_amount_clp", "awarded_amount_clp"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Float64")
    for column in ("published_at", "awarded_at", "purchase_order_at"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    frame["purchase_order_id"] = frame["purchase_order_id"].astype(str).str.strip()
    return frame[frame["purchase_order_id"].ne("") & frame["purchase_order_id"].ne("None")]


def snapshot_available(path: str | Path = DEFAULT_SNAPSHOT) -> bool:
    p = Path(path)
    return p.exists() and p.stat().st_size > 0


# ---------------------------------------------------------------------------
# Unión con los pagos
# ---------------------------------------------------------------------------

def join_payments(parquet_glob: str, procurement_path: str | Path = DEFAULT_SNAPSHOT) -> pd.DataFrame:
    """Attach each payment to the procurement process that authorised it."""
    if not snapshot_available(procurement_path):
        return pd.DataFrame()
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            WITH pagos AS (
              SELECT organization_id,
                     coalesce(provider_id,'') AS provider_id,
                     periodo,
                     upper(trim(orden_compra)) AS purchase_order_id,
                     sum(try_cast(monto_devengado AS DOUBLE)) AS paid_amount,
                     count(*) AS payment_rows,
                     min(try_cast(fecha_documento AS DATE)) AS first_payment_doc,
                     any_value(nombre_beneficiario) AS provider_name
              FROM read_parquet('{parquet_glob}', union_by_name=true)
              WHERE coalesce(is_aggregated, FALSE) = FALSE
                AND coalesce(trim(orden_compra),'') <> ''
                AND try_cast(monto_devengado AS DOUBLE) > 0
              GROUP BY 1,2,3,4
            )
            SELECT p.*, o.* EXCLUDE(purchase_order_id)
            FROM pagos p
            JOIN read_parquet('{Path(procurement_path).as_posix()}') o
              ON upper(trim(o.purchase_order_id)) = p.purchase_order_id
            """
        ).df()
    finally:
        con.close()


def coverage(parquet_glob: str | None, procurement_path: str | Path = DEFAULT_SNAPSHOT) -> dict:
    """How much of the spend can actually be traced to a procurement process."""
    if not parquet_glob:
        # Publicar el estado del adaptador no exige tener los hechos a mano.
        return {
            "rows": None,
            "rows_with_purchase_order": None,
            "amount_total": None,
            "amount_with_purchase_order": None,
            "purchase_order_amount_share": None,
            "amount_matched_to_procurement": None,
            "procurement_match_share": None,
            "snapshot_available": snapshot_available(procurement_path),
            "note": "Sin hechos locales en esta corrida; la cobertura se calcula en el pipeline.",
        }
    con = duckdb.connect()
    try:
        totals = con.execute(
            f"""
            SELECT sum(try_cast(monto_devengado AS DOUBLE)) AS total_amount,
                   sum(CASE WHEN coalesce(trim(orden_compra),'') <> ''
                            THEN try_cast(monto_devengado AS DOUBLE) ELSE 0 END) AS with_oc_amount,
                   count(*) AS rows,
                   count(*) FILTER (WHERE coalesce(trim(orden_compra),'') <> '') AS rows_with_oc
            FROM read_parquet('{parquet_glob}', union_by_name=true)
            WHERE coalesce(is_aggregated, FALSE) = FALSE
            """
        ).df().iloc[0]
    finally:
        con.close()
    total = float(totals["total_amount"] or 0)
    with_oc = float(totals["with_oc_amount"] or 0)
    joined = join_payments(parquet_glob, procurement_path)
    matched = float(joined["paid_amount"].sum()) if not joined.empty else 0.0
    return {
        "rows": int(totals["rows"] or 0),
        "rows_with_purchase_order": int(totals["rows_with_oc"] or 0),
        "amount_total": total,
        "amount_with_purchase_order": with_oc,
        "purchase_order_amount_share": round(with_oc / total, 6) if total else 0.0,
        "amount_matched_to_procurement": matched,
        "procurement_match_share": round(matched / with_oc, 6) if with_oc else 0.0,
        "snapshot_available": snapshot_available(procurement_path),
    }


# ---------------------------------------------------------------------------
# Detectores de capa 2
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProcurementThresholds:
    """Modality thresholds, expressed in UTM and converted per year.

    These are configuration on purpose. The boundaries set by Ley 19.886 and its
    regulation have moved — Ley 21.634 changed them — so the operator pins the
    values in `config/procurement_thresholds.yaml` against the text in force for
    the period analysed, and every signal states which boundary it used.
    """

    utm_clp_by_year: dict[int, float]
    boundaries_utm: tuple[float, ...] = (30.0, 100.0, 1000.0)
    bunching_window: float = 0.10
    bunching_min_ratio: float = 2.0
    bunching_min_count: int = 5

    def boundary_clp(self, year: int) -> list[tuple[float, float]]:
        utm = float(self.utm_clp_by_year.get(int(year), 0) or 0)
        if utm <= 0:
            return []
        return [(u, u * utm) for u in self.boundaries_utm]


def _text(value: object) -> str:
    """Safe string for values that may arrive as pd.NA from a nullable column."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value)


def _signal(kind: str, key: str, **fields) -> dict:
    import hashlib

    digest = hashlib.sha256(f"{kind}|{key}".encode()).hexdigest()[:20].upper()
    base = {
        "signal_id": f"SIG-MP-{kind}-{digest}",
        "signal_type": kind,
        "record_class": "DERIVED_SIGNAL",
        "confidence": "MEDIUM",
        "layer": "PROCESO_DE_COMPRA",
        "guardrail": GUARDRAIL,
    }
    base.update(fields)
    return base


def detect_single_bidder(joined: pd.DataFrame, min_amount: float = 20_000_000) -> list[dict]:
    rows = []
    for row in joined.itertuples():
        modality = str(getattr(row, "modality", "") or "")
        admissible = getattr(row, "admissible_bidders_count", None)
        bidders = getattr(row, "bidders_count", None)
        count = admissible if admissible is not None and not pd.isna(admissible) else bidders
        if count is None or pd.isna(count) or int(count) > 1:
            continue
        if modality not in {"LICITACION_PUBLICA", "LICITACION_PRIVADA"}:
            continue
        if float(getattr(row, "awarded_amount_clp", 0) or 0) < min_amount:
            continue
        rows.append(
            _signal(
                "SINGLE_BIDDER",
                str(row.purchase_order_id),
                purchase_order_id=str(row.purchase_order_id),
                organization_id=str(row.organization_id),
                provider_id=str(row.provider_id),
                periodo=int(row.periodo),
                severity="HIGH" if int(count) == 0 else "MEDIUM",
                observed_value=float(count),
                why_flagged=(
                    f"Licitación {_text(row.tender_id) or _text(row.purchase_order_id)} adjudicada con "
                    f"{int(count)} oferente admisible."
                ),
            )
        )
    return rows


def detect_direct_award_dependence(
    joined: pd.DataFrame, min_share: float = 0.5, min_amount: float = 50_000_000, min_orders: int = 5
) -> list[dict]:
    if joined.empty:
        return []
    work = joined.copy()
    work["_direct"] = work["modality"].isin(DIRECT_MODALITIES)
    work["_amount"] = pd.to_numeric(work["awarded_amount_clp"], errors="coerce").fillna(
        pd.to_numeric(work["paid_amount"], errors="coerce")
    )
    grouped = work.groupby(["organization_id", "periodo"]).agg(
        orders=("purchase_order_id", "nunique"),
        total=("_amount", "sum"),
        direct=("_amount", lambda s: float(s[work.loc[s.index, "_direct"]].sum())),
    ).reset_index()
    rows = []
    for row in grouped.itertuples():
        total = float(row.total or 0)
        if total < min_amount or int(row.orders) < min_orders:
            continue
        share = float(row.direct or 0) / total if total else 0.0
        if share < min_share:
            continue
        rows.append(
            _signal(
                "DIRECT_AWARD_DEPENDENCE",
                f"{row.organization_id}|{row.periodo}",
                organization_id=str(row.organization_id),
                provider_id="",
                periodo=int(row.periodo),
                severity="HIGH" if share >= 0.75 else "MEDIUM",
                observed_value=round(share, 4),
                expected_value=min_share,
                why_flagged=(
                    f"{share:.0%} del monto adjudicado del organismo en {int(row.periodo)} "
                    "se resolvió por modalidades sin competencia abierta."
                ),
            )
        )
    return rows


def detect_direct_award_recurrence(
    joined: pd.DataFrame, min_orders: int = 3, min_amount: float = 20_000_000
) -> list[dict]:
    if joined.empty:
        return []
    work = joined[joined["modality"].isin(DIRECT_MODALITIES)].copy()
    if work.empty:
        return []
    work["_amount"] = pd.to_numeric(work["awarded_amount_clp"], errors="coerce").fillna(
        pd.to_numeric(work["paid_amount"], errors="coerce")
    )
    grouped = work.groupby(["organization_id", "provider_id", "periodo"]).agg(
        orders=("purchase_order_id", "nunique"), amount=("_amount", "sum")
    ).reset_index()
    rows = []
    for row in grouped.itertuples():
        if int(row.orders) < min_orders or float(row.amount or 0) < min_amount:
            continue
        rows.append(
            _signal(
                "DIRECT_AWARD_RECURRENCE",
                f"{row.organization_id}|{row.provider_id}|{row.periodo}",
                organization_id=str(row.organization_id),
                provider_id=str(row.provider_id),
                periodo=int(row.periodo),
                severity="MEDIUM",
                observed_value=float(row.orders),
                why_flagged=(
                    f"{int(row.orders)} contrataciones sin competencia abierta con el mismo "
                    f"proveedor en {int(row.periodo)}, por ${float(row.amount):,.0f}."
                ),
            )
        )
    return rows


def detect_award_to_payment_inflation(
    joined: pd.DataFrame, min_ratio: float = 1.25, min_amount: float = 20_000_000
) -> list[dict]:
    rows = []
    for row in joined.itertuples():
        awarded = float(getattr(row, "awarded_amount_clp", 0) or 0)
        paid = float(getattr(row, "paid_amount", 0) or 0)
        if awarded <= 0 or paid < min_amount:
            continue
        ratio = paid / awarded
        if ratio < min_ratio:
            continue
        rows.append(
            _signal(
                "AWARD_TO_PAYMENT_INFLATION",
                str(row.purchase_order_id),
                purchase_order_id=str(row.purchase_order_id),
                organization_id=str(row.organization_id),
                provider_id=str(row.provider_id),
                periodo=int(row.periodo),
                severity="HIGH" if ratio >= min_ratio * 1.6 else "MEDIUM",
                observed_value=paid,
                expected_value=awarded,
                deviation=round(ratio, 4),
                why_flagged=(
                    f"Pagado ${paid:,.0f} sobre ${awarded:,.0f} adjudicados "
                    f"({ratio:.2f}x) en la orden {row.purchase_order_id}."
                ),
            )
        )
    return rows


def detect_threshold_hugging(
    joined: pd.DataFrame, thresholds: ProcurementThresholds
) -> list[dict]:
    """Bunching just below a modality boundary.

    This is the procurement equivalent of structuring. It is measured as a
    density discontinuity — how many awards fall in the window just below the
    boundary versus just above — so a mis-configured threshold simply finds
    nothing instead of inventing a finding.
    """
    if joined.empty:
        return []
    work = joined.copy()
    work["_amount"] = pd.to_numeric(work["awarded_amount_clp"], errors="coerce")
    work = work[work["_amount"].notna() & (work["_amount"] > 0)]
    rows = []
    for (org, year), group in work.groupby(["organization_id", "periodo"]):
        for utm_value, boundary in thresholds.boundary_clp(int(year)):
            low = group[
                (group["_amount"] >= boundary * (1 - thresholds.bunching_window))
                & (group["_amount"] < boundary)
            ]
            high = group[
                (group["_amount"] >= boundary)
                & (group["_amount"] < boundary * (1 + thresholds.bunching_window))
            ]
            if len(low) < thresholds.bunching_min_count:
                continue
            ratio = len(low) / max(1, len(high))
            if ratio < thresholds.bunching_min_ratio:
                continue
            rows.append(
                _signal(
                    "THRESHOLD_HUGGING",
                    f"{org}|{year}|{utm_value}",
                    organization_id=str(org),
                    provider_id="",
                    periodo=int(year),
                    severity="HIGH" if ratio >= thresholds.bunching_min_ratio * 2 else "MEDIUM",
                    observed_value=float(len(low)),
                    expected_value=float(len(high)),
                    deviation=round(float(ratio), 4),
                    why_flagged=(
                        f"{len(low)} adjudicaciones se agrupan justo bajo el umbral de "
                        f"{utm_value:.0f} UTM (~${boundary:,.0f}) frente a {len(high)} justo por "
                        f"encima, en {int(year)}."
                    ),
                )
            )
    return rows


def detect_split_procurement(
    joined: pd.DataFrame,
    thresholds: ProcurementThresholds,
    window_days: int = 30,
    min_orders: int = 3,
) -> list[dict]:
    """Several orders for the same object whose sum crosses a boundary each alone stays under."""
    if joined.empty:
        return []
    work = joined.copy()
    work["_amount"] = pd.to_numeric(work["awarded_amount_clp"], errors="coerce").fillna(
        pd.to_numeric(work["paid_amount"], errors="coerce")
    )
    work["_date"] = pd.to_datetime(work["purchase_order_at"], errors="coerce").fillna(
        pd.to_datetime(work["awarded_at"], errors="coerce")
    )
    work = work[work["_amount"].notna() & work["_date"].notna()]
    rows = []
    for (org, provider, year), group in work.groupby(
        ["organization_id", "provider_id", "periodo"]
    ):
        boundaries = thresholds.boundary_clp(int(year))
        if not boundaries or len(group) < min_orders:
            continue
        group = group.sort_values("_date")
        span = (group["_date"].max() - group["_date"].min()).days
        if span > window_days:
            continue
        total = float(group["_amount"].sum())
        largest = float(group["_amount"].max())
        for utm_value, boundary in boundaries:
            if largest >= boundary or total < boundary:
                continue
            rows.append(
                _signal(
                    "SPLIT_PROCUREMENT",
                    f"{org}|{provider}|{year}|{utm_value}",
                    organization_id=str(org),
                    provider_id=str(provider),
                    periodo=int(year),
                    severity="HIGH",
                    observed_value=total,
                    expected_value=boundary,
                    deviation=round(total / boundary, 4),
                    why_flagged=(
                        f"{len(group)} órdenes al mismo proveedor en {span} días suman "
                        f"${total:,.0f} y cruzan el umbral de {utm_value:.0f} UTM "
                        f"(~${boundary:,.0f}), pero ninguna lo alcanza por separado."
                    ),
                )
            )
            break
    return rows


def detect_bid_rotation(
    joined: pd.DataFrame, min_rounds: int = 4, max_winners: int = 3
) -> list[dict]:
    """A stable group of suppliers taking turns inside one buyer and category."""
    if joined.empty:
        return []
    work = joined[joined["modality"] == "LICITACION_PUBLICA"].copy()
    if work.empty:
        return []
    rows = []
    work["_category"] = work["item_category"].astype("string").fillna("NA")
    for (org, category), group in work.groupby(["organization_id", "_category"]):
        tenders = (
            group["tender_id"].astype("string").fillna(group["purchase_order_id"].astype("string")).nunique()
        )
        winners = group["provider_id"].nunique()
        if tenders < min_rounds or winners < 2 or winners > max_winners:
            continue
        rows.append(
            _signal(
                "BID_ROTATION",
                f"{org}|{category}",
                organization_id=str(org),
                provider_id="",
                periodo=int(group["periodo"].max()),
                severity="MEDIUM",
                observed_value=float(winners),
                expected_value=float(tenders),
                why_flagged=(
                    f"{tenders} licitaciones de la categoría {category} en el mismo organismo "
                    f"se reparten entre sólo {winners} adjudicatarios."
                ),
            )
        )
    return rows


def detect_speed_anomaly(joined: pd.DataFrame, max_days: int = 1) -> list[dict]:
    rows = []
    for row in joined.itertuples():
        awarded_at = pd.to_datetime(getattr(row, "awarded_at", None), errors="coerce")
        oc_at = pd.to_datetime(getattr(row, "purchase_order_at", None), errors="coerce")
        published_at = pd.to_datetime(getattr(row, "published_at", None), errors="coerce")
        if pd.isna(awarded_at) or pd.isna(published_at):
            continue
        days = (awarded_at - published_at).days
        if days > max_days or days < 0:
            continue
        rows.append(
            _signal(
                "SPEED_ANOMALY",
                str(row.purchase_order_id),
                purchase_order_id=str(row.purchase_order_id),
                organization_id=str(row.organization_id),
                provider_id=str(row.provider_id),
                periodo=int(row.periodo),
                severity="MEDIUM",
                observed_value=float(days),
                expected_value=float(max_days),
                why_flagged=(
                    f"Entre publicación y adjudicación transcurren {days} día(s), "
                    "plazo inusualmente breve para presentar y evaluar ofertas."
                ),
            )
        )
    return rows


SIGNAL_COLUMNS = [
    "signal_id", "signal_type", "purchase_order_id", "organization_id", "provider_id",
    "periodo", "severity", "confidence", "record_class", "layer", "observed_value",
    "expected_value", "deviation", "why_flagged", "guardrail",
]


def build_procurement_signals(
    parquet_glob: str,
    procurement_path: str | Path = DEFAULT_SNAPSHOT,
    thresholds: ProcurementThresholds | None = None,
    output_parquet: str | Path = "data/signals/procurement_signals.parquet",
    config: dict | None = None,
) -> dict:
    cfg = config or {}
    thresholds = thresholds or ProcurementThresholds(
        utm_clp_by_year=cfg.get("utm_clp_by_year", {}),
        boundaries_utm=tuple(cfg.get("boundaries_utm", (30.0, 100.0, 1000.0))),
    )
    joined = join_payments(parquet_glob, procurement_path)
    rows: list[dict] = []
    if not joined.empty:
        rows += detect_single_bidder(joined)
        rows += detect_direct_award_dependence(joined)
        rows += detect_direct_award_recurrence(joined)
        rows += detect_award_to_payment_inflation(joined)
        rows += detect_threshold_hugging(joined, thresholds)
        rows += detect_split_procurement(joined, thresholds)
        rows += detect_bid_rotation(joined)
        rows += detect_speed_anomaly(joined)

    frame = pd.DataFrame(rows, columns=SIGNAL_COLUMNS)
    out = Path(output_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)
    return {
        "schema": SCHEMA,
        "path": str(out),
        "snapshot_available": snapshot_available(procurement_path),
        "orders_joined": int(joined["purchase_order_id"].nunique()) if not joined.empty else 0,
        "signals": int(len(frame)),
        "by_type": frame["signal_type"].value_counts().to_dict() if len(frame) else {},
        "guardrail": GUARDRAIL,
    }


def write_status(
    parquet_glob: str | None = None,
    procurement_path: str | Path = DEFAULT_SNAPSHOT,
    output_json: str | Path = "docs/data/procurement_status.json",
) -> dict:
    """Publish the integration state honestly, whether or not a snapshot exists."""
    available = snapshot_available(procurement_path)
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "MERCADO_PUBLICO",
        "integration_state": "SNAPSHOT_PRESENT" if available else "ADAPTER_READY_SOURCE_PENDING",
        "join_key": "orden_compra",
        "canonical_columns": CANONICAL_COLUMNS,
        "detectors": [
            "SINGLE_BIDDER", "DIRECT_AWARD_DEPENDENCE", "DIRECT_AWARD_RECURRENCE",
            "AWARD_TO_PAYMENT_INFLATION", "THRESHOLD_HUGGING", "SPLIT_PROCUREMENT",
            "BID_ROTATION", "SPEED_ANOMALY",
        ],
        "guardrail": GUARDRAIL,
        "threshold_note": (
            "Los umbrales por modalidad se configuran en UTM y deben fijarse contra el texto "
            "vigente de la Ley 19.886 y su reglamento para el periodo analizado."
        ),
        "coverage": coverage(parquet_glob, procurement_path),
    }
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return payload
