from __future__ import annotations

import csv
import gzip
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from .ids import (
    flag_is_true,
    normalize_rut,
    normalize_text,
    organization_id,
    provider_id,
    recipient_id,
    source_identifier_type,
    transaction_fingerprint,
    transaction_id,
)

ALIASES = {
    "PERIODO": "periodo", "MES": "mes", "PARTIDA": "partida", "NOMBRE_PARTIDA": "nombre_partida",
    "CAPITULO": "capitulo", "NOMBRE_CAPITULO": "nombre_capitulo", "AREA": "area", "NOMBRE_AREA": "nombre_area",
    "SUBTITULO": "subtitulo", "NOMBRE_SUBTITULO": "nombre_subtitulo", "ITEM": "item", "NOMBRE_ITEM": "nombre_item",
    "ASIGNACION": "asignacion", "NOMBRE_ASIGNACION": "nombre_asignacion",
    "BENEFICIARIO": "beneficiario_source_id", "RUT_BENEFICIARIO": "beneficiario_source_id",
    "NOMBRE_BENEFICIARIO": "nombre_beneficiario", "NUMERO_DOCUMENTO": "numero_documento",
    "FECHA_DOCUMENTO": "fecha_documento", "TIPO_DOCUMENTO": "tipo_documento", "ORDEN_DE_COMPRA": "orden_compra",
    "FECHA_INGRESO": "fecha_ingreso", "FECHA_RECEPCION_CONFORME": "fecha_recepcion_conforme",
    "FECHA_PAGO": "fecha_pago", "MONEDA": "moneda_presupuestaria", "MONEDA_PRESUPUESTARIA": "moneda_presupuestaria",
    "MONTO": "monto_pago", "MONTO_PAGO": "monto_pago", "MONTO_ORIGINAL": "monto_pago_original",
    "DEVENGO": "monto_devengado", "MONTO_DEVENGADO": "monto_devengado", "DEVENGO_ORIGINAL": "monto_devengado_original",
    "RUT_PRINCIPAL": "rut_principal", "NOMBRE_PRINCIPAL": "nombre_principal", "FOLIO": "folio",
    "USUARIO_APROBADOR": "usuario_aprobador", "AGREGADO": "agregado", "BLOQUEO_OC": "bloqueo_oc",
    "CODIGO_BIP": "codigo_bip", "NOMBRE_BIP": "nombre_bip",
    "CODIGO_UBICACION_GEOGRAFICA": "codigo_ubicacion_geografica",
    "NOMBRE_UBICACION_GEOGRAFICA": "nombre_ubicacion_geografica",
    "CODIGO_PROGRAMA_PRESUPUESTARIO": "codigo_programa_presupuestario",
    "NOMBRE_PROGRAMA_PRESUPUESTARIO": "nombre_programa_presupuestario",
    "HONORARIO": "honorario", "PROVEEDOR": "proveedor", "SECTOR": "sector", "REGION": "region",
    "PERSONA": "persona", "INTRAESTADO": "intraestado", "DIAS_DE_PAGO": "dias_de_pago",
    "DIAS_DE_PAGO_CAT": "dias_de_pago_cat", "DEUDA_FLOTANTE": "deuda_flotante",
}

CANONICAL_SOURCE_COLUMNS = list(dict.fromkeys(ALIASES.values()))
DATE_COLS = ["fecha_documento", "fecha_ingreso", "fecha_recepcion_conforme", "fecha_pago"]
AMOUNT_COLS = ["monto_devengado", "monto_pago", "monto_devengado_original", "monto_pago_original"]
INT_COLS = ["periodo", "mes"]


def canonical_column(name: str) -> str:
    key = normalize_text(name).replace(" ", "_")
    key = re.sub(r"_+", "_", key)
    return ALIASES.get(key, key.lower())


def _canonicalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(columns={c: canonical_column(c) for c in df.columns})
    if not renamed.columns.duplicated().any():
        return renamed.copy()
    out = pd.DataFrame(index=renamed.index)
    for name in dict.fromkeys(renamed.columns):
        matching = renamed.loc[:, renamed.columns == name]
        if matching.shape[1] == 1:
            out[name] = matching.iloc[:, 0]
        else:
            work = matching.replace(r"^\s*$", pd.NA, regex=True)
            out[name] = work.bfill(axis=1).iloc[:, 0]
    return out


