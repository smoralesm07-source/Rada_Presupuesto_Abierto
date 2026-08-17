from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def _read_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_fusion_preview(payload: dict, output: str = "docs/data/fusion_preview.json") -> dict:
    """Publica un contrato compacto para consumidores externos.

    El Workbench no necesita descargar la cola completa de investigación para
    mostrar el estado del radar. Este preview conserva métricas agregadas,
    tiers y sólo las primeras señales priorizadas, sin cambiar la semántica
    del score ni promoverlas a hallazgos Fusion.
    """
    keep = (
        "signal_id",
        "signal_type",
        "transaction_id",
        "organization_id",
        "provider_id",
        "recipient_id",
        "periodo",
        "mes",
        "organization_name",
        "provider_or_recipient_name",
        "transaction_amount",
        "severity",
        "confidence",
        "why_flagged",
        "investigation_hypothesis",
        "cgr_match_count",
        "cgr_finding_count",
        "investigation_priority_score",
        "priority_tier",
        "priority_explanation",
    )
    top_signals = [
        {key: row.get(key) for key in keep if key in row}
        for row in (payload.get("signals") or [])[:8]
    ]
    preview = {
        "schema": "PRESUPUESTO_FUSION_PREVIEW_V1",
        "generated_at": payload.get("generated_at"),
        "version": payload.get("version"),
        "integration_status": "RADAR_OPERATIONAL_FUSION_ADAPTER_PENDING",
        "metrics": payload.get("metrics") or {},
        "signal_types": payload.get("signal_types") or {},
        "priority_tiers": payload.get("priority_tiers") or {},
        "cgr_correlation": payload.get("cgr_correlation") or {},
        "top_signals": top_signals,
        "methodology_note": payload.get("methodology_note", ""),
        "guardrail": (
            "Este preview permite visibilidad en el Workbench antes de completar el "
            "adaptador canónico. Las señales siguen siendo objetos de Radar Presupuesto "
            "Abierto y no se consideran hallazgos del Intelligence Fusion Layer."
        ),
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(preview, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return preview


def build_dashboard_json(
    parquet_glob: str,
    signals_path: str,
    output: str = "docs/data/dashboard.json",
    top_n: int = 250,
    prioritized_path: str = "data/signals/prioritized_signals.parquet",
    cgr_json: str = "docs/data/cgr_correlation.json",
) -> dict:
    con = duckdb.connect()
    con.execute(
        f"CREATE OR REPLACE VIEW facts AS "
        f"SELECT * FROM read_parquet('{parquet_glob}',union_by_name=true)"
    )
    metrics = con.execute(
        """
        SELECT count(*),count(DISTINCT organization_id),count(DISTINCT recipient_id),
               count(DISTINCT provider_id) FILTER (
                   WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''
               ),
               coalesce(sum(try_cast(monto_devengado AS DOUBLE)),0),min(periodo),max(periodo)
        FROM facts
        """
    ).fetchone()

    sig_count = 0
    sig_types: dict = {}
    if Path(signals_path).exists():
        con.execute(
            f"CREATE OR REPLACE VIEW sig AS SELECT * FROM read_parquet('{signals_path}')"
        )
        sig_count = int(con.execute("SELECT count(*) FROM sig").fetchone()[0])
        sig_types = dict(
            con.execute(
                "SELECT signal_type,count(*) FROM sig GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        )

    signals: list[dict] = []
    priority_tiers: dict = {}
    p1_count = 0
    if Path(prioritized_path).exists():
        con.execute(
            f"CREATE OR REPLACE VIEW priority AS SELECT * FROM read_parquet('{prioritized_path}')"
        )
        priority_tiers = dict(
            con.execute(
                "SELECT priority_tier,count(*) FROM priority GROUP BY 1 ORDER BY 1"
            ).fetchall()
        )
        p1_count = int(priority_tiers.get("P1", 0))
        df = con.execute(
            f"""
            SELECT * FROM priority
            ORDER BY investigation_priority_score DESC,
                     CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                     coalesce(deviation,0) DESC
            LIMIT {int(top_n)}
            """
        ).df()
        signals = df.where(df.notna(), None).to_dict("records")
    elif Path(signals_path).exists():
        df = con.execute(
            f"""
            SELECT * FROM sig
            ORDER BY CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                     coalesce(deviation,0) DESC
            LIMIT {int(top_n)}
            """
        ).df()
        signals = df.where(df.notna(), None).to_dict("records")
    con.close()

    cgr = _read_json(cgr_json)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "0.3-operational",
        "metrics": {
            "transactions": int(metrics[0]),
            "organizations": int(metrics[1]),
            "recipients": int(metrics[2]),
            "providers": int(metrics[3]),
            "amount_clp": float(metrics[4]),
            "first_year": None if metrics[5] is None else int(metrics[5]),
            "last_year": None if metrics[6] is None else int(metrics[6]),
            "signals": int(sig_count),
            "priority_p1": p1_count,
            "cgr_candidate_links": int(cgr.get("links") or 0),
            "cgr_links_with_findings": int(cgr.get("links_with_findings") or 0),
        },
        "signal_types": sig_types,
        "priority_tiers": priority_tiers,
        "cgr_correlation": {
            "status": cgr.get("status", "NO_CGR_DATA"),
            "links": int(cgr.get("links") or 0),
            "provider_links": int(cgr.get("provider_links") or 0),
            "organization_links": int(cgr.get("organization_links") or 0),
            "links_with_findings": int(cgr.get("links_with_findings") or 0),
            "high_confidence_links": int(cgr.get("high_confidence_links") or 0),
            "methodology": cgr.get("methodology", ""),
        },
        "signals": signals,
        "methodology_note": (
            "Las señales son patrones estadísticos para priorizar revisión; no constituyen "
            "hallazgos de ilegalidad ni imputaciones AML. El score 0-100 es prioridad "
            "investigativa explicable, no probabilidad de delito. Los cruces CGR son "
            "coincidencias de entidad candidatas y requieren verificación documental."
        ),
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _write_fusion_preview(payload)
    return payload
