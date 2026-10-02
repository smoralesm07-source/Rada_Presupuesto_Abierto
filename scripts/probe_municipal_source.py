from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://presupuestoabierto.gob.cl"
PAGES = [
    f"{BASE}/municipalities",
    f"{BASE}/municipalities/9/9118?view=general",
    f"{BASE}/municipalities/09/09121?view=general",
]
OUT = Path("docs/data/municipal_source_probe.json")
UA = "ATLAS-UAF municipal-source-probe/1.1"


def get(url: str) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=45)
    r.raise_for_status()
    return r


def is_js(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".js")


def main() -> None:
    result: dict[str, object] = {"pages": [], "assets": [], "matches": []}
    asset_urls: set[str] = set()

    for page in PAGES:
        try:
            r = get(page)
            soup = BeautifulSoup(r.text, "html.parser")
            result["pages"].append({
                "url": page,
                "status": r.status_code,
                "bytes": len(r.content),
                "html_head": r.text[:1200],
            })
            for tag in soup.find_all(["script", "link"]):
                raw = tag.get("src") or tag.get("href")
                if not raw:
                    continue
                u = urljoin(page, raw)
                if is_js(u):
                    asset_urls.add(u)
        except Exception as exc:
            result["pages"].append({"url": page, "error": repr(exc)})

    # Nuxt may reference lazy chunks from its initial bundles. Crawl newly found
    # same-host JavaScript assets to a bounded depth so the municipality page
    # code is inspected too, not only the bootstrap runtime.
    queue = sorted(asset_urls)
    crawled: set[str] = set()
    while queue and len(crawled) < 150:
        url = queue.pop(0)
        if url in crawled:
            continue
        crawled.add(url)
        item: dict[str, object] = {"url": url}
        try:
            r = get(url)
            text = r.text
            item.update({"status": r.status_code, "bytes": len(r.content)})
            # Absolute and root-relative Nuxt chunks found in source/webpack maps.
            candidates = set(re.findall(r"https?://[^\"'\\\s)]+\.js", text, re.I))
            candidates.update(urljoin(url, x) for x in re.findall(r"/?_nuxt/[A-Za-z0-9._/-]+\.js", text))
            for candidate in sorted(candidates):
                if urlparse(candidate).hostname == "presupuestoabierto.gob.cl" and candidate not in crawled:
                    queue.append(candidate)

            # Preserve compact source excerpts around calls/keywords. The broad
            # endpoint pattern is intentional because the production API may not
            # use an /api/v1 prefix.
            patterns = [
                re.compile(r"https://api\.presupuestoabierto\.gob\.cl[^\"'\\\s,)}]*", re.I),
                re.compile(r"[^\"'\\\s]{0,180}(?:municipalities|municipios|providers|proveedores|documentos|tributari|dte)[^\"'\\\s]{0,260}", re.I),
                re.compile(r"\.(?:get|post)\([^)]{0,500}\)", re.I),
                re.compile(r"\$axios[^;]{0,600}", re.I),
            ]
            seen_values: set[str] = {x["value"] for x in result["matches"]}
            for pat in patterns:
                for m in pat.finditer(text):
                    value = m.group(0)[:700]
                    low = value.lower()
                    if not any(k in low for k in ("municip", "provider", "proveedor", "dte", "tribut", "presupuestoabierto")):
                        continue
                    if value not in seen_values:
                        seen_values.add(value)
                        result["matches"].append({"asset": url, "value": value})
                    if len(result["matches"]) >= 1200:
                        break
                if len(result["matches"]) >= 1200:
                    break
        except Exception as exc:
            item["error"] = repr(exc)
        result["assets"].append(item)
        if len(result["matches"]) >= 1200:
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "pages": len(result["pages"]),
        "assets": len(result["assets"]),
        "matches": len(result["matches"]),
        "output": str(OUT),
    }, ensure_ascii=False))
    for row in result["matches"][:80]:
        print("MATCH", row["value"])


if __name__ == "__main__":
    main()
