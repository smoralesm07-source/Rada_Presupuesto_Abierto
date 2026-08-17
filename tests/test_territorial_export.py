from pathlib import Path

import pandas as pd

from radar_presupuesto.territorial_export import build_territorial_context


def test_build_territorial_context(tmp_path: Path):
    processed = tmp_path / 'data' / 'processed'
    signals = tmp_path / 'data' / 'signals'
    processed.mkdir(parents=True)
    signals.mkdir(parents=True)

    facts = pd.DataFrame([
        {'transaction_id':'t1','region':'13','monto_devengado':100.0,'organization_id':'o1','provider_id':'p1','codigo_ubicacion_geografica':'13101','nombre_ubicacion_geografica':'Santiago'},
        {'transaction_id':'t2','region':'13','monto_devengado':300.0,'organization_id':'o1','provider_id':'p2','codigo_ubicacion_geografica':'13101','nombre_ubicacion_geografica':'Santiago'},
        {'transaction_id':'t3','region':'05','monto_devengado':200.0,'organization_id':'o2','provider_id':'p3','codigo_ubicacion_geografica':'05101','nombre_ubicacion_geografica':'Valparaiso'},
    ])
    priority = pd.DataFrame([
        {'transaction_id':'t1','signal_type':'AMOUNT_OUTLIER','priority_tier':'P1','severity':'HIGH','investigation_priority_score':90,'cgr_match_count':1},
        {'transaction_id':'t3','signal_type':'PROVIDER_CONCENTRATION','priority_tier':'P2','severity':'MEDIUM','investigation_priority_score':70,'cgr_match_count':0},
    ])
    facts.to_parquet(processed / 'transactions_2026.parquet', index=False)
    priority.to_parquet(signals / 'prioritized_signals.parquet', index=False)
    out = tmp_path / 'territorial.json'

    payload = build_territorial_context(
        str(processed / 'transactions_*.parquet'),
        str(signals / 'prioritized_signals.parquet'),
        str(out),
    )

    assert payload['schema'] == 'PRESUPUESTO_TERRITORIAL_CONTEXT_V1'
    assert payload['coverage']['regions'] == 2
    assert payload['coverage']['commune_canonicalization_state'] == 'PENDING_CONTEXT_HUB_VALIDATION'
    rm = next(row for row in payload['regions'] if row['region'] == '13')
    assert rm['transactions'] == 2
    assert rm['p1_signals'] == 1
    assert rm['cgr_linked_signals'] == 1
    santiago = next(row for row in payload['geographic_units'] if row['geographic_unit_code'] == '13101')
    assert santiago['p1_signals'] == 1
    assert payload['methodology']['source_geographic_unit_is_commune'] is False
    assert out.exists()
