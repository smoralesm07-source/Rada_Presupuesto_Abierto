"""Una corrida que falla sin decir por qué obliga a repetirla para averiguarlo.

La corrida #19 consultó 20 órdenes, falló las 20, se detuvo correctamente, y
publicó «20 errores API» sin una sola palabra sobre la causa. El motivo estaba
en el payload, que murió al empujar a `main`. Entre un ticket rechazado —que el
operador arregla en un minuto— y un endpoint cambiado —que hay que adaptar— no
había forma de distinguir sin volver a gastar la cuota.
"""
from urllib.error import HTTPError, URLError

import pytest

from radar_presupuesto.mercado_publico_bridge import (
    ENDPOINT_CHANGED,
    NETWORK,
    RATE_LIMITED,
    TICKET_REJECTED,
    UNCLASSIFIED,
    diagnose_api_failure,
)


def _http(status):
    return HTTPError("https://api.mercadopublico.cl/x", status, "err", {}, None)


@pytest.mark.parametrize("status,expected", [
    (401, TICKET_REJECTED),
    (403, TICKET_REJECTED),
    (404, ENDPOINT_CHANGED),
    (429, RATE_LIMITED),
])
def test_cada_codigo_http_apunta_a_quien_debe_actuar(status, expected):
    d = diagnose_api_failure(_http(status))
    assert d["cause"] == expected
    assert d["http_status"] == status
    assert d["meaning"].strip()


def test_un_ticket_rechazado_se_declara_accion_del_operador():
    """Es la distinción que ahorra una corrida entera."""
    assert "acción del operador" in diagnose_api_failure(_http(401))["meaning"]


def test_sin_salida_de_red_no_se_culpa_a_la_credencial():
    d = diagnose_api_failure(URLError("Connection refused"))
    assert d["cause"] == NETWORK
    assert "no dice nada sobre la credencial" in d["meaning"].lower()


def test_un_error_desconocido_conserva_su_texto_en_vez_de_inventar_causa():
    d = diagnose_api_failure(ValueError("respuesta no es JSON: <html>503</html>"))
    assert d["cause"] == UNCLASSIFIED
    assert "respuesta no es JSON" in d["error"]


def test_el_texto_del_error_se_acota_para_no_inundar_el_payload():
    d = diagnose_api_failure(ValueError("x" * 2000))
    assert len(d["error"]) <= 300
