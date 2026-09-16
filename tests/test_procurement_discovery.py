"""Una fuente no probada no es una fuente inexistente.

El módulo existe para responder una sola pregunta —si ChileCompra publica un
listado de órdenes por fecha— porque de ella depende si 2024 en adelante cabe
en el límite diario de consultas o queda fuera de alcance. Lo que estas pruebas
cuidan es que la respuesta no se invente: que «no se pudo probar» y «no existe»
no colapsen en el mismo veredicto, y que el ticket no termine escrito en un
payload que se publica.
"""
import json

import pytest

from radar_presupuesto import procurement_discovery as pd_mod
from radar_presupuesto.procurement_discovery import (
    BLOCKED,
    DAILY_REQUEST_LIMIT,
    NEEDS_TICKET,
    REACHABLE,
    SCHEMA,
    UNREACHABLE,
    _describe_shape,
    assess_feasibility,
    candidate_sources,
    discover,
    write_sources,
)


def _row(source_id, state):
    return {"id": source_id, "state": state}


ALL_IDS = [c["id"] for c in candidate_sources("01012026", "1509-11-SE24", "76045081-2")]


def _results(**states):
    """Todos los candidatos, con el estado indicado y NEEDS_TICKET por defecto."""
    return [_row(i, states.get(i, NEEDS_TICKET)) for i in ALL_IDS]


# --- la pregunta que decide la factibilidad -------------------------------


def test_listado_diario_alcanzable_declara_viable_con_el_costo_en_consultas():
    verdict = assess_feasibility(_results(OC_POR_FECHA=REACHABLE))
    assert verdict["verdict"] == "VIABLE_POR_LISTADO_DIARIO"
    # El veredicto sólo sirve si dice cuánto cuesta: un año de cobertura tiene
    # que caber holgadamente en el límite diario, y el número debe estar a la vista.
    assert verdict["estimated_requests_per_year"] <= 366
    assert verdict["estimated_requests_per_year"] < DAILY_REQUEST_LIMIT


def test_sin_listado_diario_pero_con_catalogo_manda_a_revisar_descargas():
    verdict = assess_feasibility(
        _results(OC_POR_FECHA=UNREACHABLE, CATALOGO_DATOS_ABIERTOS=REACHABLE)
    )
    assert verdict["verdict"] == "REVISAR_DESCARGAS_MASIVAS"


def test_el_listado_diario_manda_sobre_el_catalogo():
    """Si ambos responden, la vía barata es la que fija el plan."""
    verdict = assess_feasibility(
        _results(OC_POR_FECHA=REACHABLE, CATALOGO_DATOS_ABIERTOS=REACHABLE)
    )
    assert verdict["verdict"] == "VIABLE_POR_LISTADO_DIARIO"


# --- no saber es un resultado, no un cero ---------------------------------


def test_red_bloqueada_no_se_confunde_con_fuente_inexistente():
    verdict = assess_feasibility(_results(CATALOGO_DATOS_ABIERTOS=BLOCKED))
    assert verdict["verdict"] == "NO_DETERMINADO"
    assert verdict["blocked"] == ["CATALOGO_DATOS_ABIERTOS"]
    # Un NO_DETERMINADO que no dice dónde volver a correrlo es un callejón sin salida.
    assert "CI" in verdict["why"]


def test_un_bloqueo_no_borra_un_listado_diario_que_si_respondio():
    verdict = assess_feasibility(
        _results(OC_POR_FECHA=REACHABLE, CATALOGO_DATOS_ABIERTOS=BLOCKED)
    )
    assert verdict["verdict"] == "VIABLE_POR_LISTADO_DIARIO"


def test_todo_inalcanzable_sin_bloqueos_es_un_no_definitivo():
    verdict = assess_feasibility([_row(i, UNREACHABLE) for i in ALL_IDS])
    assert verdict["verdict"] == "SIN_VIA_DE_VOLUMEN_CONFIRMADA"
    assert "10.000" in verdict["why"]


def test_proxy_bloqueado_y_404_del_servidor_no_son_el_mismo_hecho(monkeypatch):
    """El proxy dice «desde aquí no se ve»; un 404 dice «no existe». Confundirlos
    descartaría una fuente que estaba abierta."""
    import requests

    def _raise(*a, **k):
        raise requests.exceptions.ProxyError("tunnel 403")

    monkeypatch.setattr(requests, "get", _raise)
    blocked = pd_mod.probe("https://api.mercadopublico.cl/algo")
    assert blocked["state"] == BLOCKED
    assert "no dice nada sobre la fuente" in blocked["note"]

    class _Resp:
        status_code = 404
        headers = {"content-type": "text/html"}
        raw = type("R", (), {"read": staticmethod(lambda n, decode_content=True: b"")})()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    missing = pd_mod.probe("https://api.mercadopublico.cl/otro")
    assert missing["state"] == UNREACHABLE
    assert missing["http_status"] == 404


