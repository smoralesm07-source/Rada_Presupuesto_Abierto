from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .extract import download
from .normalize import normalize_to_parquet
from .pipeline import AVAILABLE_SOURCE_STATUSES
from .search import hybrid_search
from .source_discovery import discover_downloads

ALLOWED_FILTERS = {
    "rut", "source_id", "identity_type",
    "organization_id", "recipient_id", "provider_id",
    "partida", "capitulo", "area", "month", "date_from", "date_to",
    "min_amount", "max_amount", "min_paid_amount", "max_paid_amount",
    "currency", "purchase_order", "has_purchase_order", "bip", "has_bip",
    "has_valid_rut", "location", "region", "sector", "budget_code",
    "document_number", "document_type", "provider_only", "person_only",
    "honorarium_only", "intra_state_only", "floating_debt_only",
    "aggregated_only", "min_payment_days", "max_payment_days",
}


def parse_years(spec: str | None) -> list[int]:
    """Parse `2026`, `2024 2025 2026`, `2024,2026` or `2016-2026`."""
    if not spec or not spec.strip():
        raise ValueError("Debe indicar al menos un año")
    years: set[int] = set()
    for token in re.split(r"[\s,;]+", spec.strip()):
        if not token:
            continue
        if re.fullmatch(r"\d{4}-\d{4}", token):
            start, end = (int(x) for x in token.split("-", 1))
            if start > end:
                start, end = end, start
            years.update(range(start, end + 1))
        elif re.fullmatch(r"\d{4}", token):
            years.add(int(token))
        else:
            raise ValueError(f"Especificación de año inválida: {token}")
    if not years:
        raise ValueError("Debe indicar al menos un año")
    if min(years) < 2016:
        raise ValueError("Presupuesto Abierto bulk se consulta desde 2016")
    return sorted(years)


def _cleanup_year_files(raw: Path, parquet: Path) -> None:
    for path in (raw, parquet, raw.with_suffix(raw.suffix + ".metadata.json")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def run_query_years(
    years: list[int],
    output_dir: str = "data/query",
    text: str | None = None,
    filters: dict | None = None,
    limit: int = 1000,
) -> dict:
    """Run one auditable query over one or many official annual bulk files.

    Each year is downloaded, normalized, queried and deleted before the next year.
    This makes a full-history 2016-2026 search feasible on a GitHub-hosted runner
    without persisting the entire historical warehouse on disk.
    """
    years = sorted(set(int(y) for y in years))
    if not years:
        raise ValueError("Debe indicar al menos un año")
    limit = max(1, min(int(limit), 10_000))
    filters = filters or {}
    unknown = set(filters) - ALLOWED_FILTERS
    if unknown:
        raise ValueError(f"Filtros no soportados: {sorted(unknown)}")

    sources = {
        x["year"]: x
        for x in discover_downloads()
        if x.get("status") in AVAILABLE_SOURCE_STATUSES
    }
    out = Path(output_dir)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    processed: list[dict] = []
    gaps: list[dict] = []

    for year in years:
        source = sources.get(year)
        if not source:
            gaps.append({"year": year, "status": "SOURCE_NOT_CONFIRMED"})
            continue
        raw = work / f"pagos-{year}.gz"
        parquet = work / f"transactions_{year}.parquet"
        try:
            download_meta = download(source["url"], raw)
            normalize_meta = normalize_to_parquet(raw, parquet)
            result = hybrid_search(
                str(parquet),
                text=text,
                year=year,
                limit=limit,
                **filters,
            )
            if not result.empty:
                frames.append(result)
            processed.append(
                {
                    "year": year,
                    "source_url": source["url"],
                    "source_status": source.get("status"),
                    "source_sha256": download_meta.get("sha256"),
                    "source_bytes": download_meta.get("bytes"),
                    "normalized_rows": normalize_meta.get("rows"),
                    "delimiter": normalize_meta.get("delimiter"),
                    "matched_rows_before_global_limit": int(len(result)),
                }
            )
        except Exception as exc:
            gaps.append(
                {
                    "year": year,
                    "status": "PROCESSING_ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            )
        finally:
            _cleanup_year_files(raw, parquet)

    if not processed:
        raise RuntimeError(
            "No fue posible procesar ninguno de los años solicitados; revise las brechas registradas"
        )

    if frames:
        combined = pd.concat(frames, ignore_index=True, sort=False)
        combined["_sort_amount"] = pd.to_numeric(
            combined.get("monto_devengado"), errors="coerce"
        )
        combined = combined.sort_values(
            ["periodo", "mes", "_sort_amount"],
            ascending=[False, False, False],
            na_position="last",
        ).drop(columns=["_sort_amount"])
        combined = combined.head(limit)
    else:
        combined = pd.DataFrame()

    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "result.csv"
    json_path = out / "result.json"
    meta_path = out / "query_metadata.json"
    combined.to_csv(csv_path, index=False)
    json_path.write_text(
        combined.to_json(
            orient="records",
            force_ascii=False,
            date_format="iso",
            indent=2,
        ),
        encoding="utf-8",
    )

    metadata = {
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": {
            "years": years,
            "text": text,
            "filters": filters,
            "global_limit": limit,
        },
        "processed_years": processed,
        "coverage_gaps": gaps,
        "result_count": int(len(combined)),
        "outputs": {"csv": str(csv_path), "json": str(json_path)},
        "methodology": (
            "Cada año se consulta contra su snapshot bulk oficial y se elimina del runner "
            "tras la consulta. El límite se aplica globalmente después de combinar años."
        ),
    }
    meta_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def run_query(
    year: int,
    output_dir: str = "data/query",
    text: str | None = None,
    filters: dict | None = None,
    limit: int = 1000,
) -> dict:
    """Backward-compatible one-year wrapper."""
    return run_query_years([year], output_dir, text, filters, limit)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Auditable multi-year Presupuesto Abierto search job"
    )
    p.add_argument(
        "--years",
        required=True,
        help="Ej.: 2026 | '2024 2025 2026' | 2016-2026",
    )
    p.add_argument("--text")
    p.add_argument("--filters-json", default="{}")
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--output-dir", default="data/query")
    args = p.parse_args()
    filters = json.loads(args.filters_json)
    result = run_query_years(
        parse_years(args.years),
        args.output_dir,
        args.text,
        filters,
        args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
