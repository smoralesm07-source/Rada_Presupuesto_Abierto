from pathlib import Path

import duckdb
import pandas as pd

from radar_presupuesto.peer_groups import build_provider_peer_context


def test_peer_context_ranks_provider_within_same_budget_category(tmp_path: Path):
    rows = []
    amounts = [10, 20, 30, 40, 500]
    for i, amount in enumerate(amounts):
        rows.append(
            {
                "organization_id": "ORG-A",
                "periodo": 2026,
                "subtitulo": "22",
                "item": "08",
                "provider_id": f"PRV-{i}",
                "nombre_beneficiario": f"Proveedor {i}",
                "monto_devengado": amount * 1_000_000,
                "is_provider": True,
                "is_aggregated": False,
            }
        )
    facts = tmp_path / "facts.parquet"
    out = tmp_path / "peers.parquet"
    pd.DataFrame(rows).to_parquet(facts, index=False)

    result = build_provider_peer_context(str(facts), str(out), min_peer_providers=5)
    con = duckdb.connect()
    top = con.execute(
        f"SELECT peer_provider_count,peer_percentile,peer_position,amount_to_peer_median_ratio,peer_guardrail "
        f"FROM read_parquet('{out.as_posix()}') WHERE provider_id='PRV-4'"
    ).fetchone()
    con.close()

    assert result["rows"] == 5
    assert result["peer_groups"] == 1
    assert top[0] == 5
    assert top[1] == 1.0
    assert top[2] == "EXTREME_WITHIN_PEERS"
    assert top[3] > 10
    assert "no acredita irregularidad" in top[4].lower()


def test_small_peer_group_is_not_treated_as_extreme(tmp_path: Path):
    rows = [
        {
            "organization_id": "ORG-A",
            "periodo": 2026,
            "subtitulo": "22",
            "item": "08",
            "provider_id": f"PRV-{i}",
            "nombre_beneficiario": f"Proveedor {i}",
            "monto_devengado": amount,
            "is_provider": True,
            "is_aggregated": False,
        }
        for i, amount in enumerate([10, 20, 1000])
    ]
    facts = tmp_path / "facts.parquet"
    out = tmp_path / "peers.parquet"
    pd.DataFrame(rows).to_parquet(facts, index=False)

    build_provider_peer_context(str(facts), str(out), min_peer_providers=5)
    con = duckdb.connect()
    positions = con.execute(
        f"SELECT DISTINCT peer_position FROM read_parquet('{out.as_posix()}')"
    ).fetchall()
    con.close()

    assert positions == [("INSUFFICIENT_PEERS",)]
