"""La amplitud de giros y el patrimonio negativo, medidos contra pares."""
from radar_presupuesto.entity_signals import (
    ACTIVITY_BREADTH_FALLBACK,
    ACTIVITY_BREADTH_FLOOR,
    activity_breadth_thresholds,
    band_median,
)

_activity_breadth_thresholds = activity_breadth_thresholds
_band_median = band_median


def test_each_band_gets_its_own_threshold():
    # Un tramo de empresas grandes con muchos giros y uno de pequeñas con pocos.
    grandes = [3] * 40 + [9] * 5
    chicas = [1] * 40 + [4] * 5
    th = _activity_breadth_thresholds({13: grandes, 2: chicas})
    assert th[13] > th[2], "el tramo con más giros debe exigir más para destacar"
    assert th[2] >= ACTIVITY_BREADTH_FLOOR, "un piso evita marcar a cualquiera en un tramo homogéneo"


def test_a_band_with_few_peers_falls_back_instead_of_inventing_a_threshold():
    # Con tres pares no hay distribución que medir; inventar un percentil ahí
    # sería peor que usar el umbral conocido.
    th = _activity_breadth_thresholds({7: [1, 2, 3]})
    assert th[7] == ACTIVITY_BREADTH_FALLBACK


def test_the_same_count_can_be_ordinary_in_one_band_and_unusual_in_another():
    th = _activity_breadth_thresholds({13: [8] * 40, 2: [1] * 40})
    seis = 6
    assert seis < th[13], "seis giros no destaca donde la mediana del tramo es ocho"
    assert seis >= th[2], "seis giros sí destaca donde la mediana del tramo es uno"


def test_band_median_is_reported_so_the_analyst_can_weigh_it():
    assert _band_median([1, 3, 3, 9]) == 3
    assert _band_median([]) == 0
