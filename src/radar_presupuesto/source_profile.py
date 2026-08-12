from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .extract import download
from .normalize import canonical_column, detect_delimiter
from .pipeline import AVAILABLE_SOURCE_STATUSES
from .source_discovery import discover_downloads


def profile_year(year: int, output: str = "docs/data/source_profile.json", nrows: int = 250_000) -> dict:
    sources = {
        x["year"]: x for x in discover_downloads()
        if x.get("status") in AVAILABLE_SOURCE_STATUSES
    }
    source = sources.get(year)
    if not source:
        raise SystemExit(f"No bulk source confirmed for {year}")

    raw = Path("data/raw") / f"profile-pagos-{year}.gz"
    if not raw.exists():
        download(source["url"], raw)
    sep = detect_delimiter(raw)
    df = pd.read_csv(
        raw,
        compression="gzip",
        sep=sep,
        encoding="utf-8-sig",
        dtype=str,
        nrows=nrows,
        low_memory=False,
    )
    original_columns = list(df.columns)
    canonical = {c: canonical_column(c) for c in df.columns}
    renamed = df.rename(columns=canonical)

    def counts(col: str, top: int = 20) -> dict[str, int]:
        if col not in renamed:
            return {}
        values = renamed[col].fillna("").astype(str).str.strip()
        return {str(k): int(v) for k, v in values.value_counts(dropna=False).head(top).items()}

    beneficiary = renamed.get("rut_beneficiario", pd.Series([], dtype="string")).fillna("").astype(str).str.strip()
    lengths = Counter(beneficiary.str.replace(r"[^0-9Kk]", "", regex=True).str.len().tolist())
    name = renamed.get("nombre_beneficiario", pd.Series([], dtype="string")).fillna("").astype(str).str.strip()
    synthetic_mask = beneficiary.str.replace(r"[^0-9Kk]", "", regex=True).str.len() > 9

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "year": year,
        "source": source,
        "sample_rows": int(len(df)),
        "delimiter": sep,
        "original_columns": original_columns,
        "canonical_column_mapping": canonical,
        "value_counts": {
            "proveedor": counts("proveedor"),
            "persona": counts("persona"),
            "honorario": counts("honorario"),
            "intraestado": counts("intraestado"),
            "deuda_flotante": counts("deuda_flotante"),
            "agregado": counts("agregado"),
        },
        "beneficiary_clean_length_counts": {str(k): int(v) for k, v in sorted(lengths.items())},
        "synthetic_beneficiary_rows": int(synthetic_mask.sum()),
        "synthetic_beneficiary_examples": [
            {"raw": str(r), "name": str(n)}
            for r, n in zip(beneficiary[synthetic_mask].head(30), name[synthetic_mask].head(30))
        ],
        "note": "Perfil descriptivo de la fuente. No convierte identificadores sintéticos en RUT ni asigna riesgo.",
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--output", default="docs/data/source_profile.json")
    p.add_argument("--nrows", type=int, default=250_000)
    args = p.parse_args()
    print(json.dumps(profile_year(args.year, args.output, args.nrows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