def _parse_date(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    nonempty = values[values.ne("")]
    if nonempty.empty:
        return pd.to_datetime(series, errors="coerce")
    iso_share = nonempty.str.match(r"^\d{4}-\d{2}-\d{2}(?:[ T].*)?$").mean()
    return pd.to_datetime(
        series,
        errors="coerce",
        yearfirst=True if iso_share >= 0.95 else False,
        dayfirst=False if iso_share >= 0.95 else True,
    )


def normalize_frame(
    df: pd.DataFrame,
    source_url: str = "",
    source_file: str = "",
    source_row_offset: int = 0,
) -> pd.DataFrame:
    out = _canonicalize_columns(df)
    for col in CANONICAL_SOURCE_COLUMNS:
        if col not in out:
            out[col] = pd.NA

    special = set(DATE_COLS + AMOUNT_COLS + INT_COLS)
    for col in list(out.columns):
        if col not in special:
            out[col] = out[col].fillna("").astype(str)
    for col in DATE_COLS:
        out[col] = _parse_date(out[col])
    for col in AMOUNT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Float64")
    for col in INT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")

    out["rut_beneficiario"] = out["beneficiario_source_id"].map(normalize_rut)
    out["rut_beneficiario_normalizado"] = out["rut_beneficiario"]
    out["beneficiario_id_type"] = out["beneficiario_source_id"].map(source_identifier_type)
    out["beneficiario_normalizado"] = out["nombre_beneficiario"].map(normalize_text)
    out["entity_id"] = out["rut_beneficiario"].map(lambda r: f"ENT-RUT-{r}" if r else pd.NA)
    out["recipient_entity_id"] = out["entity_id"]
    out["identity_status"] = out["entity_id"].map(lambda x: "RESOLVED" if pd.notna(x) and str(x) else "UNRESOLVED")
    out["identity_method"] = out["entity_id"].map(lambda x: "RUT_EXACT" if pd.notna(x) and str(x) else "SOURCE_LOCAL_ONLY")
    out["identity_confidence"] = out["entity_id"].map(lambda x: 1.0 if pd.notna(x) and str(x) else 0.0).astype("Float64")
    out["is_provider"] = out["proveedor"].map(flag_is_true).astype(bool)
    out["is_person"] = out["persona"].map(flag_is_true).astype(bool)
    out["is_honorarium"] = out["honorario"].map(flag_is_true).astype(bool)
    out["is_intra_state"] = out["intraestado"].map(flag_is_true).astype(bool)
    out["is_floating_debt"] = out["deuda_flotante"].map(flag_is_true).astype(bool)
    out["is_aggregated"] = out["agregado"].map(flag_is_true).astype(bool)

    out["organization_id"] = [
        organization_id(r.partida, r.capitulo, r.area, r.nombre_area)
        for r in out.itertuples()
    ]
    out["recipient_id"] = [
        recipient_id(raw, name, org)
        for raw, name, org in zip(
            out["beneficiario_source_id"], out["nombre_beneficiario"], out["organization_id"]
        )
    ]
    out["provider_id"] = [
        provider_id(raw, name, flag, org)
        for raw, name, flag, org in zip(
            out["beneficiario_source_id"],
            out["nombre_beneficiario"],
            out["proveedor"],
            out["organization_id"],
        )
    ]

    out["source_system"] = "PRESUPUESTO_ABIERTO"
    out["source_url"] = source_url
    out["source_file"] = source_file
    out["source_row_number"] = pd.Series(
        range(source_row_offset + 1, source_row_offset + len(out) + 1),
        index=out.index,
        dtype="Int64",
    )
    records = out.to_dict("records")
    out["transaction_fingerprint"] = [transaction_fingerprint(r) for r in records]
    records = out.to_dict("records")
    out["transaction_id"] = [transaction_id(r) for r in records]
    out["record_class"] = "SOURCE_FACT"
    return out


def detect_delimiter(path: str | Path) -> str:
    path = Path(path)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(64 * 1024)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;|\t").delimiter
    except csv.Error:
        return ","


def read_normalized(path: str | Path, chunksize: int = 100_000) -> Iterable[pd.DataFrame]:
    path = Path(path)
    compression = "gzip" if path.suffix.lower() == ".gz" else "infer"
    sep = detect_delimiter(path)
    offset = 0
    for chunk in pd.read_csv(
        path,
        compression=compression,
        sep=sep,
        encoding="utf-8-sig",
        dtype=str,
        chunksize=chunksize,
        low_memory=False,
    ):
        normalized = normalize_frame(
            chunk,
            source_file=path.name,
            source_row_offset=offset,
        )
        offset += len(chunk)
        yield normalized


def normalize_to_parquet(
    path: str | Path, output_path: str | Path, chunksize: int = 100_000
) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    rows = 0
    arrow_schema = None
    try:
        for chunk in read_normalized(path, chunksize=chunksize):
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                arrow_schema = table.schema.remove_metadata()
                writer = pq.ParquetWriter(output_path, arrow_schema, compression="zstd")
            table = table.cast(arrow_schema, safe=False).replace_schema_metadata(None)
            writer.write_table(table)
            rows += len(chunk)
    finally:
        if writer is not None:
            writer.close()
    return {
        "path": str(output_path),
        "rows": rows,
        "delimiter": detect_delimiter(path),
    }
