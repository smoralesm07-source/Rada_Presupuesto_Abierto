from radar_presupuesto.mercado_publico_bridge import (
    build_targets,
    parse_order_payload,
)


def test_parse_order_payload_normalizes_core_fields():
    payload = {
        'Cantidad': 1,
        'Listado': [
            {
                'Codigo': '1606-203-TD26',
                'Nombre': 'Orden ejemplo',
                'CodigoEstado': 6,
                'CodigoLicitacion': '1606-12-FTD26',
                'Tipo': 'SE',
                'TipoMoneda': 'CLP',
                'EstadoProveedor': 'Aceptada',
                'Total': 142908,
                'Fechas': {'FechaEnvio': '2026-05-26T10:00:00'},
                'Comprador': {
                    'CodigoOrganismo': 'ORG-1',
                    'NombreOrganismo': 'Servicio de ejemplo',
                    'RutUnidad': '60.808.000-7',
                },
                'Proveedor': {
                    'Codigo': 'PRV1',
                    'Nombre': 'Proveedor ejemplo',
                    'RutSucursal': '89.862.200-2',
                },
                'Items': {
                    'Cantidad': 1,
                    'Listado': [
                        {'Categoria': 'Servicios', 'CodigoProducto': 80101508}
                    ],
                },
            }
        ],
    }
    out = parse_order_payload(payload, '1606-203-TD26')
    assert out['purchase_order_code'] == '1606-203-TD26'
    assert out['linked_tender_code'] == '1606-12-FTD26'
    assert out['buyer']['unit_rut'] == '60808000-7'
    assert out['supplier']['rut'] == '89862200-2'
    assert out['total'] == 142908.0
    assert out['categories'] == ['Servicios']


def test_parse_order_payload_supports_nested_historical_wrapper():
    payload = {
        'Listado': {
            'OrdenCompra': {
                'Codigo': '1-2-SE26',
                'Proveedor': {'RutSucursal': '76.415.528-9'},
                'Items': {'Cantidad': 0},
            }
        }
    }
    out = parse_order_payload(payload, '1-2-SE26')
    assert out['purchase_order_code'] == '1-2-SE26'
    assert out['supplier']['rut'] == '76415528-9'


def test_build_targets_is_bounded_and_priority_ordered():
    findings = {
        'relation_findings': [
            {'finding_id': 'low', 'attention_level': 'SEGUIMIENTO', 'max_priority_score': 90},
            {'finding_id': 'high', 'attention_level': 'ATENCION_INMEDIATA', 'max_priority_score': 70},
        ]
    }
    procurement = {
        'findings': [
            {
                'finding_id': 'low',
                'provider_id': 'PRV-RUT-11.111.111-1',
                'organization_id': 'A',
                'periodo': 2026,
                'purchase_order_examples': ['A-1-SE26', 'A-2-SE26'],
            },
            {
                'finding_id': 'high',
                'provider_id': 'PRV-RUT-76.415.528-9',
                'organization_id': 'B',
                'periodo': 2026,
                'purchase_order_examples': ['B-1-SE26', 'B-2-SE26', 'B-3-SE26'],
            },
        ]
    }
    out = build_targets(procurement, findings, max_orders_per_finding=2, max_total_orders=3)
    assert [x['finding_id'] for x in out] == ['high', 'high', 'low']
    assert out[0]['expected_provider_rut'] == '76415528-9'
    assert len(out) == 3
