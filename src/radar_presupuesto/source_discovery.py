from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PORTALS = (
    "https://presupuestoabierto.gob.cl",
    "https://api.presupuestoabierto.gob.cl",
)
ABOUT_DATA_PATH = "/about-data"
DATA_PATTERN = re.compile(r"/data/pagos-(\d{4})\.gz$", re.I)


def discover_downloads(timeout: int = 30, probe_future: bool = True) -> list[dict]:
    """Discover official annual bulk files and probe predictable annual URLs."""
    found: dict[int, dict] = {}
    headers = {"User-Agent": "RadarPresupuestoAbierto/0.1 (+public OSINT research)"}
    for base in PORTALS:
        try:
            r = requests.get(urljoin(base, ABOUT_DATA_PATH), timeout=timeout, headers=headers)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = urljoin(base, a["href"])
                m = DATA_PATTERN.search(href)
                if m:
                    year = int(m.group(1))
                    found[year] = {"year": year, "url": href, "status": "linked", "source_page": r.url}
        except requests.RequestException:
            continue
    if probe_future:
        start = min(found) if found else 2016
        current = datetime.now().year
        probe_base = PORTALS[1]
        for year in range(start, current + 1):
            if year in found:
                continue
            url = f"{probe_base}/data/pagos-{year}.gz"
            try:
                r = requests.head(url, timeout=timeout, allow_redirects=True, headers=headers)
                ok = r.status_code < 400
                found[year] = {"year": year,"url": url,"status": "probed_available" if ok else "probed_missing","http_status": r.status_code,"content_type": r.headers.get("content-type"),"content_length": r.headers.get("content-length")}
            except requests.RequestException as exc:
                found[year] = {"year": year, "url": url, "status": "probe_error", "error": type(exc).__name__}
    return [found[y] for y in sorted(found)]


def write_catalog(path: str | Path) -> list[dict]:
    data = discover_downloads()
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),"source": "Presupuesto Abierto - DIPRES","downloads": data}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--output", default="docs/data/source_catalog.json"); args = p.parse_args()
    rows = write_catalog(args.output); print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
