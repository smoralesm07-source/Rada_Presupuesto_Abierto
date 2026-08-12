from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .extract import download
from .normalize import normalize_to_parquet
from .pipeline import AVAILABLE_SOURCE_STATUSES
from .search import hybrid_search
from .source_discovery import discover_downloads


def run_query(
    year: int,
    output_dir: str = "data/query",
    text: str | None = None,
    rut: str | None = None,
    organization_id: str | None = None,
    provider_id: str | None = None,
    month: int | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    purchase_order: str | None = None,
    bip: str | None = None,
    location: str | None = None,
    budget_code: str | None = None,
    limit: int = 1000,
) -> dict:
    """Execute an auditable search against one official annual bulk snapshot."""
    limit = max(1, min(int(limit), 10_000))
    sources = {
        x["year"]: x
        for x in discover_downloads()
        if x.get("status") in AVAILABLE_SOURCE_STATUSES
    }
    source = sources.get(int(year))
    if not source:
        raise SystemExit(f"No se confirmó fuente bulk oficial para {year}")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw = out / f"pagos-{year}.gz"
    parquet = out / f"transactions_{year}.parquet"
    if not raw.exists():
        download(source["url"], raw)
    normalize_meta = normalize_to_parquet(raw, parquet)

    df = hybrid_search(
        str(parquet),
        text=text,
        rut=rut,
        organization_id=organization_id,
        provider_id=provider_id,
        year=year,
        month=month,
        min_amount=min_amount,
        max_amount=max_amount,
        purchase_order=purchase_order,
        bip=bip,
        location=location,
        budget_code=budget_code,
        limit=limit,
    )
    csv_path = out / "result.csv"
    json_path = out / "result.json"
    meta_path = out / "query_metadata.json"
    df.to_csv(csv_path, index=False)
    json_path.write_text(
        df.to_json(orient="records", force_ascii=False, date_format="iso", indent=2),
        encoding="utf-8",
    )
    query = {
        "year": year,
        "text": text,
        "rut": rut,
        "organization_id": organization_id,
        "provider_id": provider_id,
        "month": month,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "purchase_order": purchase_order,
        "bip": bip,
        "location": location,
        "budget_code": budget_code,
        "limit": limit,
    }
    metadata = {
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "normalization": normalize_meta,
        "query": query,
        "result_count": int(len(df)),
        "outputs": {"csv": str(csv_path), "json": str(json_path)},
    }
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def main() -> None:
    p = argparse.ArgumentParser(description="Auditable one-year Presupuesto Abierto search job")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--text")
    p.add_argument("--rut")
    p.add_argument("--organization-id")
    p.add_argument("--provider-id")
    p.add_argument("--month", type=int)
    p.add_argument("--min-amount", type=float)
    p.add_argument("--max-amount", type=float)
    p.add_argument("--purchase-order")
    p.add_argument("--bip")
    p.add_argument("--location")
    p.add_argument("--budget-code")
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--output-dir", default="data/query")
    args = p.parse_args()
    meta = run_query(
        year=args.year,
        output_dir=args.output_dir,
        text=args.text,
        rut=args.rut,
        organization_id=args.organization_id,
        provider_id=args.provider_id,
        month=args.month,
        min_amount=args.min_amount,
        max_amount=args.max_amount,
        purchase_order=args.purchase_order,
        bip=args.bip,
        location=args.location,
        budget_code=args.budget_code,
        limit=args.limit,
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
