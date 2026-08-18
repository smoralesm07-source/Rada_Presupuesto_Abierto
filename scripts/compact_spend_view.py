from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def _strict_json(value):
    """Recursively replace non-finite numeric values with JSON null."""
    if isinstance(value, dict):
        return {str(k): _strict_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strict_json(v) for v in value]
    if isinstance(value, tuple):
        return [_strict_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def compact(input_path: str, output_path: str, max_flows: int = 3200, per_service: int = 2) -> dict:
    src = Path(input_path)
    # Python accepts NaN in legacy JSON; sanitize it before re-publishing strict JSON.
    data = json.loads(src.read_text(encoding="utf-8"))
    flows = list(data.get("flows") or [])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in flows:
        grouped[str(row.get("organization_id") or "")].append(row)

    keep: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for rows in grouped.values():
        rows.sort(key=lambda r: float(r.get("amount_clp") or 0), reverse=True)
        for row in rows[:per_service]:
            key = (str(row.get("organization_id") or ""), str(row.get("provider_id") or ""))
            if key not in seen:
                seen.add(key)
                keep.append(row)

    if len(keep) < max_flows:
        remaining = sorted(flows, key=lambda r: float(r.get("amount_clp") or 0), reverse=True)
        for row in remaining:
            if len(keep) >= max_flows:
                break
            key = (str(row.get("organization_id") or ""), str(row.get("provider_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            keep.append(row)

    provider_ids = {str(r.get("provider_id") or "") for r in keep if r.get("provider_id")}
    profiles = {str(p.get("provider_id") or ""): p for p in (data.get("providers") or [])}
    providers: list[dict] = []
    flow_name: dict[str, tuple[str, str]] = {}
    for row in keep:
        pid = str(row.get("provider_id") or "")
        if pid and pid not in flow_name:
            flow_name[pid] = (str(row.get("provider_name") or pid), str(row.get("rut") or ""))
    for pid in sorted(provider_ids):
        if pid in profiles:
            providers.append(profiles[pid])
        else:
            name, rut = flow_name.get(pid, (pid, ""))
            providers.append({
                "provider_id": pid,
                "provider_name": name,
                "rut": rut,
                "amount_l12": 0,
                "transactions_l12": 0,
                "organizations_l12": 0,
                "months_active": 0,
                "monthly": [],
                "signal_count": 0,
                "p1_count": 0,
            })

    data["flows"] = keep
    data["providers"] = providers
    data.setdefault("source", {})["ui_payload"] = "COMPACT_INITIAL_VIEW"
    data["source"]["ui_note"] = (
        "Todos los servicios L12 permanecen disponibles; el payload inicial conserva "
        "las relaciones principales por servicio para acelerar GitHub Pages."
    )
    data["published"] = {
        **(data.get("published") or {}),
        "services": len(data.get("services") or []),
        "providers": len(providers),
        "flows": len(keep),
        "flows_per_service_initial": per_service,
        "initial_flow_cap": max_flows,
    }

    data = _strict_json(data)
    out = Path(output_path)
    out.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    # Verify with a strict parser policy before publishing.
    json.loads(
        out.read_text(encoding="utf-8"),
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"non-finite JSON constant: {x}")),
    )
    return {
        "bytes": out.stat().st_size,
        "services": len(data.get("services") or []),
        "providers": len(providers),
        "flows": len(keep),
        "strict_json": True,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="docs/data/spend_view_v2.json")
    p.add_argument("--output", default="docs/data/spend_view_v2.json")
    p.add_argument("--max-flows", type=int, default=3200)
    p.add_argument("--per-service", type=int, default=2)
    args = p.parse_args()
    print(json.dumps(compact(args.input, args.output, args.max_flows, args.per_service), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
