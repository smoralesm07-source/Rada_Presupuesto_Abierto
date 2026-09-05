#!/usr/bin/env python3
"""Publish a compact Presupuesto Abierto snapshot to ATLAS Architecture v2.

Uses GitHub Actions OIDC. No Supabase service key is stored in this repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CONTRACT = "ATLAS_BUDGET_EXECUTION_SOURCE_V2"
SOURCE_KEY = "presupuesto_abierto_l12"
AUDIENCE = "atlas-v2-source-ingest"
DEFAULT_ENDPOINT = "https://bzqxvidggykkdouotylg.supabase.co/functions/v1/atlas-v2-source-ingest"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def pick(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {k: row.get(k) for k in keys if k in row}


def top_rows(rows: Any, amount_keys: tuple[str, ...], keys: list[str], limit: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []

    def amount(row: dict[str, Any]) -> float:
        for key in amount_keys:
            try:
                value = row.get(key)
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                pass
        return 0.0

    clean = [r for r in rows if isinstance(r, dict)]
    clean.sort(key=amount, reverse=True)
    return [pick(r, keys) for r in clean[:limit]]


def compact_snapshot(l12: dict[str, Any], parity: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if l12.get("schema") != "PRESUPUESTO_SPEND_VIEW_V2":
        raise ValueError("Unexpected Presupuesto Abierto schema")

    window = l12.get("window") if isinstance(l12.get("window"), dict) else {}
    overview = l12.get("overview") if isinstance(l12.get("overview"), dict) else {}
    monthly = l12.get("monthly") if isinstance(l12.get("monthly"), list) else []
    source = l12.get("source") if isinstance(l12.get("source"), dict) else {}
    assessment = parity.get("assessment") if isinstance(parity.get("assessment"), dict) else {}

    service_keys = [
        "organization_id", "organization_name", "main_region", "amount_l12",
        "transactions_l12", "providers_l12", "provider_amount_l12", "amount_prev12",
        "dominant_subtitle", "variation_l12", "q4_share", "top_provider_id",
        "top_provider_name", "top_provider_share", "provider_hhi", "signal_count",
        "p1_count", "max_priority_score",
    ]
    provider_keys = [
        "provider_id", "provider_name", "supplier_id", "supplier_name", "rut",
        "amount_l12", "amount_clp", "transactions_l12", "buyers_l12", "buyer_count",
        "top_buyer_id", "top_buyer_name", "top_buyer_share", "provider_hhi", "hhi",
        "variation_l12", "signal_count", "p1_count", "max_priority_score",
    ]

    payload: dict[str, Any] = {
        "contract": CONTRACT,
        "source": {
            "system": source.get("system", "PRESUPUESTO_ABIERTO"),
            "publisher": source.get("publisher", "DIPRES"),
            "record_class": source.get("record_class"),
            "organization_grain": source.get("organization_grain"),
            "provider_scope": source.get("provider_scope"),
            "provider_base_rule": source.get("provider_base_rule"),
            "recipient_rut_scope": source.get("recipient_rut_scope"),
            "source_flags_preserved": source.get("source_flags_preserved"),
            "ui_staging_rows": source.get("ui_staging_rows"),
            "source_services": source.get("source_services"),
            "analytic_provider_ids": source.get("analytic_provider_ids"),
            "generated_at": l12.get("generated_at"),
        },
        "window": window,
        "overview": overview,
        "monthly": monthly,
        "top_services": top_rows(
            l12.get("services"),
            ("amount_l12", "amount_clp"),
            service_keys,
            40,
        ),
        "top_providers": top_rows(
            l12.get("providers"),
            ("amount_l12", "amount_clp"),
            provider_keys,
            40,
        ),
        "quality": {
            "source_parity": assessment,
            "semantic_status": "CORRECTED_V3",
            "scope_note": "Ejecución presupuestaria y universo de receptores/proveedores según contrato Presupuesto Abierto corregido; no equivale al universo ChileCompra.",
        },
    }

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    end_month = str(window.get("end_month") or "unknown").replace("-", "")[:8]
    snapshot_id = f"PA-{end_month}-{checksum[:12]}"
    return snapshot_id, payload


def github_oidc_token() -> str:
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not request_url or not request_token:
        raise RuntimeError("GitHub OIDC environment is unavailable")

    sep = "&" if "?" in request_url else "?"
    url = f"{request_url}{sep}audience={urllib.parse.quote(AUDIENCE)}"
    req = urllib.request.Request(url, headers={"Authorization": f"bearer {request_token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    token = str(body.get("value") or "")
    if not token:
        raise RuntimeError("GitHub OIDC token response had no value")
    return token


def publish(endpoint: str, snapshot_id: str, payload: dict[str, Any], generated_at: str) -> dict[str, Any]:
    token = github_oidc_token()
    body = {
        "source_key": SOURCE_KEY,
        "snapshot_id": snapshot_id,
        "contract": CONTRACT,
        "generated_at": generated_at,
        "payload": payload,
        "source_versions": {
            "publisher_contract": CONTRACT,
            "source_schema": "PRESUPUESTO_SPEND_VIEW_V2",
            "source_workflow": "Corrected Spend Data v3",
        },
    }
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "radar-presupuesto-atlas-v2-publisher/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not 200 <= resp.status < 300:
                raise RuntimeError(f"ATLAS v2 ingest HTTP {resp.status}: {result}")
            return result
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"ATLAS v2 ingest HTTP {exc.code}: {detail}") from exc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="docs/data/spend_view_v2.json")
    ap.add_argument("--parity", default="docs/data/source_parity.json")
    ap.add_argument("--endpoint", default=os.environ.get("ATLAS_V2_SOURCE_INGEST_URL", DEFAULT_ENDPOINT))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    l12 = load_json(Path(args.input))
    parity_path = Path(args.parity)
    parity = load_json(parity_path) if parity_path.exists() else {}
    snapshot_id, payload = compact_snapshot(l12, parity)
    generated_at = str(l12.get("generated_at") or "")
    if not generated_at:
        raise ValueError("Source generated_at is missing")

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    print(json.dumps({
        "snapshot_id": snapshot_id,
        "payload_bytes": len(encoded),
        "services": len(payload["top_services"]),
        "providers": len(payload["top_providers"]),
        "months": len(payload["monthly"]),
        "endpoint": args.endpoint,
        "dry_run": args.dry_run,
    }, ensure_ascii=False))

    if args.dry_run:
        return 0

    result = publish(args.endpoint, snapshot_id, payload, generated_at)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ATLAS_V2_PUBLISH_ERROR] {exc}", file=sys.stderr)
        raise
