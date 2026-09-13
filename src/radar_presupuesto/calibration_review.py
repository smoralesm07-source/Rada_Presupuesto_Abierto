from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = 'RIGP-CALIBRATION-REVIEW-v1'


def _read(path: str, default: dict | None = None) -> dict:
    p = Path(path)
    if not p.exists():
        return dict(default or {})
    return json.loads(p.read_text(encoding='utf-8'))


def _ratio(num: int | float, den: int | float) -> float:
    return round(float(num) / float(den), 4) if den else 0.0


def review_payloads(
    operational: dict,
    signal_health: dict,
    findings: dict,
    procurement: dict,
    entity_context: dict,
) -> dict:
    signals = signal_health.get('signals') or []
    statuses = {str(x.get('signal_type')): str(x.get('status')) for x in signals}
    counts = {str(x.get('signal_type')): int(x.get('signal_count') or 0) for x in signals}
    dominant = [s for s, status in statuses.items() if status == 'DOMINANT_REVIEW']
    zero = [s for s, status in statuses.items() if status == 'EXPERIMENTAL_ZERO']
    low = [s for s, status in statuses.items() if status == 'LOW_VOLUME']
    active = [s for s, status in statuses.items() if status == 'ACTIVE']
    nonzero = [s for s, n in counts.items() if n > 0]

    relation_count = len(findings.get('relation_findings') or [])
    context = findings.get('context_coverage') or operational.get('finding_context_coverage') or {}
    peer_count = int(context.get('relations_with_peer_context') or 0)
    pattern_count = int(context.get('relations_with_primary_pattern') or 0)

    procurement_cov = procurement.get('coverage') or operational.get('procurement_context') or {}
    proc_requested = int(procurement_cov.get('findings_requested') or 0)
    proc_oc = int(procurement_cov.get('findings_with_purchase_order') or 0)

    entity_cov = entity_context.get('coverage') or {}
    providers = int(entity_cov.get('providers_published') or 0)
    valid_rut = int(entity_cov.get('providers_with_valid_rut') or 0)
    sii_matched = int(entity_cov.get('providers_matched_in_sii') or 0)

    window = operational.get('analysis_window') or findings.get('analysis_window') or {}
    year_count = int(window.get('year_count') or 0)

    publication = findings.get('publication_selection') or operational.get('publication') or {}
    max_rows = int(publication.get('max_rows') or 600)
    publication_method = publication.get('method')

    gates = {
        'historical_window_min_5_years': year_count >= 5,
        'bounded_publication': relation_count <= max_rows,
        'priority_pattern_peer_separated': bool(findings.get('interpretation_contract')),
        'signal_diversity_selection': publication_method == 'priority_with_signal_diversity_reserve',
        'at_least_two_nonzero_signal_types': len(nonzero) >= 2,
    }

    coverage = {
        'relations_published': relation_count,
        'peer_context_relations': peer_count,
        'peer_context_ratio': _ratio(peer_count, relation_count),
        'primary_pattern_relations': pattern_count,
        'primary_pattern_ratio': _ratio(pattern_count, relation_count),
        'procurement_findings_requested': proc_requested,
        'findings_with_purchase_order': proc_oc,
        'purchase_order_ratio': _ratio(proc_oc, proc_requested),
        'providers_published': providers,
        'providers_with_valid_rut': valid_rut,
        'valid_rut_ratio': _ratio(valid_rut, providers),
        'providers_matched_in_sii': sii_matched,
        'sii_match_ratio_over_valid_rut': _ratio(sii_matched, valid_rut),
    }

    recommendations: list[dict] = []
    if dominant:
        recommendations.append({
            'priority': 'ALTA',
            'topic': 'DOMINANCIA_DE_SENAL',
            'signals': dominant,
            'action': (
                'Revisar umbral, población comparable y regla de publicación de las señales dominantes. '
                'No modificar pesos automáticamente ni reducir el score sólo para equilibrar conteos.'
            ),
        })
    if zero:
        recommendations.append({
            'priority': 'MEDIA',
            'topic': 'SENALES_SIN_PRODUCCION',
            'signals': zero,
            'action': (
                'Mantener estas señales como experimentales. Verificar disponibilidad de campos, ventana histórica y '
                'sensibilidad del detector antes de devolverlas al flujo operativo.'
            ),
        })
    if low:
        recommendations.append({
            'priority': 'MEDIA',
            'topic': 'BAJO_VOLUMEN',
            'signals': low,
            'action': (
                'Revisar sensibilidad con una muestra de casos verdaderos y explicaciones normales. '
                'Bajo volumen no justifica por sí mismo bajar umbrales.'
            ),
        })
    if coverage['peer_context_ratio'] < 0.70:
        recommendations.append({
            'priority': 'ALTA',
            'topic': 'COBERTURA_GRUPOS_DE_PARES',
            'action': (
                'Revisar grupos con pocos proveedores y llaves organismo-año-subtítulo-ítem. '
                'No usar ausencia de pares como señal adversa.'
            ),
        })
    if proc_requested and coverage['purchase_order_ratio'] < 0.50:
        recommendations.append({
            'priority': 'ALTA',
            'topic': 'PUENTE_MERCADO_PUBLICO',
            'action': (
                'Priorizar el enlace Presupuesto Abierto → orden de compra → Mercado Público para ampliar evidencia '
                'contractual. La ausencia de OC en el registro presupuestario no es una irregularidad.'
            ),
        })
    if providers and coverage['valid_rut_ratio'] < 0.70:
        recommendations.append({
            'priority': 'ALTA',
            'topic': 'RESOLUCION_DE_IDENTIDAD',
            'action': (
                'Mejorar resolución determinística de identidad antes de ampliar OSINT/SII. '
                'No resolver automáticamente RUT por similitud de nombre.'
            ),
        })
    if valid_rut and coverage['sii_match_ratio_over_valid_rut'] < 0.80:
        recommendations.append({
            'priority': 'MEDIA',
            'topic': 'COBERTURA_SII',
            'action': (
                'Revisar snapshot y catálogo SII para los RUT explícitamente resueltos que no obtuvieron contexto. '
                'Mantener la ausencia como brecha de cobertura, no como señal de riesgo.'
            ),
        })

    hard_fail = not all([
        gates['historical_window_min_5_years'],
        gates['bounded_publication'],
        gates['priority_pattern_peer_separated'],
        gates['signal_diversity_selection'],
        gates['at_least_two_nonzero_signal_types'],
    ])
    if hard_fail:
        readiness = 'REQUIRES_METHOD_REVIEW'
    elif recommendations:
        readiness = 'READY_WITH_COVERAGE_GAPS'
    else:
        readiness = 'READY_FOR_ANALYST_REVIEW'

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'schema': SCHEMA,
        'readiness': readiness,
        'automatic_threshold_changes': False,
        'analysis_window': window,
        'quality_gates': gates,
        'signal_health': {
            'total_signals': int(signal_health.get('total_signals') or 0),
            'active': active,
            'low_volume': low,
            'experimental_zero': zero,
            'dominant_review': dominant,
            'counts': counts,
        },
        'coverage': coverage,
        'recommendations': recommendations,
        'method_note': (
            'Este producto decide qué calibraciones conviene estudiar; no cambia umbrales, pesos ni clasifica delitos. '
            'Cualquier ajuste requiere revisión humana y contraste con casos explicados y casos que ameritaron profundización.'
        ),
    }


def build_calibration_review(
    operational_path: str = 'docs/data/operational_bundle.json',
    signal_health_path: str = 'docs/data/signal_health.json',
    findings_path: str = 'docs/data/investigative_findings.json',
    procurement_path: str = 'docs/data/procurement_context.json',
    entity_context_path: str = 'docs/data/case_entity_context.json',
    output_path: str = 'docs/data/calibration_review.json',
) -> dict:
    result = review_payloads(
        _read(operational_path),
        _read(signal_health_path),
        _read(findings_path),
        _read(procurement_path),
        _read(entity_context_path),
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    result = build_calibration_review()
    print('[RIGP calibration]', result['readiness'])
    print('[RIGP gates]', result['quality_gates'])
    print('[RIGP signal health]', result['signal_health'])
    print('[RIGP coverage]', result['coverage'])
    for row in result['recommendations']:
        print('[RIGP recommendation]', row['priority'], row['topic'])


if __name__ == '__main__':
    main()
