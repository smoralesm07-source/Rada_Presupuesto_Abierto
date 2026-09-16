"""Un 429 dice «espera», no «no existe».

La corrida #21 resolvió 349 órdenes y perdió 413, casi todas por HTTP 429
contra una pausa fija de 0,05s. Tratar el límite de ritmo como un fallo
definitivo botó más de la mitad de una corrida de nueve minutos que ya estaba
pagada con el tiempo del runner.
"""
from urllib.error import HTTPError

import pytest

from radar_presupuesto.mercado_publico_bridge import (
    RATE_LIMIT_MAX_RETRIES,
    _is_rate_limited,
    fetch_order_with_backoff,
)


def _http(status):
    return HTTPError("https://api.mercadopublico.cl/x", status, "err", {}, None)


def _fetch_failing(times, status=429, then=None):
    """Falla `times` veces con ese estado y después devuelve `then`."""
    state = {"calls": 0}

    def _fetch(code, ticket, timeout, endpoint):
        state["calls"] += 1
        if state["calls"] <= times:
            raise _http(status)
        return then

    _fetch.state = state
    return _fetch


def test_un_429_transitorio_se_recupera_en_vez_de_perderse():
    order = {"purchase_order_code": "1509-11-SE24"}
    fetch = _fetch_failing(2, then=order)
    got, retries = fetch_order_with_backoff(
        "1509-11-SE24", "t", "ordenesdecompra.json", fetch=fetch, sleep=lambda s: None
    )
    assert got is order
    assert retries == 2


def test_el_reintento_tiene_techo_y_no_insiste_para_siempre():
    fetch = _fetch_failing(99)
    with pytest.raises(HTTPError):
        fetch_order_with_backoff(
            "x", "t", "ordenesdecompra.json", fetch=fetch, sleep=lambda s: None
        )
    # Un intento inicial más los reintentos permitidos, ni uno más.
    assert fetch.state["calls"] == RATE_LIMIT_MAX_RETRIES + 1


def test_la_espera_crece_entre_reintentos():
    """Insistir al mismo ritmo contra un límite de ritmo no lo levanta."""
    waits = []
    fetch = _fetch_failing(2, then={"ok": True})
    fetch_order_with_backoff(
        "x", "t", "ordenesdecompra.json", fetch=fetch, sleep=waits.append
    )
    assert waits == sorted(waits) and len(set(waits)) == len(waits)


def test_un_error_que_no_es_de_ritmo_no_se_reintenta():
    """Repetir un 404 o un 500 no lo va a cambiar, y gasta cuota."""
    fetch = _fetch_failing(99, status=500)
    with pytest.raises(HTTPError):
        fetch_order_with_backoff(
            "x", "t", "ordenesdecompra.json", fetch=fetch, sleep=lambda s: None
        )
    assert fetch.state["calls"] == 1


@pytest.mark.parametrize("status,expected", [(429, True), (404, False), (500, False), (401, False)])
def test_solo_el_429_cuenta_como_limite_de_ritmo(status, expected):
    assert _is_rate_limited(_http(status)) is expected
