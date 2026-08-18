from pathlib import Path

import pandas as pd
import pytest

from radar_presupuesto.regions import region_code, region_meta, region_reference
from radar_presupuesto.spend_view import build_spend_view


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("13", "13"),
        ("9", "09"),
        ("05", "05"),
        ("RM", "13"),
        ("Región Metropolitana", "13"),
        ("REGION DEL BIOBIO", "08"),
        ("XIV REGION DE LOS RIOS", "14"),
        ("Ñuble", "16"),
        ("O'Higgins", "06"),
        ("Aysén", "11"),
        ("", "UNKNOWN"),
        (None, "UNKNOWN"),
        ("99", "UNKNOWN"),
        ("marte", "UNKNOWN"),
    ],
)
def test_region_code_resolves_source_variants(raw, expected):
    assert region_code(raw) == expected


def test_region_reference_is_ordered_north_to_south():
    reference = region_reference()
    assert [r["region_code"] for r in reference][:3] == ["15", "01", "02"]
    assert reference[-1]["region_code"] == "UNKNOWN"
    assert region_meta("13")["macrozone"] == "CENTRO"


def _facts() -> pd.DataFrame:
    rows = []
    # Proveedor histórico repartido entre dos organismos y dos regiones.
    for year in (2025, 2026):
        for month in (3, 6, 9):
            rows.append(
                dict(
                    transaction_id=f"t-hist-{year}-{month}", organization_id="o1",
                    provider_id="p-hist", recipient_id="r-hist", entity_id="ENT-RUT-1",
                    rut_beneficiario="76111111-1", nombre_beneficiario="PROVEEDOR HISTORICO",
                    periodo=year, mes=month, monto_devengado=40_000_000.0, monto_pago=40_000_000.0,
                    dias_de_pago=30.0, orden_compra="OC-1", subtitulo="22",
                    nombre_subtitulo="BIENES Y SERVICIOS", nombre_partida="MINISTERIO A",
                    nombre_capitulo="SUBSECRETARIA", nombre_area="SERVICIO A", region="05",
                    codigo_ubicacion_geografica="05101", is_provider=True, is_person=False,
                    is_honorarium=False, is_intra_state=False, is_floating_debt=False, is_aggregated=False,
                )
            )
    # Entrante nuevo de 2026: comprador único, sin OC, cierre de año y montos redondos.
    for month in (11, 12):
        rows.append(
            dict(
                transaction_id=f"t-new-{month}", organization_id="o2", provider_id="p-new",
                recipient_id="r-new", entity_id="ENT-RUT-2", rut_beneficiario="77222222-2",
                nombre_beneficiario="ENTRANTE NUEVO", periodo=2026, mes=month,
                monto_devengado=500_000_000.0, monto_pago=500_000_000.0, dias_de_pago=1.0,
                orden_compra=None, subtitulo="31", nombre_subtitulo="INICIATIVAS DE INVERSION",
                nombre_partida="MINISTERIO B", nombre_capitulo="SUBSECRETARIA B", nombre_area="SERVICIO B",
                region="13", codigo_ubicacion_geografica="13101", is_provider=True, is_person=False,
                is_honorarium=False, is_intra_state=False, is_floating_debt=False, is_aggregated=False,
            )
        )
    # Pago sin región informada: categoría propia, nunca cero silencioso.
    rows.append(
        dict(
            transaction_id="t-sin-region", organization_id="o2", provider_id="p-hist",
            recipient_id="r-hist", entity_id="ENT-RUT-1", rut_beneficiario="76111111-1",
            nombre_beneficiario="PROVEEDOR HISTORICO", periodo=2026, mes=5,
            monto_devengado=10_000_000.0, monto_pago=10_000_000.0, dias_de_pago=40.0,
            orden_compra="OC-9", subtitulo="22", nombre_subtitulo="BIENES Y SERVICIOS",
            nombre_partida="MINISTERIO B", nombre_capitulo="SUBSECRETARIA B", nombre_area="SERVICIO B",
            region="", codigo_ubicacion_geografica="", is_provider=True, is_person=False,
            is_honorarium=False, is_intra_state=False, is_floating_debt=False, is_aggregated=False,
        )
    )
    return pd.DataFrame(rows)


