"""Empaqueta el módulo web en un solo archivo HTML autocontenido.

La página del repositorio carga sus datos por ``fetch``. Para publicarla donde
no hay servidor de archivos (un artifact, un adjunto, una revisión offline) se
incrusta el artefacto analítico y la cartografía dentro del propio HTML.

    PYTHONPATH=src python scripts/build_standalone_page.py \
        --data docs/data/spend_view_demo_v1.json --output dist/ejecucion.html

Con ``--artifact`` se emite sólo el contenido de la página (sin doctype, html,
head ni body), que es el formato que espera el publicador de artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def build(page: Path, data: Path, map_path: Path, title: str | None, artifact: bool) -> str:
    html = page.read_text(encoding="utf-8")
    payload = json.loads(data.read_text(encoding="utf-8"))
    cartography = json.loads(map_path.read_text(encoding="utf-8"))

    embed = (
        "<script>window.__SPEND_VIEW__=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";window.__CHILE_MAP__=" + json.dumps(cartography, ensure_ascii=False, separators=(",", ":"))
        + ";</script>\n"
    )
    marker = "<script>\n(() => {"
    if marker not in html:
        raise SystemExit("No se encontró el script principal de la página")
    html = html.replace(marker, embed + marker, 1)

    if title:
        html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)

    if artifact:
        # El publicador envuelve el contenido en su propio esqueleto.
        html = re.sub(r"^<!doctype html>\s*<html[^>]*>\s*", "", html, flags=re.I)
        html = html.replace("<head>", "", 1).replace("</head>", "", 1)
        html = html.replace("<body>", "", 1)
        html = re.sub(r"</body>\s*</html>\s*$", "", html, flags=re.I)
        html = re.sub(r'<meta charset="utf-8">\s*', "", html, count=1)
        html = re.sub(r'<meta name="viewport"[^>]*>\s*', "", html, count=1)
    return html.strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera el módulo web autocontenido")
    parser.add_argument("--page", default="docs/ejecucion.html")
    parser.add_argument("--data", default="docs/data/spend_view_v1.json")
    parser.add_argument("--map", default="docs/assets/chile_regions.json")
    parser.add_argument("--output", default="dist/ejecucion_standalone.html")
    parser.add_argument("--title", default=None)
    parser.add_argument("--artifact", action="store_true", help="Emite sólo el contenido, sin esqueleto HTML.")
    args = parser.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = build(Path(args.page), Path(args.data), Path(args.map), args.title, args.artifact)
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out} · {len(html)/1024:.0f} KB · datos {Path(args.data).name}")


if __name__ == "__main__":
    main()
