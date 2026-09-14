from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .analysis_window import describe_window
from .pattern_compatibility import CORROBORATION_NOTE
from .pattern_compatibility import GUARDRAIL as PATTERN_GUARDRAIL
from .pattern_compatibility import PROFILES as PATTERN_PROFILES
from .pattern_compatibility import score_pattern_compatibility
from .peer_groups import build_provider_peer_context
from .procurement_context import build_procurement_context
from .publication_selection import rebalance_findings_publication
from .signal_health import build_signal_health


PRIORITY_GUARDRAIL = (
    "La prioridad de revisión ordena dónde conviene mirar primero. "
    "No mide culpabilidad, corrupción, fraude, delito funcionario ni probabilidad de un ilícito."
)

PEER_GUARDRAIL = (
    "La posición frente a pares compara materialidad dentro del mismo organismo, año, subtítulo e ítem. "
    "No reemplaza el análisis de mercado, modalidad de compra, contrato o necesidad pública."
)


def _peer_map(peer_parquet: str) -> dict[tuple[str, str, int], dict]:
    path = Path(peer_parquet)
    if not path.exists():
        return {}
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT
          organization_id,
          provider_id,
          periodo,
          peer_group_id,
          subtitulo,
          item,
          provider_amount,
          transaction_count,
          peer_provider_count,
          peer_median_amount,
          peer_p90_amount,
          peer_p99_amount,
          peer_percentile,
          amount_to_peer_median_ratio,
          peer_position
        FROM read_parquet('{path.as_posix()}')
        """
    ).fetchall()
    con.close()

    out: dict[tuple[str, str, int], dict] = {}
    for row in rows:
        (
            organization_id,
            provider_id,
            periodo,
            peer_group_id,
            subtitulo,
            item,
            provider_amount,
            transaction_count,
            peer_provider_count,
            peer_median_amount,
            peer_p90_amount,
            peer_p99_amount,
            peer_percentile,
            amount_to_peer_median_ratio,
            peer_position,
        ) = row
        key = (str(organization_id or ""), str(provider_id or ""), int(periodo or 0))
        if not all(key):
            continue
        out[key] = {
            "peer_group_id": peer_group_id,
            "subtitulo": subtitulo,
            "item": item,
            "provider_amount": float(provider_amount or 0),
            "transaction_count": int(transaction_count or 0),
            "peer_provider_count": int(peer_provider_count or 0),
            "peer_median_amount": float(peer_median_amount or 0),
            "peer_p90_amount": float(peer_p90_amount or 0),
            "peer_p99_amount": float(peer_p99_amount or 0),
            "peer_percentile_pct": round(float(peer_percentile or 0) * 100, 1),
            "amount_to_peer_median_ratio": (
                round(float(amount_to_peer_median_ratio), 3)
                if amount_to_peer_median_ratio is not None
                else None
            ),
            "peer_position": str(peer_position or ""),
            "guardrail": PEER_GUARDRAIL,
        }
    return out


def annotate_published_findings(
    findings_json: str = "docs/data/investigative_findings.json",
    peer_parquet: str = "data/processed/provider_peer_context.parquet",
    years: list[int] | None = None,
) -> dict:
    """Attach compact peer and descriptive pattern context to the published findings.

    This deliberately keeps investigation priority separate from descriptive pattern
    compatibility. The former sorts work; the latter tells the analyst which review
    hypothesis best matches the observed signal combination.
    """
    path = Path(findings_json)
    if not path.exists():
        raise FileNotFoundError(findings_json)

    payload = json.loads(path.read_text(encoding="utf-8"))
    peers = _peer_map(peer_parquet)
    relations = payload.get("relation_findings") or []

    peer_matches = 0
    pattern_matches = 0
    similarity_only = 0
    observed_years: set[int] = set()
    for row in relations:
        try:
            year = int(row.get("periodo"))
            observed_years.add(year)
        except (TypeError, ValueError):
            year = 0

        compatibility = [
            x for x in score_pattern_compatibility(row.get("signal_types") or [])
            if int(x.get("compatibility_score") or 0) > 0
        ]
        # La hipótesis principal exige corroboración: dos patrones concurrentes.
        # Con el umbral de score a secas, un PROVIDER_CONCENTRATION solitario
        # bastaba para proponer una tipología.
        primary = next(
            (
                x for x in compatibility
                if x.get("corroborated") and int(x.get("compatibility_score") or 0) >= 40
            ),
            None,
        )
        if primary:
            pattern_matches += 1

        key = (
            str(row.get("organization_id") or ""),
            str(row.get("provider_id") or ""),
            year,
        )
        peer = peers.get(key)
        if peer:
            peer_matches += 1

        row["review_priority"] = {
            "score": float(row.get("max_priority_score") or 0),
            "attention_level": row.get("attention_level") or "SEGUIMIENTO",
            "guardrail": PRIORITY_GUARDRAIL,
        }
        if not primary and compatibility:
            # Sin corroborar no se propone hipótesis, pero tampoco se borra el
            # parecido: queda en `pattern_compatibility` con su estado, para que el
            # analista vea a qué se parece y qué le falta para sostenerse.
            similarity_only += 1

        row["primary_pattern"] = primary
        row["pattern_compatibility"] = compatibility[:2]
        row["peer_context"] = peer

    effective_years = sorted({int(y) for y in (years or observed_years)})
    payload["analysis_window"] = describe_window(effective_years)
    # El texto de cada perfil --qué lo descarta, qué documento pedir-- es idéntico
    # en todas las filas. Vive una vez a nivel de payload, como el guardrail.
    payload["pattern_profiles"] = [
        {
            "pattern_code": profile.code,
            "pattern_label": profile.label,
            "pattern_description": profile.description,
            "review_question": profile.review_question,
            "discards": list(profile.discards),
            "next_document": profile.next_document,
        }
        for profile in PATTERN_PROFILES
    ]
    payload["corroboration_rule"] = CORROBORATION_NOTE
    payload["interpretation_contract"] = {
        "review_priority": PRIORITY_GUARDRAIL,
        "pattern_compatibility": PATTERN_GUARDRAIL,
        "peer_context": PEER_GUARDRAIL,
        "separation_rule": (
            "Prioridad, compatibilidad de patrón y posición frente a pares son dimensiones distintas. "
            "Ninguna se interpreta como probabilidad de delito ni reemplaza verificación documental."
        ),
    }
    payload["context_coverage"] = {
        "published_relations": len(relations),
        "relations_with_peer_context": peer_matches,
        "relations_with_primary_pattern": pattern_matches,
        # Relaciones que se parecen a un perfil pero con un solo patrón: no son
        # hipótesis todavía. Si este número domina, el radar está viendo una capa
        # de señales, no convergencia, y eso hay que verlo en la corrida.
        "relations_with_uncorroborated_similarity": similarity_only,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload["context_coverage"]


def build_operational_bundle(
    parquet_glob: str,
    years: list[int] | None = None,
    findings_json: str = "docs/data/investigative_findings.json",
    output_json: str = "docs/data/operational_bundle.json",
    max_published_findings: int = 600,
    reserve_per_signal: int = 20,
) -> dict:
    """Build the bounded analytical products used by the case-first RIGP pilot."""
    peer = build_provider_peer_context(parquet_glob)
    signal_health = build_signal_health()
    publication = rebalance_findings_publication(
        payload_json=findings_json,
        max_rows=max_published_findings,
        reserve_per_signal=reserve_per_signal,
    )
    coverage = annotate_published_findings(
        findings_json=findings_json,
        peer_parquet=peer["path"],
        years=years,
    )
    procurement = build_procurement_context(
        parquet_glob,
        findings_json=findings_json,
    )

    window = describe_window(sorted({int(y) for y in (years or [])}))
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": "RIGP-OPERATIONAL-BUNDLE-v1",
        "analysis_window": window,
        "publication": publication,
        "signal_health": {
            "total_signals": signal_health["total_signals"],
            "active_signal_types": signal_health["active_signal_types"],
            "needs_review_signal_types": signal_health["needs_review_signal_types"],
            "statuses": {
                row["signal_type"]: row["status"]
                for row in signal_health["signals"]
            },
        },
        "peer_context": peer,
        "finding_context_coverage": coverage,
        "procurement_context": procurement,
        "interpretation": (
            "El bundle separa prioridad de revisión, compatibilidad descriptiva de patrón, "
            "materialidad frente a pares y contexto de contratación. Ninguna capa acredita irregularidad o delito."
        ),
    }
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary
