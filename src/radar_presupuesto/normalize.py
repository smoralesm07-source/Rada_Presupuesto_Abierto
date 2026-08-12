from __future__ import annotations

import csv
import gzip
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from .ids import normalize_rut, normalize_text, organization_id, provider_id, transaction_id

ALIASES = {
    "PERIODO": "periodo", "MES": "mes", "PARTIDA": "partida", "NOMBRE_PARTIDA": "nombre_partida",
    "CAPITULO": "capitulo", "NOMBRE_CAPITULO": "nombre_capitulo", "AREA": "area", "NOMBRE_AREA": "nombre_area",
    "SUBTITULO": "subtitulo", "NOMBRE_SUBTITULO": "nombre_subtitulo", "ITEM": "item", "NOMBRE_ITEM": "nombre_item",
    "ASIGNACION": "asignacion", "NOMBRE_ASIGNACION": "nombre_asignacion", "RUT_BENEFICIARIO": "rut_beneficiario",
    "NOMBRE_BENEFICIARIO": "nombre_beneficiario", "NUMERO_DOCUMENTO": "numero_documento",
    "FECHA_DOCUMENTO": "fecha_documento", "TIPO_DOCUMENTO": "tipo_documento", "ORDEN_DE_COMPRA": "orden_compra",
    "FECHA_INGRESO": "fecha_ingreso", "FECHA_RECEPCION_CONFORME": "fecha_recepcion_conforme",
    "MONEDA_PRESUPUESTARIA": "moneda_presupuestaria", "MONTO_DEVENGADO": "monto_devengado",
    "FECHA_PAGO": "fecha_pago", "MONTO_PAGO": "monto_pago", "RUT_PRINCIPAL": "rut_principal",
    "NOMBRE_PRINCIPAL": "nombre_principal", "FOLIO": "folio", "USUARIO_APROBADOR": "usuario_aprobador",
    "AGREGADO": "agregado", "BLOQUEO_OC": "bloqueo_oc", "CODIGO_BIP": "codigo_bip", "NOMBRE_BIP": "nombre_bip",
    "CODIGO_UBICACION_GEOGRAFICA": "codigo_ubicacion_geografica",
    "NOMBRE_UBICACION_GEOGRAFICA": "nombre_ubicacion_geografica",
    "CODIGO_PROGRAMA_PRESUPUESTARIO": "codigo_programa_presupuestario",
    "NOMBRE_PROGRAMA_PRESUPUESTARIO": "nombre_programa_presupuestario",
}

CANONICAL_SOURCE_COLUMNS = list(dict.fromkeys(ALIASES.values()))
DATE_COLS = ["fecha_documento", "fecha_ingreso", "fecha_recepcion_conforme", "fecha_pago"]
AMOUNT_COLS = ["monto_devengado", "monto_pago"]
INT_COLS = ["periodo", "mes"]
TEXT_COLS = [c for c in CANONICAL_SOURCE_COLUMNS if c not in set(DATE_COLS + AMOUNT_COLS + INT_COLS)]


def canonical_column(name: str) -> str:
    key = normalize_text(name).replace(" ", "_")
    key = re.sub(r"_+", "_", key)
    return ALIASES.get(key, key.lower())


def normalize_frame(df: pd.DataFrame, source_url: str = "", source_file: str = "") -> pd.DataFrame:
    """Apply a stable canonical contract even when optional source columns are absent."""
    out = df.rename(columns={c: canonical_column(c) for c in df.columns}).copy()

    # Schema drift is expected across years/systems. Missing official fields remain null/blank,
    # but the normalized Parquet contract is stable for analytics and search.
    for col in CANONICAL_SOURCE_COLUMNS:
        if col not in out:
            out[col] = pd.NA

    for col in TEXT_COLS:
        out[col] = out[col].fillna("").astype(str)
    for col in DATE_COLS:
        out[col] = pd.to_datetime(out[col], dayfirst=True, errors="coerce")
    for col in AMOUNT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Float64")
    for col in INT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")

    out["rut_beneficiario_normalizado"] = out["rut_beneficiario"].map(normalize_rut)
    out["beneficiario_normalizado"] = out["nombre_beneficiario"].map(normalize_text)
    out["organization_id"] = [
        organization_id(r.partida, r.capitulo, r.area, r.nombre_area)
        for r in out.itertuples()
    ]
    out["provider_id"] = [
        provider_id(r, n)
        for r, n in zip(out["rut_beneficiario"], out["nombre_beneficiario"])
    ]
    out["transaction_id"] = [transaction_id(r) for r in out.to_dict("records")]
    out["record_class"] = "SOURCE_FACT"
    out["source_system"] = "PRESUPUESTO_ABIERTO"
    out["source_url"] = source_url
    out["source_file"] = source_file
    return out


def detect_delimiter(path: str | Path) -> str:
    """Detect the bulk CSV delimiter once, then keep pandas on its fast C parser."""
    path = Path(path)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(64 * 1024)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;|\t").delimiter
    except csv.Error:
        # Comma is the documented/most common CSV default; schema validation will catch a bad parse.
        return ","


def read_normalized(path: str | Path, chunksize: int = 100_000) -> Iterable[pd.DataFrame]:
    path = Path(path)
    compression = "gzip" if path.suffix.lower() == ".gz" else "infer"
    sep = detect_delimiter(path)
    for chunk in pd.read_csv(
        path,
        compression=compression,
        sep=sep,
        encoding="utf-8-sig",
        dtype=str,
        chunksize=chunksize,
        low_memory=False,
    ):
        yield normalize_frame(chunk, source_file=path.name)


def normalize_to_parquet(path: str | Path, output_path: str | Path, chunksize: int = 100_000) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    rows = 0
    try:
        for chunk in read_normalized(path, chunksize=chunksize):
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(output_path, table.schema, compression="zstd")
            writer.write_table(table)
            rows += len(chunk)
    finally:
        if writer is not None:
            writer.close()
    return {"path": str(output_path), "rows": rows, "delimiter": detect_delimiter(path)}