# --- describir la respuesta sin afirmar de más ----------------------------


def test_trozo_parcial_de_json_no_se_adivina():
    """4096 bytes de un JSON grande no son un JSON: decir la forma sería inventarla."""
    truncated = b'{"Listado": [{"Codigo": "1509-11-SE24", "Nombre": "Adquis'
    shape = _describe_shape(truncated)
    assert shape["determined"] is False
    assert "head" in shape


def test_respuesta_vacia_se_declara_indeterminada():
    assert _describe_shape(b"")["determined"] is False


def test_json_completo_reporta_sus_claves():
    shape = _describe_shape(json.dumps({"Cantidad": 2, "Listado": []}).encode("utf-8"))
    assert shape["determined"] is True
    assert shape["type"] == "object"
    assert "Listado" in shape["keys"]


def test_arreglo_reporta_largo_y_claves_del_primero():
    shape = _describe_shape(json.dumps([{"Codigo": "x"}]).encode("utf-8"))
    assert shape == {"determined": True, "type": "array", "length": 1,
                     "first_keys": ["Codigo"]}


def test_html_de_error_no_se_lee_como_datos():
    shape = _describe_shape(b"<!DOCTYPE html><html><body>Service Unavailable")
    assert shape["determined"] is False


# --- el ticket no se publica ----------------------------------------------


def test_sin_ticket_no_se_consulta_la_api_y_se_dice_por_que(monkeypatch):
    probed: list[str] = []

    def _fake_probe(url, timeout=25):
        probed.append(url)
        return {"state": UNREACHABLE, "http_status": 404}

    monkeypatch.setattr(pd_mod, "probe", _fake_probe)
    payload = discover(ticket=None)

    by_id = {s["id"]: s for s in payload["sources"]}
    assert by_id["OC_POR_FECHA"]["state"] == NEEDS_TICKET
    assert "MERCADO_PUBLICO_TICKET" in by_id["OC_POR_FECHA"]["note"]
    # Sólo el catálogo abierto se prueba sin credencial.
    assert probed == [by_id["CATALOGO_DATOS_ABIERTOS"]["url"]]
    assert payload["ticket_present"] is False


def test_el_ticket_se_usa_para_consultar_pero_nunca_queda_escrito(monkeypatch):
    secret = "TICKET-SECRETO-0001"
    seen: list[str] = []

    def _fake_probe(url, timeout=25):
        seen.append(url)
        return {"state": REACHABLE, "http_status": 200,
                "sample_shape": {"determined": True, "type": "object", "keys": ["Listado"]}}

    monkeypatch.setattr(pd_mod, "probe", _fake_probe)
    payload = discover(ticket=secret)

    assert any(secret in url for url in seen), "el ticket debe llegar a la consulta"
    assert secret not in json.dumps(payload, ensure_ascii=False), \
        "el ticket no puede quedar en un payload que se publica"
    assert all("<ticket>" in s["url"] for s in payload["sources"] if s["needs_ticket"])


def test_write_sources_deja_el_payload_con_su_esquema_y_guardrail(tmp_path, monkeypatch):
    monkeypatch.setattr(pd_mod, "probe",
                        lambda url, timeout=25: {"state": BLOCKED, "error": "ProxyError"})
    out = tmp_path / "docs" / "data" / "procurement_sources.json"
    payload = write_sources(out, ticket=None)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["schema"] == SCHEMA == payload["schema"]
    assert written["daily_request_limit"] == DAILY_REQUEST_LIMIT
    # El guardrail viaja en el payload, como en todos los demás.
    assert "no conducta" in written["guardrail"]
    assert written["coverage_feasibility"]["verdict"] == "NO_DETERMINADO"


# --- los candidatos declaran qué desbloquean ------------------------------


@pytest.mark.parametrize("cand", candidate_sources("01012026", "1509-11-SE24", "76045081-2"))
def test_cada_candidato_declara_hipotesis_y_costo(cand):
    assert cand["unlocks"].strip()
    assert cand["volume"]
    assert cand["url"].startswith("https://")


def test_existe_el_candidato_del_que_depende_la_factibilidad():
    ids = {c["id"] for c in candidate_sources("01012026", "1509-11-SE24", "76045081-2")}
    assert {"OC_POR_FECHA", "CATALOGO_DATOS_ABIERTOS"} <= ids
