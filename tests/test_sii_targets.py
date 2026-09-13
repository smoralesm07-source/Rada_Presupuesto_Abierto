from radar_presupuesto.sii_targets import canon_rut, rut_from_provider_id, target_ruts_from_payload


def test_canon_rut_and_provider_id_are_explicit_only():
    assert canon_rut('76.415.528-9') == '76415528-9'
    assert rut_from_provider_id('PRV-RUT-76.415.528-9') == '76415528-9'
    assert rut_from_provider_id('PRV-SHA1-abc123') == ''
    assert rut_from_provider_id('Proveedor por nombre') == ''


def test_findings_are_preferred_target_universe():
    payload = {
        'relation_findings': [
            {'provider_id': 'PRV-RUT-76415528-9'},
            {'provider_id': 'PRV-SHA1-deadbeef'},
            {'provider_id': 'PRV-RUT-96.689.310-K'},
        ],
        'providers': [{'rut': '11.111.111-1'}],
    }
    assert target_ruts_from_payload(payload) == {'76415528-9', '96689310-K'}


def test_legacy_provider_list_is_only_fallback():
    payload = {
        'providers': [
            {'rut': '76.415.528-9'},
            {'rut': None},
        ]
    }
    assert target_ruts_from_payload(payload) == {'76415528-9'}
