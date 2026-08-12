from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


def download(url: str, dest: str | Path, timeout: int = 120) -> dict:
    dest = Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part"); h = hashlib.sha256(); size = 0
    headers = {"User-Agent": "RadarPresupuestoAbierto/0.1 (+public OSINT research)"}
    with requests.get(url, stream=True, timeout=timeout, headers=headers) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk: continue
                f.write(chunk); h.update(chunk); size += len(chunk)
    tmp.replace(dest)
    meta = {"url": url,"path": str(dest),"sha256": h.hexdigest(),"bytes": size,"downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    dest.with_suffix(dest.suffix + ".metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
