import json
from pathlib import Path

import pandas as pd

from radar_presupuesto.signal_health import build_signal_health


def test_zero_signal_is_marked_experimental(tmp_path: Path):
    rows = []
    for i in range(20):
        rows.append({
            "signal_type": "AMOUNT_OUTLIER",
            "organization_id": f"ORG-{i%3}",
            "provider_id": f"PRV-{i}",
            "periodo": 2026,
            "severity": "HIGH" if i < 5 else "MEDIUM",
        })
    path = tmp_path / "signals.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    out = tmp_path / "health.json"

    payload = build_signal_health(str(path), str(out), min_volume=5)
    by_type = {x["signal_type"]: x for x in payload["signals"]}

    assert by_type["PAYMENT_DELAY_OUTLIER"]["status"] == "EXPERIMENTAL_ZERO"
    assert by_type["PAYMENT_DELAY_OUTLIER"]["signal_count"] == 0
    assert payload["needs_review_signal_types"] >= 1
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == "RIGP-SIGNAL-HEALTH-v1"


def test_dominant_signal_is_flagged_for_review(tmp_path: Path):
    rows = [
        {
            "signal_type": "AMOUNT_OUTLIER",
            "organization_id": "ORG-A",
            "provider_id": f"PRV-{i}",
            "periodo": 2026,
            "severity": "MEDIUM",
        }
        for i in range(95)
    ]
    rows += [
        {
            "signal_type": "PROVIDER_CONCENTRATION",
            "organization_id": "ORG-B",
            "provider_id": f"OTHER-{i}",
            "periodo": 2026,
            "severity": "MEDIUM",
        }
        for i in range(5)
    ]
    path = tmp_path / "signals.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)

    payload = build_signal_health(str(path), str(tmp_path / "health.json"), min_volume=5)
    by_type = {x["signal_type"]: x for x in payload["signals"]}

    assert by_type["AMOUNT_OUTLIER"]["status"] == "DOMINANT_REVIEW"
    assert by_type["PROVIDER_CONCENTRATION"]["status"] == "ACTIVE"
    assert by_type["AMOUNT_OUTLIER"]["share_of_signal_universe"] == 0.95
