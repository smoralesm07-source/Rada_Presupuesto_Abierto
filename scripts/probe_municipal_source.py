from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://presupuestoabierto.gob.cl"
PAGES = [
    f"{BASE}/municipalities",
    f"{BASE}/municipalities/9/9118?view=general",
    f"{BASE}/municipalities/09/09121?view=general",
]
OUT = Path("docs/data/municipal_source_probe.json")
UA = "ATLAS-UAF municipal-source-probe/1.0"


def get(url: str) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=45)
    r.raise_for_status()
    return r


def main() -> None:
    result: dict[str, object] = {"pages": [], "scripts": [], "matches": []}
    script_urls: set[str] = set()

    for page in PAGES:
        try:
            r = get(page)
            result["pages"].append({"url": page, "status": r.status_code, "bytes": len(r.content)})
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all("script", src=True):
                script_urls.add(urljoin(page, tag["src"]))
        except Exception as exc:
            result["pages"].append({"url": page, "error": repr(exc)})

    patterns = [
        re.compile(r"https?://[^\"'\\\s]+", re.I),
        re.compile(r"/api/v1/[^\"'\\\s]+", re.I),
        re.compile(r"[^\"'\\\s]{0,140}(?:municip|municipal|dte|tributari)[^\"'\\\s]{0,220}", re.I),
    ]
    seen: set[str] = set()
    for url in sorted(script_urls):
        item: dict[str, object] = {"url": url}
        try:
            r = get(url)
            text = r.text
            item.update({"status": r.status_code, "bytes": len(r.content)})
            for pat in patterns:
                for m in pat.finditer(text):
                    value = m.group(0)
                    if any(k in value.lower() for k in ("api", "municip", "dte", "tribut")):
                        value = value[:500]
                        if value not in seen:
                            seen.add(value)
                            result["matches"].append({"script": url, "value": value})
                            if len(result["matches"]) >= 500:
                                break
                if len(result["matches"]) >= 500:
                    break
        except Exception as exc:
            item["error"] = repr(exc)
        result["scripts"].append(item)
        if len(result["matches"]) >= 500:
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "pages": len(result["pages"]),
        "scripts": len(result["scripts"]),
        "matches": len(result["matches"]),
        "output": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
