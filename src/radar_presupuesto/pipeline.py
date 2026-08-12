from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from .analytics import build_signals
from .anomalies import detect_all
from .coverage import write_coverage
from .dashboard import build_dashboard_json
from .extract import download
from .features import build_profiles
from .normalize import normalize_frame, normalize_to_parquet
from .quality import audit_quality
from .search import build_fts, build_fts_from_parquet
from .source_discovery import write_catalog

AVAILABLE_SOURCE_STATUSES = {"linked", "linked_available", "probed_available"}


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


def _build_signals_from_config(parquet_glob: str, cfg: dict) -> dict:
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


def run_sample(sample: str) -> None:
    raw = pd.read_csv(sample, dtype=str)
    df = normalize_frame(raw, source_file=Path(sample).name)
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    parquet = "data/processed/transactions_sample.parquet"
    df.to_parquet(parquet, index=False)
    signals = detect_all(df, load_config())
    Path("data/signals").mkdir(parents=True, exist_ok=True)
    signals.to_parquet("data/signals/risk_signals.parquet", index=False)
    build_fts(df, "data/index/search.sqlite")
    build_profiles(parquet)
    audit_quality(parquet)
    build_dashboard_json(parquet, "data/signals/risk_signals.parquet")


def run_years(years: list[int], build_search_index: bool = True) -> None:
    catalog_rows = write_catalog("docs/data/source_catalog.json")
    write_coverage("docs/data/coverage.json")
    catalog = {
        x["year"]: x
        for x in catalog_rows
        if x.get("status") in AVAILABLE_SOURCE_STATUSES
    }
    processed: list[Path] = []
    snapshots: list[dict] = []
    for year in years:
        src = catalog.get(year)
        if not src:
            print(
                f"[WARN] Sin fuente bulk confirmada para {year}; "
                "queda registrado como brecha de cobertura."
            )
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
        raise SystemExit(
            "No fue posible procesar ningún año solicitado; "
            "revisar docs/data/source_catalog.json"
        )

    _write_snapshot_manifest(snapshots)
    glob = "data/processed/transactions_*.parquet"
    quality = audit_quality(glob)
    print(
        f"[OK] calidad: {quality['status']} | "
        f"devengado={quality['coverage']['monto_devengado']:.1%} | "
        f"RUT válido={quality['coverage']['valid_rut']:.1%} | "
        f"ID SHA1={quality['coverage']['hashed_source_identity']:.1%}"
    )
    cfg = load_config()
    build_profiles(glob)
    signal_result = _build_signals_from_config(glob, cfg)
    print(f"[OK] señales: {signal_result['signals']:,} | {signal_result['by_type']}")
    if build_search_index:
        indexed = build_fts_from_parquet(glob, "data/index/search.sqlite")
        print(f"[OK] índice FTS: {indexed:,} transacciones")
    else:
        print("[OK] índice FTS omitido para esta corrida de recalibración")
    build_dashboard_json(glob, "data/signals/risk_signals.parquet")


def main() -> None:
    p = argparse.ArgumentParser(description="Radar Presupuesto Abierto pipeline")
    p.add_argument("--years", nargs="*", type=int)
    p.add_argument("--sample")
    p.add_argument(
        "--skip-index",
        action="store_true",
        help="Omite la reconstrucción FTS; útil para recalibración del motor analítico.",
    )
    args = p.parse_args()
    if args.sample:
        run_sample(args.sample)
    elif args.years:
        run_years(args.years, build_search_index=not args.skip_index)
    else:
        p.error("use --sample FILE or --years YYYY ...")


if __name__ == "__main__":
    main()