@pytest.fixture()
def built(tmp_path: Path) -> dict:
    processed = tmp_path / "processed"
    signals = tmp_path / "signals"
    processed.mkdir()
    signals.mkdir()
    _facts().to_parquet(processed / "transactions_2026.parquet", index=False)
    pd.DataFrame(
        [
            dict(signal_id="s1", signal_type="POTENTIAL_FRAGMENTATION", transaction_id="t-new-12",
                 organization_id="o2", provider_id="p-new", priority_tier="P1", severity="HIGH",
                 investigation_priority_score=88.0, cgr_match_count=1, periodo=2026),
        ]
    ).to_parquet(signals / "prioritized_signals.parquet", index=False)
    return build_spend_view(
        str(processed / "transactions_*.parquet"),
        str(signals / "prioritized_signals.parquet"),
        str(tmp_path / "spend_view.json"),
        config_path=str(tmp_path / "missing_config.yaml"),
    )


def test_schema_and_coverage(built):
    assert built["schema"] == "PRESUPUESTO_SPEND_VIEW_V1"
    assert built["mode"] == "REAL"
    assert built["coverage"]["transactions"] == 9
    assert built["coverage"]["first_year"] == 2025 and built["coverage"]["last_year"] == 2026
    assert built["coverage"]["priority_queue_available"] is True
    assert built["methodology"]["budget_appropriation_available"] is False


def test_missing_region_is_its_own_category_not_zero(built):
    regions = {r["region_code"]: r for r in built["territory"]["regions"]}
    assert regions["UNKNOWN"]["devengado"] == 10_000_000.0
    assert regions["13"]["devengado"] == 1_000_000_000.0
    assert 0 < regions["UNKNOWN"]["share_of_national"] < 0.02
    assert built["territory"]["concentration"]["unassigned_share"] > 0


def test_execution_series_is_complete_and_cumulative(built):
    monthly = built["execution"]["monthly"]
    assert {m["month_label"] for m in monthly} >= {"2026-11", "2026-12"}
    last_2026 = [m for m in monthly if m["periodo"] == 2026][-1]
    assert last_2026["cumulative_share_of_year"] == pytest.approx(1.0, abs=1e-6)
    by_year = {y["periodo"]: y for y in built["execution"]["by_year"]}
    assert by_year[2026]["payment_ratio"] == pytest.approx(1.0)
    assert by_year[2026]["december_share"] > by_year[2026]["expected_uniform_december_share"]


def test_new_entrant_is_detected_and_scored_explainably(built):
    new_block = built["new_providers"]
    assert new_block["available"] is True
    assert new_block["cohort_year"] == 2026
    assert "ENTRANTE NUEVO" in [p["provider_name"] for p in new_block["material"]]

    scored = {p["provider_name"]: p for p in built["providers"]["anomalous"]}
    entrant = scored["ENTRANTE NUEVO"]
    codes = {r["code"] for r in entrant["reasons"]}
    assert {"NUEVO_CON_MONTO_MATERIAL", "DEPENDENCIA_DE_UN_COMPRADOR", "SIN_ORDEN_DE_COMPRA"} <= codes
    assert 0 < entrant["anomaly_score"] <= 100
    assert entrant["anomaly_score"] <= sum(built["providers"]["score_weights"].values())
    assert all(r["weight"] <= r["max_weight"] for r in entrant["reasons"])
    assert all(r["alternative_reading"] for r in entrant["reasons"])


def test_signals_are_reused_not_recreated(built):
    assert built["methodology"]["no_new_signals_created"] is True
    assert built["patterns"]["signal_types"] == {"POTENTIAL_FRAGMENTATION": 1}
    regions = {r["region_code"]: r for r in built["territory"]["regions"]}
    assert regions["13"]["p1_signals"] == 1
    assert regions["13"]["cgr_linked_signals"] == 1


def test_headline_and_guardrails_present(built):
    ids = {k["id"] for k in built["headline_indicators"]}
    assert {"devengado_total", "region_concentration", "new_provider_amount", "anomalous_providers"} <= ids
    assert "GASTO_PUBLICO_NO_ES_RIESGO_POR_SI_MISMO" in built["guardrails"]
    assert "AUSENCIA_NO_ES_CERO" in built["guardrails"]
    assert built["indicator_catalog"]


