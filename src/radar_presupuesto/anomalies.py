from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd


def robust_z(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").astype(float)
    med = x.median()
    mad = (x - med).abs().median()
    if not math.isfinite(mad) or mad == 0:
        return pd.Series(np.zeros(len(x)), index=x.index)
    return 0.6745 * (x - med) / mad


def _signal_id(kind: str, key: str) -> str:
    h = hashlib.sha256(f"{kind}|{key}".encode()).hexdigest()[:20].upper()
    return f"SIG-PA-{kind}-{h}"


def _mk(kind, row, observed, expected, deviation, severity, why, checks):
    key = str(row.get("transaction_id") or row.get("recipient_id") or row.get("organization_id"))
    return {
        "signal_id": _signal_id(kind, key),
        "signal_type": kind,
        "transaction_id": row.get("transaction_id"),
        "organization_id": row.get("organization_id"),
        "recipient_id": row.get("recipient_id"),
        "provider_id": row.get("provider_id"),
        "periodo": row.get("periodo"),
        "mes": row.get("mes"),
        "observed_value": None if pd.isna(observed) else float(observed),
        "expected_value": None if pd.isna(expected) else float(expected),
        "deviation": None if pd.isna(deviation) else float(deviation),
        "severity": severity,
        "confidence": "MEDIUM",
        "record_class": "DERIVED_SIGNAL",
        "why_flagged": why,
        "investigation_hypothesis": (
            "Patrón que requiere explicación documental/contextual; "
            "no implica irregularidad por sí solo."
        ),
        "recommended_checks": checks,
        "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def detect_amount_outliers(
    df,
    threshold=4.5,
    min_group=20,
    min_ratio=3.0,
    quantile_floor=0.99,
    provider_only=True,
    exclude_aggregated=True,
):
    """Detect material high-side outliers inside comparable procurement groups.

    The statistical deviation must be accompanied by economic materiality relative to
    the same group: the observation must reach the configured upper quantile and be
    at least `min_ratio` times the group median. By default this signal is restricted
    to source-explicit providers and excludes aggregated records.
    """
    if "monto_devengado" not in df:
        return []
    work = df.copy()
    if provider_only and "is_provider" in work:
        work = work[work["is_provider"] == True].copy()  # noqa: E712
    if exclude_aggregated and "is_aggregated" in work:
        work = work[work["is_aggregated"] != True].copy()  # noqa: E712
    work["_amount"] = pd.to_numeric(work["monto_devengado"], errors="coerce")
    work = work[work["_amount"] >= 0]
    group_cols = [
        c for c in ["organization_id", "subtitulo", "item"] if c in work
    ] or ["organization_id"]
    signals = []
    for _, g in work.dropna(subset=["_amount"]).groupby(group_cols, dropna=False):
        if len(g) < min_group:
            continue
        z = robust_z(np.log1p(g["_amount"].clip(lower=0)))
        med = float(g["_amount"].median())
        floor = float(g["_amount"].quantile(quantile_floor))
        material_floor = max(floor, med * float(min_ratio))
        candidates = g.index[(z >= threshold) & (g["_amount"] >= material_floor)]
        for idx in candidates:
            row = work.loc[idx]
            zv = float(z.loc[idx])
            ratio = float(row["_amount"] / med) if med > 0 else None
            ratio_text = f"; {ratio:.1f}x la mediana" if ratio is not None else ""
            signals.append(
                _mk(
                    "AMOUNT_OUTLIER",
                    row,
                    row["_amount"],
                    med,
                    zv,
                    "HIGH" if zv >= 7 else "MEDIUM",
                    (
                        "Monto proveedor en la cola superior material de su grupo "
                        f"organismo/subtítulo/ítem (z robusto={zv:.2f}{ratio_text}; "
                        f"p{int(quantile_floor * 100)}={floor:,.0f})."
                    ),
                    [
                        "Revisar documento y Orden de Compra",
                        "Comparar con objeto/ítem presupuestario",
                        "Revisar historial del proveedor en el organismo",
                        "Descartar hitos contractuales o pagos extraordinarios legítimos",
                    ],
                )
            )
    return signals


def detect_potential_fragmentation(df, min_count=3, max_cv=0.15):
    required = {
        "organization_id",
        "provider_id",
        "fecha_documento",
        "monto_devengado",
        "is_provider",
    }
    if not required.issubset(df.columns):
        return []
    work = df[df["is_provider"] == True].copy()  # noqa: E712
    if "is_aggregated" in work:
        work = work[work["is_aggregated"] != True].copy()  # noqa: E712
    work = work[work["provider_id"].fillna("") != ""]
    work["fecha_documento"] = pd.to_datetime(work["fecha_documento"], errors="coerce")
    work["_amount"] = pd.to_numeric(work["monto_devengado"], errors="coerce")
    work["_window"] = work["fecha_documento"].dt.to_period("W").astype(str)
    groups = ["organization_id", "provider_id", "_window"] + (
        ["item"] if "item" in work else []
    )
    signals = []
    for _, g in work.dropna(subset=["fecha_documento", "_amount"]).groupby(
        groups, dropna=False
    ):
        if len(g) < min_count:
            continue
        mean = g["_amount"].mean()
        if not mean or mean <= 0:
            continue
        cv = float(g["_amount"].std(ddof=0) / mean)
        if cv <= max_cv:
            row = g.iloc[0]
            sig = _mk(
                "POTENTIAL_FRAGMENTATION",
                row,
                len(g),
                min_count,
                cv,
                "MEDIUM",
                (
                    f"{len(g)} documentos de montos similares para mismo "
                    f"organismo/proveedor/ítem en una ventana semanal (CV={cv:.3f})."
                ),
                [
                    "Verificar si corresponden a un mismo objeto de contratación",
                    "Revisar OC/licitación y fechas",
                    "Descartar pagos parciales o facturación periódica legítima",
                ],
            )
            sig["supporting_transactions"] = g["transaction_id"].astype(str).tolist()[:50]
            signals.append(sig)
    return signals


def detect_year_end_spikes(df, ratio_threshold=2.5):
    required = {"organization_id", "periodo", "mes", "monto_devengado"}
    if not required.issubset(df.columns):
        return []
    work = df.copy()
    work["_amount"] = pd.to_numeric(work["monto_devengado"], errors="coerce").fillna(0)
    monthly = work.groupby(
        ["organization_id", "periodo", "mes"], dropna=False
    )["_amount"].sum().reset_index()
    signals = []
    for (org, year), g in monthly.groupby(["organization_id", "periodo"]):
        base = g[g["mes"].between(1, 10)]["_amount"].mean()
        end = g[g["mes"].between(11, 12)]["_amount"].mean()
        if base and pd.notna(end) and end / base >= ratio_threshold:
            sample = work[
                (work["organization_id"] == org) & (work["periodo"] == year)
            ].iloc[0]
            ratio = float(end / base)
            signals.append(
                _mk(
                    "YEAR_END_SPIKE",
                    sample,
                    end,
                    base,
                    ratio,
                    "MEDIUM",
                    f"Promedio mensual nov-dic es {ratio:.2f}x el promedio ene-oct.",
                    [
                        "Comparar con estacionalidad histórica del organismo",
                        "Revisar concentración por proveedor y subtítulo",
                        "Identificar nuevas OC o modificaciones presupuestarias",
                    ],
                )
            )
    return signals


def detect_exact_duplicates(df):
    work = df.copy()
    if "is_aggregated" in work:
        work = work[work["is_aggregated"] != True].copy()  # noqa: E712
    keys = [
        c
        for c in [
            "periodo",
            "mes",
            "organization_id",
            "recipient_id",
            "numero_documento",
            "fecha_documento",
            "monto_devengado",
            "folio",
        ]
        if c in work
    ]
    if len(keys) < 5:
        return []
    dup = work[work.duplicated(keys, keep=False)]
    out = []
    for _, g in dup.groupby(keys, dropna=False):
        row = g.iloc[0]
        sig = _mk(
            "EXACT_DUPLICATE_CANDIDATE",
            row,
            len(g),
            1,
            len(g) - 1,
            "HIGH",
            f"{len(g)} registros coinciden en las claves documentales principales.",
            [
                "Verificar si es duplicación fuente",
                "Revisar pagos parciales/ajustes",
                "Comparar folio y fecha de pago",
            ],
        )
        sig["supporting_transactions"] = g["transaction_id"].astype(str).tolist()[:50]
        out.append(sig)
    return out


def detect_all(df, config=None):
    cfg = config or {}
    rows = []
    rows += detect_amount_outliers(df, **cfg.get("amount_outlier", {}))
    rows += detect_potential_fragmentation(df, **cfg.get("potential_fragmentation", {}))
    rows += detect_year_end_spikes(df, **cfg.get("year_end_spike", {}))
    rows += detect_exact_duplicates(df)
    return pd.DataFrame(rows)
