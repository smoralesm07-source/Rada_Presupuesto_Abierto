import pandas as pd

from radar_presupuesto.search import hybrid_search


def _sample(tmp_path):
    rows = [
        {
            "transaction_id":"T1","organization_id":"ORG1","recipient_id":"R1","provider_id":"P1",
            "rut_beneficiario":"76123456-0","beneficiario_source_id":"76123456-0","beneficiario_id_type":"RUT",
            "nombre_beneficiario":"CONSTRUCTORA NORTE SPA","nombre_partida":"MINISTERIO OBRAS PUBLICAS","nombre_capitulo":"DIRECCION VIALIDAD","nombre_area":"OBRAS",
            "nombre_subtitulo":"INICIATIVAS DE INVERSION","nombre_item":"OBRAS CIVILES","nombre_asignacion":"CAMINOS","nombre_programa_presupuestario":"CONSERVACION",
            "numero_documento":"100","tipo_documento":"FACTURA","orden_compra":"OC-1","codigo_bip":"BIP-1","nombre_bip":"RUTA NORTE",
            "nombre_ubicacion_geografica":"ANTOFAGASTA","region":"ANTOFAGASTA","sector":"TRANSPORTE","periodo":2026,"mes":7,
            "monto_devengado":5000000,"monto_pago":4900000,"moneda_presupuestaria":"CLP","is_provider":True,"is_person":False,"is_honorarium":False,"is_intra_state":False,"is_floating_debt":False,"is_aggregated":False,"dias_de_pago":20,
        },
        {
            "transaction_id":"T2","organization_id":"ORG2","recipient_id":"R2","provider_id":"P2",
            "rut_beneficiario":"","beneficiario_source_id":"abc","beneficiario_id_type":"SOURCE_ID",
            "nombre_beneficiario":"SERVICIOS SUR SPA","nombre_partida":"MINISTERIO SALUD","nombre_capitulo":"SERVICIO SALUD","nombre_area":"SALUD",
            "nombre_subtitulo":"BIENES Y SERVICIOS","nombre_item":"MANTENCION","nombre_asignacion":"SERVICIOS","nombre_programa_presupuestario":"HOSPITAL",
            "numero_documento":"200","tipo_documento":"FACTURA","orden_compra":"","codigo_bip":"","nombre_bip":"",
            "nombre_ubicacion_geografica":"TEMUCO","region":"ARAUCANIA","sector":"SALUD","periodo":2026,"mes":6,
            "monto_devengado":1000000,"monto_pago":1000000,"moneda_presupuestaria":"CLP","is_provider":True,"is_person":False,"is_honorarium":False,"is_intra_state":False,"is_floating_debt":False,"is_aggregated":False,"dias_de_pago":30,
        },
    ]
    path=tmp_path/"sample.parquet"; pd.DataFrame(rows).to_parquet(path,index=False); return str(path)


def test_text_modes_and_exclusion(tmp_path):
    p=_sample(tmp_path)
    assert len(hybrid_search(p,text="constructora norte",text_mode="all"))==1
    assert len(hybrid_search(p,text="constructora salud",text_mode="any"))==2
    assert len(hybrid_search(p,text="constructora norte",text_mode="phrase"))==1
    assert len(hybrid_search(p,text="spa",exclude_text="sur"))==1


def test_field_scope_and_sort(tmp_path):
    p=_sample(tmp_path)
    assert len(hybrid_search(p,text="salud",search_fields=["institution"]))==1
    assert len(hybrid_search(p,text="antofagasta",search_fields=["geography"]))==1
    df=hybrid_search(p,sort_by="amount_desc",limit=2)
    assert df.iloc[0]["transaction_id"]=="T1"
