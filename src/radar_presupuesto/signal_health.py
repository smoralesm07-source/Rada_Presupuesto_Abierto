from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

EXPECTED_SIGNALS = [
    "AMOUNT_OUTLIER",
    "POTENTIAL_FRAGMENTATION",
    "EXACT_DUPLICATE_CANDIDATE",
    "YEAR_END_SPIKE",
    "PROVIDER_CONCENTRATION",
    "PAYMENT_DELAY_OUTLIER",
    "NEW_TO_SERIES_HIGH_SPEND",
]


def _status(count: int, share: float, min_volume: int) -> str:
    if count == 0:
        return "EXPERIMENTAL_ZERO"
    if count < min_volume:
        return "LOW_VOLUME"
    if share >= 0.85:
        return "DOMINANT_REVIEW"
    return "ACTIVE"


def build_signal_health(
    signals_path: str = "data/signals/risk_signals.parquet",
    output_json: str = "docs/data/signal_health.json",
    min_volume: int = 5,
) -> dict:
    """Audit whether configured signal families are actually producing useful coverage.

    The report never changes thresholds automatically. It marks zero-volume signals as
    experimental, low-volume signals for review, and dominant signals when they crowd
    out the rest of the signal universe. Human calibration remains mandatory.
    """
    source = Path(signals_path)
    if not source.exists():
        raise FileNotFoundError(signals_path)

    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT
          signal_type,
          count(*) AS signal_count,
          count(DISTINCT organization_id) AS organization_count,
          count(DISTINCT nullif(provider_id,'')) AS provider_count,
          count(DISTINCT periodo) AS observed_years,
          min(periodo) AS first_year,
          max(periodo) AS last_year,
          sum(CASE WHEN severity='HIGH' THEN 1 ELSE 0 END) AS high_count,
          sum(CASE WHEN severity='MEDIUM' THEN 1 ELSE 0 END) AS medium_count
        FROM read_parquet('{source.as_posix()}')
        GROUP BY signal_type
        ORDER BY signal_count DESC, signal_type
        """
    ).fetchdf()
    con.close()

    observed = {
        str(row["signal_type"]): row
        for row in rows.where(rows.notna(), None).to_dict("records")
    }
    total = sum(int(row.get("signal_count") or 0) for row in observed.values())
    report = []
    for signal in EXPECTED_SIGNALS:
        row = observed.get(signal, {})
        count = int(row.get("signal_count") or 0)
        share = (count / total) if total else 0.0
        status = _status(count, share, int(min_volume))
        note = {
            "EXPERIMENTAL_ZERO": "La señal no produjo resultados en la corrida; no debe ocupar espacio operativo hasta revisar datos y umbrales.",
            "LOW_VOLUME": "La señal produjo muy pocos resultados; mantener visible sólo con etiqueta experimental y revisar sensibilidad.",
            "DOMINANT_REVIEW": "La señal domina el universo; revisar umbral, grupo de pares y reglas de publicación para evitar monocultura analítica.",
            "ACTIVE": "La señal tiene producción suficiente para permanecer activa, sujeta a validación humana y calibración periódica.",
        }[status]
        report.append(
            {
                "signal_type": signal,
                "status": status,
                "signal_count": count,
                "share_of_signal_universe": round(share, 6),
                "organization_count": int(row.get("organization_count") or 0),
                "provider_count": int(row.get("provider_count") or 0),
                "observed_years": int(row.get("observed_years") or 0),
                "first_year": row.get("first_year"),
                "last_year": row.get("last_year"),
                "high_count": int(row.get("high_count") or 0),
                "medium_count": int(row.get("medium_count") or 0),
                "note": note,
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": "RIGP-SIGNAL-HEALTH-v1",
        "methodology": (
            "Auditoría descriptiva de producción y cobertura de señales. No modifica pesos ni umbrales automáticamente. "
            "Las señales con cero resultados quedan marcadas experimentales; las dominantes requieren revisión para evitar sesgo de publicación."
        ),
        "total_signals": int(total),
        "expected_signal_types": len(EXPECTED_SIGNALS),
        "active_signal_types": sum(1 for x in report if x["status"] == "ACTIVE"),
        "needs_review_signal_types": sum(1 for x in report if x["status"] != "ACTIVE"),
        "signals": report,
    }
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload
