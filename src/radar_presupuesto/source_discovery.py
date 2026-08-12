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


def _probe_file(url: str, headers: dict[str, str], timeout: int) -> dict:
    """Probe a bulk file without downloading it; fall back to a 1-byte GET when HEAD is unsupported."""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True, headers=headers)
        if r.status_code < 400:
            return {
                "available": True,
                "http_status": r.status_code,
                "content_type": r.headers.get("content-type"),
                "content_length": r.headers.get("content-length"),
                "probe_method": "HEAD",
                "final_url": r.url,
            }
        # Some public file endpoints reject HEAD while allowing GET.
        get_headers = dict(headers)
        get_headers["Range"] = "bytes=0-0"
        with requests.get(url, timeout=timeout, allow_redirects=True, headers=get_headers, stream=True) as g:
            available = g.status_code in (200, 206)
            return {
                "available": available,
                "http_status": g.status_code,
                "content_type": g.headers.get("content-type"),
                "content_length": g.headers.get("content-length"),
                "probe_method": "GET_RANGE",
                "final_url": g.url,
            }
    except requests.RequestException as exc:
        return {"available": False, "error": type(exc).__name__, "probe_method": "ERROR"}


def discover_downloads(timeout: int = 30, probe_future: bool = True) -> list[dict]:
    """Discover official annual bulk files and probe predictable annual URLs.

    The portal's download page can lag behind the interactive application, so linked
    years and canonical annual endpoints are audited independently. Missing years are
    recorded as coverage gaps rather than silently ignored.
    """
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
                if not m:
                    continue
                year = int(m.group(1))
                current = found.get(year, {})
                current.update({"year": year, "url": href, "status": "linked", "source_page": r.url})
                found[year] = current
        except requests.RequestException:
            continue

    if probe_future:
        start = min(found) if found else 2016
        current_year = datetime.now().year
        probe_base = PORTALS[1]
        for year in range(start, current_year + 1):
            # Probe even linked files: this turns catalog discovery into an availability audit.
            url = found.get(year, {}).get("url") or f"{probe_base}/data/pagos-{year}.gz"
            probe = _probe_file(url, headers, timeout)
            linked = found.get(year, {}).get("status") == "linked"
            record = found.get(year, {"year": year, "url": url})
            record.update({k: v for k, v in probe.items() if k != "available"})
            if probe.get("available"):
                record["status"] = "linked_available" if linked else "probed_available"
            else:
                record["status"] = "linked_unavailable" if linked else ("probe_error" if "error" in probe else "probed_missing")
            found[year] = record

    return [found[y] for y in sorted(found)]


def write_catalog(path: str | Path) -> list[dict]:
    data = discover_downloads()
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Presupuesto Abierto - DIPRES",
        "downloads": data,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="docs/data/source_catalog.json")
    args = p.parse_args()
    rows = write_catalog(args.output)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