def test_institutions_answer_who_buys_from_whom(built):
    block = built["institutions"]
    rows = {r["organization_name"]: r for r in block["rows"]}
    assert "SERVICIO B" in rows and "SERVICIO A" in rows

    servicio_b = rows["SERVICIO B"]
    assert servicio_b["amounts_by_year"][-1] > 0
    assert servicio_b["detail_available"] is True

    detail = block["detail"][servicio_b["organization_id"]]
    schema = block["detail_schema"]["p"]
    top = dict(zip(schema, detail["p"][0]))
    # El entrante nuevo es el proveedor de mayor influencia del servicio B.
    assert block["provider_names"][top["provider_name_index"]] == "ENTRANTE NUEVO"
    assert top["share_of_organization"] == pytest.approx(1.0, abs=0.01)
    assert top["provider_id"] == "p-new"

    # En qué gastó: el subtítulo declarado por la fuente, con su participación.
    line = dict(zip(block["detail_schema"]["l"], detail["l"][0]))
    assert block["line_names"][line["line_name_index"]] == "INICIATIVAS DE INVERSION"
    assert sum(detail["m"]) > 0, "la serie mensual del servicio debe estar publicada"

    # La matriz servicio×año se arma desde las filas: los totales por año deben
    # cuadrar con la suma de todos los organismos publicados.
    participation = block["participation"]
    for index, year_total in enumerate(participation["totals"]):
        assert year_total == pytest.approx(
            sum(r["amounts_by_year"][index] for r in block["rows"]), rel=1e-6
        )
    assert participation["visible_rows"] >= 1
    assert block["rows"] == sorted(block["rows"], key=lambda r: (-r["amount_clp"], r["organization_name"] or ""))

    # Detalle por año: el mismo servicio, distinto foco temporal.
    year = str(block["years"][-1])
    slot = detail["y"][year]
    year_top = dict(zip(block["detail_schema"]["y"]["p"], slot["p"][0]))
    assert year_top["share_of_organization_year"] > 0
    assert block["line_names"][slot["l"][0][1]]


def test_pinned_institution_survives_the_size_cut(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    _facts().to_parquet(processed / "transactions_2026.parquet", index=False)
    config = tmp_path / "spend_view.yaml"
    config.write_text(
        "institutions:\n  max_rows: 1\n  always_include:\n    - SERVICIO B\n",
        encoding="utf-8",
    )
    payload = build_spend_view(
        str(processed / "transactions_*.parquet"),
        str(tmp_path / "missing.parquet"),
        str(tmp_path / "out.json"),
        config_path=str(config),
    )
    rows = {r["organization_name"]: r for r in payload["institutions"]["rows"]}
    # El corte por tamaño deja una fila, pero el servicio fijado igual aparece.
    assert "SERVICIO B" in rows
    assert rows["SERVICIO B"]["pinned"] is True
    assert rows["SERVICIO B"]["detail_available"] is True


def test_institution_detail_floor_is_declared(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    _facts().to_parquet(processed / "transactions_2026.parquet", index=False)
    config = tmp_path / "spend_view.yaml"
    config.write_text("institutions:\n  detail_min_amount_clp: 100000000000\n", encoding="utf-8")
    payload = build_spend_view(
        str(processed / "transactions_*.parquet"),
        str(tmp_path / "missing.parquet"),
        str(tmp_path / "out.json"),
        config_path=str(config),
    )
    block = payload["institutions"]
    assert block["coverage"]["organizations_with_detail"] == 0
    assert block["detail"] == {}
    assert all(r["detail_available"] is False for r in block["rows"])
    assert block["coverage"]["detail_min_amount_clp"] == 100000000000
    # La fila compacta sobrevive: ausencia de ficha no es ausencia de organismo.
    assert all(r["amounts_by_year"] for r in block["rows"])


def test_runs_without_priority_queue(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir()
    _facts().to_parquet(processed / "transactions_2026.parquet", index=False)
    payload = build_spend_view(
        str(processed / "transactions_*.parquet"),
        str(tmp_path / "no_priority.parquet"),
        str(tmp_path / "out.json"),
    )
    assert payload["coverage"]["priority_queue_available"] is False
    assert payload["patterns"]["signal_types"] == {}
    assert (tmp_path / "out.json").exists()
