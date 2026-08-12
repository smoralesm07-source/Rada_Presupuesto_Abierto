from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import duckdb


def build_dashboard_json(parquet_glob: str, signals_path: str, output: str = "docs/data/dashboard.json", top_n: int = 250) -> dict:
    con=duckdb.connect(); con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}',union_by_name=true)")
    metrics=con.execute("""SELECT count(*),count(DISTINCT organization_id),count(DISTINCT recipient_id),count(DISTINCT provider_id) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''),coalesce(sum(try_cast(monto_devengado AS DOUBLE)),0),min(periodo),max(periodo) FROM facts""").fetchone()
    signals=[]; sig_count=0; sig_types={}
    if Path(signals_path).exists():
        con.execute(f"CREATE OR REPLACE VIEW sig AS SELECT * FROM read_parquet('{signals_path}')"); sig_count=con.execute("SELECT count(*) FROM sig").fetchone()[0]; sig_types=dict(con.execute("SELECT signal_type,count(*) FROM sig GROUP BY 1 ORDER BY 2 DESC").fetchall()); df=con.execute(f"SELECT * FROM sig ORDER BY CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,coalesce(deviation,0) DESC LIMIT {int(top_n)}").df(); signals=df.where(df.notna(),None).to_dict("records")
    payload={"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"metrics":{"transactions":int(metrics[0]),"organizations":int(metrics[1]),"recipients":int(metrics[2]),"providers":int(metrics[3]),"amount_clp":float(metrics[4]),"first_year":None if metrics[5] is None else int(metrics[5]),"last_year":None if metrics[6] is None else int(metrics[6]),"signals":int(sig_count)},"signal_types":sig_types,"signals":signals,"methodology_note":"Las señales son patrones estadísticos para priorizar revisión; no constituyen hallazgos de ilegalidad ni imputaciones AML. Proveedor y receptor se modelan por separado."}
    out=Path(output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding="utf-8"); con.close(); return payload
