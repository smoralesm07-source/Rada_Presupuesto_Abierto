from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from .advanced_signals import extend_signals
from .analytics import build_signals
from .cgr_correlation import correlate_with_cgr
from .coverage import write_coverage
from .dashboard import build_dashboard_json
from .entity_signals import build_entity_signals, merge_into_risk_signals
from .entity_signals import summarize as summarize_entity_signals
from .extract import download
from .features import build_profiles
from .investigative_findings import build_investigative_findings
from .normalize import normalize_frame, normalize_to_parquet
from .operational_bundle import build_operational_bundle
from .prioritization import prioritize_signals
from .quality import audit_quality
from .search import build_fts, build_fts_from_parquet
from .sii_document_candidates import build_sii_document_candidates
from .source_discovery import write_catalog
from .spend_view import build_spend_view_v2

AVAILABLE_SOURCE_STATUSES = {"linked", "linked_available", "probed_available"}
DEFAULT_CGR_DIR = "external/radar-cgr/data/silver"


def load_config(path: str = "config/anomaly_thresholds.yaml") -> dict:
    p = Path(path)
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def _write_snapshot_manifest(rows: list[dict]) -> None:
    out = Path("docs/data/snapshot_manifest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_system": "PRESUPUESTO_ABIERTO",
                "snapshots": rows,
                "note": "SHA-256 identifica exactamente el bulk utilizado en la corrida; los archivos masivos no se versionan en Git.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _build_base_signals(parquet_glob: str, cfg: dict) -> dict:
    amount = cfg.get("amount_outlier", {})
    frag = cfg.get("potential_fragmentation", {})
    year_end = cfg.get("year_end_spike", {})
    return build_signals(
        parquet_glob,
        amount_z=amount.get("threshold", 4.5),
        min_group=amount.get("min_group", 20),
        amount_min_ratio=amount.get("min_ratio", 3.0),
        amount_quantile=amount.get("quantile_floor", 0.99),
        amount_provider_only=amount.get("provider_only", True),
        amount_exclude_aggregated=amount.get("exclude_aggregated", True),
        frag_min=frag.get("min_count", 3),
        frag_cv=frag.get("max_cv", 0.15),
        year_end_ratio=year_end.get("ratio_threshold", 2.5),
    )


def _build_entity_signals(parquet_glob: str, cfg: dict) -> dict:
    """Capa de contraparte: se construye aparte y luego entra a la cola común.

    Sin el merge la capa existiría como producto aislado y no participaría de la
    priorización ni de la corroboración de tipologías.
    """
    result = build_entity_signals(parquet_glob, config=cfg.get("entity_signals", {}))
    result["merge"] = merge_into_risk_signals(parquet_glob)
    return result


def _extend_from_config(parquet_glob: str, cfg: dict) -> dict:
    concentration = cfg.get("provider_concentration", {})
    delay = cfg.get("payment_delay_outlier", {})
    new_series = cfg.get("new_to_series_high_spend", {})
    return extend_signals(
        parquet_glob,
        concentration_min_providers=concentration.get("min_providers", 8),
        concentration_min_share=concentration.get("min_share", 0.45),
        concentration_min_hhi=concentration.get("min_hhi", 0.25),
        concentration_min_amount=concentration.get("min_amount", 10_000_000),
        payment_delay_min_days=delay.get("min_days", 60),
        payment_delay_min_group=delay.get("min_group", 20),
        payment_delay_quantile=delay.get("quantile_floor", 0.99),
        new_series_min_amount=new_series.get("min_amount", 50_000_000),
        new_series_quantile=new_series.get("quantile_floor", 0.99),
    )


def _run_cgr_correlation(parquet_glob: str, cgr_dir: str) -> dict:
    return correlate_with_cgr(parquet_glob, cgr_silver_dir=cgr_dir)


def _run_analytics(
    parquet_glob: str,
    cfg: dict,
    cgr_dir: str,
    years: list[int] | None = None,
    build_legacy_spend_view: bool = True,
) -> dict:
    build_profiles(parquet_glob)
    base = _build_base_signals(parquet_glob, cfg)
    extended = _extend_from_config(parquet_glob, cfg)

    # La capa de entidad entra a la cola antes de priorizar: aporta patrones de
    # otra naturaleza, que es lo que permite corroborar una hipótesis en vez de
    # proponerla desde una sola señal de la capa de transacción.
    entity = _build_entity_signals(parquet_glob, cfg)

    cgr = _run_cgr_correlation(parquet_glob, cgr_dir)

    # La cola JSON permanece como producto de auditoría; no define el universo visible.
    queue = prioritize_signals(parquet_glob, top_n=5000)

    # Los hallazgos se generan completos en parquet y luego el bundle operacional
    # publica un lote acotado con reserva de diversidad, contexto de pares y patrones.
    findings = build_investigative_findings(top_n=600)
    operational = build_operational_bundle(
        parquet_glob,
        years=years,
        max_published_findings=600,
        reserve_per_signal=20,
    )

    dashboard = build_dashboard_json(
        parquet_glob,
        "data/signals/risk_signals.parquet",
        prioritized_path="data/signals/prioritized_signals.parquet",
        cgr_json="docs/data/cgr_correlation.json",
    )

    if build_legacy_spend_view:
        spend_view = build_spend_view_v2(
            parquet_glob,
            output="docs/data/spend_view_v2.json",
            prioritized_path="data/signals/prioritized_signals.parquet",
        )
    else:
        spend_view = {
            "skipped": True,
            "reason": (
                "La corrida operacional case-first no reconstruye spend_view_v2.json; "
                "ese producto pertenece al pipeline histórico Corrected Spend Data v3."
            ),
        }

    sii_document_candidates = build_sii_document_candidates(parquet_glob)
    return {
        "base": base,
        "extended": extended,
        "entity": entity,
        "cgr": cgr,
        "queue": queue,
        "findings": findings,
        "operational": operational,
        "dashboard": dashboard,
        "spend_view": spend_view,
        "sii_document_candidates": sii_document_candidates,
    }


def run_sample(sample: str, cgr_dir: str = DEFAULT_CGR_DIR) -> None:
    raw = pd.read_csv(sample, dtype=str)
    df = normalize_frame(raw, source_file=Path(sample).name)
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    parquet = "data/processed/transactions_sample.parquet"
    df.to_parquet(parquet, index=False)
    build_fts(df, "data/index/search.sqlite")
    quality = audit_quality(parquet)
    if quality["transaction_id_collision_ratio"] != 0:
        raise RuntimeError("transaction_id debe ser único para cada fila fuente")
    years = sorted({int(x) for x in df["periodo"].dropna().tolist()}) if "periodo" in df.columns else []
    result = _run_analytics(parquet, load_config(), cgr_dir, years=years)
    print(
        f"[OK] muestra: {len(df):,} filas | señales={result['extended']['signals']:,} | "
        f"prioridad={result['queue']['priority_tiers']} | hallazgos={result['findings']['relations']:,} | "
        f"publicados={result['operational']['publication']['relations_published']:,} | "
        f"candidatos SII={result['sii_document_candidates']['rows']:,}"
    )


def run_years(
    years: list[int],
    build_search_index: bool = True,
    cgr_dir: str = DEFAULT_CGR_DIR,
    build_legacy_spend_view: bool = True,
) -> None:
    catalog_rows = write_catalog("docs/data/source_catalog.json")
    write_coverage("docs/data/coverage.json")
    catalog = {x["year"]: x for x in catalog_rows if x.get("status") in AVAILABLE_SOURCE_STATUSES}
    processed: list[Path] = []
    snapshots: list[dict] = []
    for year in years:
        src = catalog.get(year)
        if not src:
            print(f"[WARN] Sin fuente bulk confirmada para {year}; queda registrado como brecha de cobertura.")
            continue
        raw = Path("data/raw") / f"pagos-{year}.gz"
        parquet = Path("data/processed") / f"transactions_{year}.parquet"
        download_meta = download(src["url"], raw)
        normalize_meta = normalize_to_parquet(raw, parquet)
        print(f"[OK] {year}: {normalize_meta['rows']:,} registros normalizados")
        processed.append(parquet)
        snapshots.append(
            {
                "year": year,
                "source_url": src["url"],
                "source_status": src.get("status"),
                "sha256": download_meta.get("sha256"),
                "bytes": download_meta.get("bytes"),
                "downloaded_at": download_meta.get("downloaded_at"),
                "normalized_rows": normalize_meta.get("rows"),
                "delimiter": normalize_meta.get("delimiter"),
                "normalized_output": parquet.name,
            }
        )

    if not processed:
        raise SystemExit("No fue posible procesar ningún año solicitado; revisar docs/data/source_catalog.json")

    _write_snapshot_manifest(snapshots)
    glob = "data/processed/transactions_*.parquet"
    quality = audit_quality(glob)
    if quality["transaction_id_collision_ratio"] != 0:
        raise RuntimeError(
            "Falla de integridad: transaction_id no es único. "
            "Las repeticiones documentales deben compartir fingerprint, no ID físico."
        )
    print(
        f"[OK] calidad: {quality['status']} | devengado={quality['coverage']['monto_devengado']:.1%} | "
        f"RUT válido={quality['coverage']['valid_rut']:.1%} | "
        f"ID SHA1={quality['coverage']['hashed_source_identity']:.1%} | "
        f"repetición documental={quality['source_fact_repeat_ratio']:.2%}"
    )

    effective_years = sorted(int(p.stem.rsplit("_", 1)[-1]) for p in processed)
    result = _run_analytics(
        glob,
        load_config(),
        cgr_dir,
        years=effective_years,
        build_legacy_spend_view=build_legacy_spend_view,
    )
    print(f"[OK] señales operativas: {result['extended']['signals']:,} | {result['extended']['by_type']}")
    print(
        f"[OK] capa de entidad: {summarize_entity_signals(result['entity'])} | "
        f"incorporadas a la cola={result['entity']['merge'].get('merged', 0):,}"
    )
    print(
        f"[OK] CGR: {result['cgr']['status']} | enlaces candidatos={result['cgr']['links']:,} | "
        f"con hallazgos={result['cgr']['links_with_findings']:,}"
    )
    print(f"[OK] cola investigativa: {result['queue']['priority_tiers']}")
    print(
        f"[OK] hallazgos RIGP: {result['findings']['relations']:,} relaciones analíticas | "
        f"publicados={result['operational']['publication']['relations_published']:,} | "
        f"con pares={result['operational']['finding_context_coverage']['relations_with_peer_context']:,} | "
        f"con patrón={result['operational']['finding_context_coverage']['relations_with_primary_pattern']:,}"
    )
    print(
        f"[OK] salud de señales: activas={result['operational']['signal_health']['active_signal_types']} | "
        f"requieren revisión={result['operational']['signal_health']['needs_review_signal_types']} | "
        f"{result['operational']['signal_health']['statuses']}"
    )
    print(
        f"[OK] contratación: hallazgos={result['operational']['procurement_context']['findings_requested']:,} | "
        f"con OC={result['operational']['procurement_context']['findings_with_purchase_order']:,}"
    )
    if result["spend_view"].get("skipped"):
        print("[OK] spend-view histórico omitido en esta corrida operacional")
    else:
        print(
            f"[OK] spend-view L12: {len(result['spend_view']['services']):,} servicios | "
            f"{len(result['spend_view']['providers']):,} proveedores | "
            f"{len(result['spend_view']['flows']):,} flujos publicados"
        )
    print(
        f"[OK] candidatos documentales SII: {result['sii_document_candidates']['rows']:,} entidades | "
        f"{result['sii_document_candidates']['min_document_date'] or '—'} a "
        f"{result['sii_document_candidates']['max_document_date'] or '—'}"
    )

    if build_search_index:
        indexed = build_fts_from_parquet(glob, "data/index/search.sqlite")
        print(f"[OK] índice FTS: {indexed:,} transacciones")
    else:
        print("[OK] índice FTS omitido para esta corrida operacional")


def main() -> None:
    p = argparse.ArgumentParser(description="Radar Presupuesto Abierto pipeline")
    p.add_argument("--years", nargs="*", type=int)
    p.add_argument("--sample")
    p.add_argument("--cgr-dir", default=DEFAULT_CGR_DIR)
    p.add_argument(
        "--skip-index",
        action="store_true",
        help="Omite la reconstrucción FTS; útil para la corrida operacional web.",
    )
    p.add_argument(
        "--skip-legacy-spend-view",
        action="store_true",
        help=(
            "No reconstruye spend_view_v2.json. Recomendado para Radar monthly, "
            "donde ese producto es responsabilidad de Corrected Spend Data v3."
        ),
    )
    args = p.parse_args()
    if args.sample:
        run_sample(args.sample, cgr_dir=args.cgr_dir)
    elif args.years:
        run_years(
            args.years,
            build_search_index=not args.skip_index,
            cgr_dir=args.cgr_dir,
            build_legacy_spend_view=not args.skip_legacy_spend_view,
        )
    else:
        p.error("use --sample FILE or --years YYYY ...")


if __name__ == "__main__":
    main()
