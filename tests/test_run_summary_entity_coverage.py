import json

from radar_presupuesto.run_summary import _first_int


def test_reads_the_key_the_producer_actually_writes():
    # build_case_entity_context.py escribe estos nombres; el resumen buscaba
    # tres alias que nadie escribe y caía al cero por defecto.
    cov = {"providers_published": 286, "providers_with_valid_rut": 286,
           "providers_matched_in_sii": 93, "providers_without_valid_rut": 4}
    assert _first_int(cov, ("providers_published", "published_providers"), default=0) == 286
    assert _first_int(cov, ("providers_matched_in_sii", "matched"), default=None) == 93


def test_a_real_zero_is_not_confused_with_a_missing_key():
    # Una cadena de `or` descarta el 0 igual que la clave ausente. Medir cero
    # cruces es un resultado; no medir es una capa que no se calculó.
    assert _first_int({"providers_matched_in_sii": 0}, ("providers_matched_in_sii",), default=None) == 0
    assert _first_int({}, ("providers_matched_in_sii",), default=None) is None


def test_unknown_shape_falls_back_without_crashing():
    assert _first_int({"providers_matched_in_sii": "x"}, ("providers_matched_in_sii",), default=7) == 7
    assert _first_int({}, ("nada",), default=5) == 5
