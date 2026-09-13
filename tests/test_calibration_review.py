from radar_presupuesto.calibration_review import review_payloads


def test_review_separates_method_health_from_allegations():
    operational = {'analysis_window': {'years': [2020, 2021, 2022, 2023, 2024, 2025], 'year_count': 6}}
    health = {
        'total_signals': 100,
        'signals': [
            {'signal_type': 'AMOUNT_OUTLIER', 'status': 'DOMINANT_REVIEW', 'signal_count': 90},
            {'signal_type': 'PROVIDER_CONCENTRATION', 'status': 'ACTIVE', 'signal_count': 10},
            {'signal_type': 'PAYMENT_DELAY_OUTLIER', 'status': 'EXPERIMENTAL_ZERO', 'signal_count': 0},
        ],
    }
    findings = {
        'relation_findings': [{} for _ in range(10)],
        'publication_selection': {'method': 'priority_with_signal_diversity_reserve', 'max_rows': 600},
        'interpretation_contract': {'separation_rule': 'separado'},
        'context_coverage': {'relations_with_peer_context': 8, 'relations_with_primary_pattern': 7},
    }
    procurement = {'coverage': {'findings_requested': 10, 'findings_with_purchase_order': 6}}
    entities = {'coverage': {
        'providers_published': 8,
        'providers_with_valid_rut': 7,
        'providers_matched_in_sii': 6,
    }}

    out = review_payloads(operational, health, findings, procurement, entities)
    assert out['schema'] == 'RIGP-CALIBRATION-REVIEW-v1'
    assert out['automatic_threshold_changes'] is False
    assert out['quality_gates']['historical_window_min_5_years'] is True
    assert out['coverage']['peer_context_ratio'] == 0.8
    assert out['readiness'] == 'READY_WITH_COVERAGE_GAPS'
    topics = {x['topic'] for x in out['recommendations']}
    assert 'DOMINANCIA_DE_SENAL' in topics
    assert 'SENALES_SIN_PRODUCCION' in topics


def test_review_blocks_short_window():
    out = review_payloads(
        {'analysis_window': {'years': [2024, 2025, 2026], 'year_count': 3}},
        {'total_signals': 2, 'signals': [
            {'signal_type': 'A', 'status': 'ACTIVE', 'signal_count': 1},
            {'signal_type': 'B', 'status': 'ACTIVE', 'signal_count': 1},
        ]},
        {
            'relation_findings': [{}],
            'publication_selection': {'method': 'priority_with_signal_diversity_reserve', 'max_rows': 600},
            'interpretation_contract': {'separation_rule': 'separado'},
        },
        {'coverage': {}},
        {'coverage': {}},
    )
    assert out['readiness'] == 'REQUIRES_METHOD_REVIEW'
    assert out['quality_gates']['historical_window_min_5_years'] is False


def test_review_reports_marketplace_ticket_gap_without_changing_method_gates():
    operational = {'analysis_window': {'years': [2020, 2021, 2022, 2023, 2024], 'year_count': 5}}
    health = {'total_signals': 2, 'signals': [
        {'signal_type': 'A', 'status': 'ACTIVE', 'signal_count': 1},
        {'signal_type': 'B', 'status': 'ACTIVE', 'signal_count': 1},
    ]}
    findings = {
        'relation_findings': [{} for _ in range(4)],
        'publication_selection': {'method': 'priority_with_signal_diversity_reserve', 'max_rows': 600},
        'interpretation_contract': {'separation_rule': 'separado'},
        'context_coverage': {'relations_with_peer_context': 4, 'relations_with_primary_pattern': 4},
    }
    procurement = {'coverage': {'findings_requested': 4, 'findings_with_purchase_order': 4}}
    entities = {'coverage': {
        'providers_published': 4,
        'providers_with_valid_rut': 4,
        'providers_matched_in_sii': 4,
    }}
    mercado = {
        'status': 'AWAITING_TICKET',
        'coverage': {'target_orders': 4, 'api_requests_attempted': 0, 'orders_resolved': 0},
    }
    out = review_payloads(operational, health, findings, procurement, entities, mercado)
    assert all(out['quality_gates'].values())
    assert out['coverage']['mercado_publico_status'] == 'AWAITING_TICKET'
    assert out['readiness'] == 'READY_WITH_COVERAGE_GAPS'
    assert 'API_MERCADO_PUBLICO_PENDIENTE' in {x['topic'] for x in out['recommendations']}


def test_review_flags_low_marketplace_resolution_and_identity_candidates():
    base = review_payloads(
        {'analysis_window': {'years': [2020, 2021, 2022, 2023, 2024], 'year_count': 5}},
        {'total_signals': 2, 'signals': [
            {'signal_type': 'A', 'status': 'ACTIVE', 'signal_count': 1},
            {'signal_type': 'B', 'status': 'ACTIVE', 'signal_count': 1},
        ]},
        {
            'relation_findings': [{} for _ in range(4)],
            'publication_selection': {'method': 'priority_with_signal_diversity_reserve', 'max_rows': 600},
            'interpretation_contract': {'separation_rule': 'separado'},
            'context_coverage': {'relations_with_peer_context': 4, 'relations_with_primary_pattern': 4},
        },
        {'coverage': {'findings_requested': 4, 'findings_with_purchase_order': 4}},
        {'coverage': {'providers_published': 4, 'providers_with_valid_rut': 4, 'providers_matched_in_sii': 4}},
        {'status': 'READY_WITH_GAPS', 'coverage': {
            'target_orders': 10,
            'api_requests_attempted': 10,
            'orders_resolved': 6,
            'identity_matches': 5,
            'identity_reviews': 1,
            'linked_tenders': 4,
        }},
    )
    topics = {x['topic'] for x in base['recommendations']}
    assert base['coverage']['mercado_publico_resolution_ratio'] == 0.6
    assert 'COBERTURA_API_MERCADO_PUBLICO' in topics
    assert 'IDENTIDAD_OC_REQUIERE_REVISION' in topics
