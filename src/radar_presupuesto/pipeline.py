from __future__ import annotations

import argparse
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


def run_years(years: list[int]) -> None:
    catalog_rows = write_catalog("docs/data/source_catalog.json")
    write_coverage("docs/data/coverage.json")
    catalog = {
        x["year"]: x
        for x in catalog_rows
        if x.get("status") in AVAILABLE_SOURCE_STATUSES
    }
    processed = []
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
        download(src["url"], raw)
        meta = normalize_to_parquet(raw, parquet)
        print(f"[OK] {year}: {meta['rows']:,} registros normalizados")
        processed.append(parquet)

    if not processed:
        raise SystemExit(
            "No fue posible procesar ningún año solicitado; "
            "revisar docs/data/source_catalog.json"
        )

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
    build_signals(
        glob,
        amount_z=cfg.get("amount_outlier", {}).get("threshold", 4.5),
        min_group=cfg.get("amount_outlier", {}).get("min_group", 8),
        frag_min=cfg.get("potential_fragmentation", {}).get("min_count", 3),
        frag_cv=cfg.get("potential_fragmentation", {}).get("max_cv", 0.15),
        year_end_ratio=cfg.get("year_end_spike", {}).get("ratio_threshold", 2.5),
    )
    indexed = build_fts_from_parquet(glob, "data/index/search.sqlite")
    print(f"[OK] índice FTS: {indexed:,} transacciones")
    build_dashboard_json(glob, "data/signals/risk_signals.parquet")


def main() -> None:
    p = argparse.ArgumentParser(description="Radar Presupuesto Abierto pipeline")
    p.add_argument("--years", nargs="*", type=int)
    p.add_argument("--sample")
    args = p.parse_args()
    if args.sample:
        run_sample(args.sample)
    elif args.years:
        run_years(args.years)
    else:
        p.error("use --sample FILE or --years YYYY ...")


if __name__ == "__main__":
    main()
