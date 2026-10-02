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
UA = "ATLAS-UAF municipal-source-probe/1.3"


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
                "html": r.text,
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

    queue = sorted(asset_urls)
    crawled: set[str] = set()
    while queue and len(crawled) < 180:
        url = queue.pop(0)
        if url in crawled:
            continue
        crawled.add(url)
        item: dict[str, object] = {"url": url}
        try:
            r = get(url)
            text = r.text
            item.update({"status": r.status_code, "bytes": len(r.content)})
            if len(text) <= 12000:
                item["text"] = text

            candidates = set(re.findall(r"https?://[^\"'\\\s)]+\.js", text, re.I))
            candidates.update(urljoin(url, x) for x in re.findall(r"/?_nuxt/[A-Za-z0-9._/-]+\.js", text))
            for filename in re.findall(r"(?<![A-Za-z0-9])([0-9a-f]{6,}\.js)(?![A-Za-z0-9])", text, re.I):
                candidates.add(f"{BASE}/_nuxt/{filename}")
            for filename in re.findall(r"[\"']([0-9]+\.[0-9a-f]{6,}\.js)[\"']", text, re.I):
                candidates.add(f"{BASE}/_nuxt/{filename}")

            # Parse the common webpack form: ({chunkId:chunkName}[e]||e)+'.'+{chunkId:hash}[e]+'.js'.
            name_maps = re.findall(r"\{((?:\d+:[\"'][^\"']+[\"'],?){2,})\}", text)
            for raw_map in name_maps:
                for _, value in re.findall(r"(\d+):[\"']([^\"']+)[\"']", raw_map):
                    if re.fullmatch(r"[0-9a-f]{6,}", value, re.I):
                        candidates.add(f"{BASE}/_nuxt/{value}.js")

            for candidate in sorted(candidates):
                if urlparse(candidate).hostname == "presupuestoabierto.gob.cl" and candidate not in crawled and candidate not in queue:
                    queue.append(candidate)

            patterns = [
                re.compile(r"https://api\.presupuestoabierto\.gob\.cl[^\"'\\\s,)}]*", re.I),
                re.compile(r"[^\"'\\\s]{0,220}(?:municipalities|municipios|providers|proveedores|documents|documentos|tributari|dte)[^\"'\\\s]{0,340}", re.I),
                re.compile(r"\.(?:get|post)\([^)]{0,700}\)", re.I),
                re.compile(r"\$axios[^;]{0,800}", re.I),
            ]
            seen_values: set[str] = {x["value"] for x in result["matches"]}
            for pat in patterns:
                for m in pat.finditer(text):
                    value = m.group(0)[:900]
                    low = value.lower()
                    if not any(k in low for k in ("municip", "provider", "proveedor", "document", "dte", "tribut", "presupuestoabierto")):
                        continue
                    if value not in seen_values:
                        seen_values.add(value)
                        result["matches"].append({"asset": url, "value": value})
                    if len(result["matches"]) >= 1600:
                        break
                if len(result["matches"]) >= 1600:
                    break
        except Exception as exc:
            item["error"] = repr(exc)
        result["assets"].append(item)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "pages": len(result["pages"]),
        "assets": len(result["assets"]),
        "matches": len(result["matches"]),
        "output": str(OUT),
    }, ensure_ascii=False))
    for row in result["matches"][:150]:
        print("MATCH", row["asset"], row["value"])


if __name__ == "__main__":
    main()
