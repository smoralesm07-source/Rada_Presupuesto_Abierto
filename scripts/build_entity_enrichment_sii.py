from __future__ import annotations

import argparse
import fnmatch
import json
import math
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

from radar_sii.normalize import read_chunks, normalize_names, normalize_activities, normalize_company_year


def canon_rut(value: object) -> str:
    s = ''.join(ch for ch in str(value or '').upper() if ch.isdigit() or ch == 'K')
    if len(s) < 2:
        return ''
    return f'{s[:-1]}-{s[-1]}'


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, 'item'):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'Radar-Presupuesto-SII-Enrichment/1.1'})
    with urllib.request.urlopen(req, timeout=180) as r, path.open('wb') as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def _extract(zip_path: Path, patterns: list[str], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            base = Path(name).name
            if any(fnmatch.fnmatch(base, p) for p in patterns):
                target = out_dir / base
                with z.open(name) as src, target.open('wb') as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                paths.append(target)
    if not paths:
        raise RuntimeError(f'No se encontraron miembros {patterns} en {zip_path.name}')
    return paths


def _target_ruts(spend_path: Path) -> set[str]:
    d = json.loads(spend_path.read_text(encoding='utf-8'))
    out = {canon_rut(p.get('rut')) for p in d.get('providers', [])}
    return {x for x in out if x}


def _selected_rows(paths: list[Path], normalizer, targets: set[str], chunksize: int) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        for chunk in read_chunks(path, chunksize=chunksize):
            norm = normalizer(chunk)
            if 'rut' not in norm.columns:
                continue
            hit = norm[norm['rut'].isin(targets)]
            if not hit.empty:
                rows.extend(hit.to_dict('records'))
    return rows


def _mark(signal_type: str, severity: str, year: object, why: str) -> dict:
    return {'signal_type': signal_type, 'severity': severity, 'year': _clean(year), 'why': why, 'source': 'RADAR_SII_RULE_CATALOG'}


def build(spend_path: str, catalog_path: str, output: str, workdir: str) -> dict:
    spend = Path(spend_path)
    catalog = json.loads(Path(catalog_path).read_text(encoding='utf-8'))
    targets = _target_ruts(spend)
    if not targets:
        raise RuntimeError('No hay RUT válidos de proveedores en spend_view_v2.json')

    by_id = {x['id']: x for x in catalog}
    required = ['sii_names_current', 'sii_activities_current', 'sii_company_year']
    root = Path(workdir)
    extracted: dict[str, list[Path]] = {}
    for source_id in required:
        src = by_id[source_id]
        zip_path = root / f'{source_id}.zip'
        _download(src['url'], zip_path)
        extracted[source_id] = _extract(zip_path, src['member_globs'], root / source_id)
        print('[OK] fuente', source_id, 'miembros', len(extracted[source_id]))

    name_rows = _selected_rows(extracted['sii_names_current'], normalize_names, targets, chunksize=150_000)
    activity_rows = _selected_rows(extracted['sii_activities_current'], normalize_activities, targets, chunksize=150_000)
    year_rows = _selected_rows(extracted['sii_company_year'], normalize_company_year, targets, chunksize=100_000)

    names: dict[str, dict] = {}
    for r in name_rows:
        rut = canon_rut(r.get('rut'))
        if not rut:
            continue
        names[rut] = {
            'rut': rut,
            'legal_name': _clean(r.get('legal_name')),
            'tax_status': _clean(r.get('current_status')),
            'start_date': _clean(r.get('activity_start_date')),
            'termination_date': _clean(r.get('termination_date')),
            'taxpayer_subtype_code': _clean(r.get('taxpayer_subtype_code')),
        }

    activities: dict[str, list[dict]] = defaultdict(list)
    seen_activities: dict[str, set[tuple]] = defaultdict(set)
    for r in activity_rows:
        rut = canon_rut(r.get('rut'))
        if not rut:
            continue
        item = {
            'codigo': _clean(r.get('activity_code')),
            'glosa': _clean(r.get('activity_name')),
            'estado': _clean(r.get('activity_status')),
            'categoria_tributaria': _clean(r.get('activity_category')),
            'afecta_iva': _clean(r.get('vat_affected')),
            'fecha_registro': _clean(r.get('activity_registration_date')),
        }
        key = tuple(item.get(k) for k in ('codigo', 'glosa', 'estado', 'categoria_tributaria'))
        if key not in seen_activities[rut]:
            seen_activities[rut].add(key)
            activities[rut].append(item)

    history: dict[str, list[dict]] = defaultdict(list)
    for r in year_rows:
        rut = canon_rut(r.get('rut'))
        year = _clean(r.get('commercial_year'))
        if not rut or year is None:
            continue
        history[rut].append({
            'commercial_year': int(year),
            'sales_band_code': _clean(r.get('sales_band_code')),
            'sales_band': _clean(r.get('sales_band')),
            'workers': _clean(r.get('workers')),
            'main_region': _clean(r.get('region')),
            'main_activity': _clean(r.get('main_activity')),
            'taxpayer_type': _clean(r.get('taxpayer_type')),
            'taxpayer_subtype': _clean(r.get('taxpayer_subtype')),
            'termination_date': _clean(r.get('termination_date')),
            'negative_equity_band': _clean(r.get('negative_equity_band')),
        })
    for rut in history:
        history[rut].sort(key=lambda x: int(x.get('commercial_year') or 0))

    entities: dict[str, dict] = {}
    mark_count = 0
    for rut in sorted(targets):
        if rut not in names and rut not in activities and rut not in history:
            continue
        n = names.get(rut, {})
        hist = history.get(rut, [])
        y = hist[-1] if hist else {}
        prev = hist[-2] if len(hist) >= 2 else {}
        code = y.get('sales_band_code')
        marks: list[dict] = []

        if code is not None and prev.get('sales_band_code') is not None:
            try:
                delta = int(code) - int(prev['sales_band_code'])
                if delta >= 3:
                    marks.append(_mark('SALES_BAND_JUMP', 'MEDIUM', y.get('commercial_year'), f'El tramo SII de ventas aumentó {delta} niveles respecto del año anterior con información.'))
            except Exception:
                pass
        workers = y.get('workers')
        try:
            if code is not None and int(code) >= 10 and workers is not None and int(workers) <= 2:
                marks.append(_mark('HIGH_SALES_LOW_WORKFORCE', 'MEDIUM', y.get('commercial_year'), f'Tramo SII de gran empresa (nivel {int(code)}) con {int(workers)} trabajadores dependientes informados.'))
        except Exception:
            pass
        start = n.get('start_date')
        try:
            age = int(y.get('commercial_year')) - int(str(start)[:4]) if start and y.get('commercial_year') else None
            if code is not None and int(code) >= 10 and age is not None and 0 <= age <= 2:
                marks.append(_mark('RECENT_START_HIGH_SALES', 'MEDIUM', y.get('commercial_year'), f'Empresa con hasta {age} años desde el inicio publicado y tramo SII de gran empresa.'))
        except Exception:
            pass
        try:
            pw = prev.get('workers')
            pc = prev.get('sales_band_code')
            if pw is not None and int(pw) >= 10 and workers is not None and int(workers) <= int(pw) * .20 and code is not None and pc is not None and int(code) > 1 and int(pc) > 1 and int(code) >= int(pc):
                marks.append(_mark('WORKFORCE_DROP_STABLE_SALES', 'MEDIUM', y.get('commercial_year'), 'La dotación informada cayó al 20% o menos mientras el tramo de ventas no disminuyó.'))
        except Exception:
            pass
        if y.get('main_activity') and prev.get('main_activity') and str(y['main_activity']).strip() != str(prev['main_activity']).strip():
            marks.append(_mark('MAIN_ACTIVITY_CHANGE', 'LOW', y.get('commercial_year'), 'La actividad económica principal cambió respecto del año comercial anterior.'))
        if y.get('main_region') and prev.get('main_region') and str(y['main_region']).strip() != str(prev['main_region']).strip():
            marks.append(_mark('REGION_CHANGE', 'LOW', y.get('commercial_year'), 'La región informada para la empresa cambió respecto del año comercial anterior.'))
        if len(activities.get(rut, [])) >= 6:
            marks.append(_mark('ACTIVITY_BREADTH', 'LOW', 'CURRENT', f'Registra {len(activities[rut])} actividades económicas vigentes/publicadas.'))
        if n.get('tax_status') == 'ACTIVE_AS_PUBLISHED' and any(str(h.get('termination_date') or '').strip() for h in hist):
            marks.append(_mark('REACTIVATION_PATTERN', 'LOW', 'CURRENT', 'Existe término de giro en un registro histórico y la nómina vigente actual aparece sin término de giro.'))
        neg = str(y.get('negative_equity_band') or '').strip().lower()
        try:
            if code is not None and int(code) >= 10 and neg and neg not in {'nan','0','sin informacion','sin información'}:
                marks.append(_mark('HIGH_SALES_NEGATIVE_EQUITY', 'MEDIUM', y.get('commercial_year'), 'Tramo SII de gran empresa coexistiendo con tramo de capital propio tributario negativo informado.'))
        except Exception:
            pass

        mark_count += len(marks)
        entities[rut] = {
            'rut': rut,
            'entity_id': f'ENT-RUT-{rut}',
            **n,
            'acteco': activities.get(rut, []),
            **y,
            'sales_band_label': (f'Tramo SII {code}' if code is not None else None),
            'marks': marks,
            'history_available_years': [h['commercial_year'] for h in hist],
        }

    payload = {
        'schema': 'PRESUPUESTO_ENTITY_ENRICHMENT_V1',
        'generated_at': pd.Timestamp.utcnow().isoformat(),
        'sources': {
            'RADAR_SII': {
                'status': 'SELECTIVE_RUT_EXTRACT_READY',
                'key': 'ENT-RUT-{RUT_NORMALIZADO}',
                'matched_entities': len(entities),
                'target_ruts': len(targets),
                'marks': mark_count,
                'published_updates': {k: by_id[k].get('published_update') for k in required},
                'coverage_note': 'Estado registral y ACTECO: snapshot 2026-05. Ventas/trabajadores: último año comercial publicado dentro de 2020-2024. Marcas reproducen reglas del catálogo Radar SII cuando los campos selectivos son suficientes.'
            },
            'RADAR_UAF': {'status': 'LIVE_PUBLIC_PAGE_LOOKUP', 'path': '/Radar_UAF/data/dashboard.json', 'key': 'rut'},
            'RADAR_SANCIONES': {'status': 'LIVE_PUBLIC_PAGE_LOOKUP', 'path': '/Radar_sanciones/data/entities.json', 'key': 'rut'},
        },
        'entities': entities,
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=str), encoding='utf-8')
    print('[OK] enrichment', {'targets': len(targets), 'matched': len(entities), 'names': len(name_rows), 'activities': len(activity_rows), 'company_year': len(year_rows), 'marks': mark_count})
    return payload


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--spend', default='docs/data/spend_view_v2.json')
    p.add_argument('--catalog', default='external/radar-sii/docs/data/source_catalog.json')
    p.add_argument('--output', default='docs/data/entity_enrichment_v1.json')
    p.add_argument('--workdir', default='/tmp/radar-sii-enrichment')
    a = p.parse_args()
    build(a.spend, a.catalog, a.output, a.workdir)


if __name__ == '__main__':
    main()
