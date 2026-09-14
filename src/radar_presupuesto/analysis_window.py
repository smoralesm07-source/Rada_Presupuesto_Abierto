from __future__ import annotations

"""Dos horizontes, no uno: lo que todavía se puede trabajar y lo que sólo enseña.

Un hallazgo de 2018 y uno de este año no son el mismo producto. El viejo no se
puede perseguir razonablemente —el contrato cerró, los funcionarios rotaron, el
respaldo documental puede ya no obtenerse— pero es exactamente lo que una línea
base necesita: dice cómo se veía lo normal antes.

**Ventana de acción.** Sólo estas relaciones pueden convertirse en expediente.
Es la bandeja.

**Ventana de aprendizaje.** Todo lo procesado desde el primer año, la ventana de
acción incluida. Nunca llega a la bandeja; alimenta prevalencia, medianas de
pares, primera aparición del proveedor y calibración.

Mezclarlas es lo que dejaba sin sentido a `NEW_TO_SERIES_HIGH_SPEND`: «nuevo»
significaba «no presente en la serie procesada», así que un proveedor activo
desde 2016 parecía nuevo apenas la serie empezaba en 2020. Con las ventanas
separadas, «nuevo» se mide contra la línea base, y la señal informa cuántos años
de base respaldan efectivamente esa afirmación.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

AVAILABLE_STATUSES = {"linked", "linked_available", "probed_available"}

WINDOW_ACTION = "ACCION"
WINDOW_LEARNING = "APRENDIZAJE"
WINDOW_OUT_OF_SERIES = "FUERA_DE_SERIE"

ACTIONABLE = "ACCIONABLE"
EVIDENCE_AT_RISK = "EVIDENCIA_EN_RIESGO"
LEARNING_ONLY = "SOLO_APRENDIZAJE"

WINDOW_LABEL = {
    WINDOW_ACTION: "Ventana de acción",
    WINDOW_LEARNING: "Sólo aprendizaje",
    WINDOW_OUT_OF_SERIES: "Fuera de la serie",
}

ACTIONABILITY_LABEL = {
    ACTIONABLE: "Accionable",
    EVIDENCE_AT_RISK: "Evidencia en riesgo",
    LEARNING_ONLY: "Sólo aprendizaje",
}

# El horizonte de evidencia es operativo, no jurídico: describe hasta cuándo es
# razonable esperar obtener respaldo documental de una contratación. No afirma
# plazos de prescripción ni de conservación legal, que dependen de la norma
# aplicable y deben fijarse contra ella.
EVIDENCE_HORIZON_NOTE = (
    "El horizonte de evidencia es un supuesto operativo sobre la obtenibilidad práctica "
    "del respaldo documental, configurable en config/analysis_windows.yaml. No es un plazo "
    "de prescripción ni de conservación legal."
)

WINDOW_GUARDRAIL = (
    "La ventana de acción delimita qué puede trabajarse hoy, no qué es más grave. "
    "Un patrón en la ventana de aprendizaje no es menos relevante: es menos accionable, "
    "y por eso alimenta la línea base en vez de la bandeja."
)


def resolve_analysis_years(
    catalog_path: str = "docs/data/source_catalog.json",
    requested: str | None = None,
    window_years: int = 7,
    min_years: int = 5,
) -> list[int]:
    """Resolve a stable historical window for RIGP analytics.

    Three years are insufficient for labels such as ``NEW_TO_SERIES_HIGH_SPEND``
    and make historical concentration comparisons fragile. The default therefore
    uses the latest seven confirmed bulk years, while refusing to silently operate
    with fewer than five unless years were explicitly requested by an operator.
    """
    if requested and requested.strip():
        years = sorted({int(x) for x in requested.replace(",", " ").split() if x.strip()})
        if not years:
            raise ValueError("requested years is empty after parsing")
        return years

    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    years = sorted(
        {
            int(row["year"])
            for row in catalog.get("downloads", [])
            if row.get("status") in AVAILABLE_STATUSES and row.get("year") is not None
        }
    )
    if len(years) < min_years:
        raise RuntimeError(
            f"RIGP requires at least {min_years} confirmed years for its default historical window; found {len(years)}"
        )
    if window_years <= 0:
        return years
    return years[-window_years:]


def describe_window(years: list[int]) -> dict:
    if not years:
        return {"years": [], "year_count": 0, "first_year": None, "last_year": None}
    ordered = sorted(set(int(y) for y in years))
    return {
        "years": ordered,
        "year_count": len(ordered),
        "first_year": ordered[0],
        "last_year": ordered[-1],
        "historical_depth_years": ordered[-1] - ordered[0] + 1,
    }


@dataclass(frozen=True)
class AnalysisWindows:
    """Dónde empieza la ventana de acción y hasta dónde llega la línea base."""

    action_from_year: int = 2023
    learning_from_year: int = 2016
    evidence_horizon_months: int = 60
    evidence_warning_months: int = 42

    def __post_init__(self) -> None:
        if self.learning_from_year > self.action_from_year:
            raise ValueError(
                "la ventana de aprendizaje debe comenzar antes o junto con la de acción; "
                f"recibidas aprendizaje={self.learning_from_year}, acción={self.action_from_year}"
            )
        if self.evidence_warning_months > self.evidence_horizon_months:
            raise ValueError(
                "el aviso de evidencia en riesgo debe ocurrir antes del horizonte, no después"
            )

    def window_of(self, year: object) -> str:
        try:
            value = int(year)
        except (TypeError, ValueError):
            return WINDOW_OUT_OF_SERIES
        if value >= self.action_from_year:
            return WINDOW_ACTION
        if value >= self.learning_from_year:
            return WINDOW_LEARNING
        return WINDOW_OUT_OF_SERIES

    def is_actionable(self, year: object) -> bool:
        return self.window_of(year) == WINDOW_ACTION

    def in_learning(self, year: object) -> bool:
        return self.window_of(year) in {WINDOW_ACTION, WINDOW_LEARNING}

    def baseline_years(self, available_years: object) -> int:
        """Años de historia que quedan *antes* de la ventana de acción.

        Es lo que le da fuerza a una afirmación de «proveedor nuevo». Con cero
        años de base la afirmación no es falsa: está sin respaldo, y la señal
        tiene que decirlo en vez de afirmar novedad.
        """
        years = set()
        for y in available_years or []:
            try:
                years.add(int(y))
            except (TypeError, ValueError):
                continue
        return len([y for y in years if self.learning_from_year <= y < self.action_from_year])

    def months_since(self, moment: object, reference: date | None = None) -> float | None:
        if moment in (None, ""):
            return None
        if isinstance(moment, datetime):
            value = moment.date()
        elif isinstance(moment, date):
            value = moment
        else:
            try:
                value = datetime.fromisoformat(str(moment)[:19]).date()
            except ValueError:
                return None
        today = reference or datetime.now(timezone.utc).date()
        return (today - value).days / 30.4375

    def actionability(
        self, year: object, last_activity: object = None, reference: date | None = None
    ) -> dict:
        """Si esto todavía se puede trabajar, y qué lo limita."""
        window = self.window_of(year)
        months = self.months_since(last_activity, reference=reference)
        if window != WINDOW_ACTION:
            return {
                "window": window,
                "state": LEARNING_ONLY,
                "months_since_activity": months,
                "why": (
                    f"El periodo {year} queda fuera de la ventana de acción "
                    f"(desde {self.action_from_year}). Alimenta la línea base, no la bandeja."
                ),
            }
        if months is not None and months >= self.evidence_warning_months:
            horizon = months >= self.evidence_horizon_months
            return {
                "window": window,
                "state": EVIDENCE_AT_RISK,
                "months_since_activity": months,
                "why": (
                    f"Última actividad hace {months:.0f} meses, por sobre el horizonte de "
                    f"evidencia configurado ({self.evidence_horizon_months}). Conviene confirmar "
                    "disponibilidad documental antes de comprometer trabajo."
                    if horizon
                    else f"Última actividad hace {months:.0f} meses; se acerca al horizonte de "
                    f"evidencia ({self.evidence_horizon_months} meses)."
                ),
            }
        return {
            "window": window,
            "state": ACTIONABLE,
            "months_since_activity": months,
            "why": (
                "Dentro de la ventana de acción y del horizonte de evidencia."
                if months is not None
                else "Dentro de la ventana de acción; sin fecha de última actividad publicada."
            ),
        }

    def describe(self, available_years: object = None) -> dict:
        out = {
            "action_from_year": self.action_from_year,
            "learning_from_year": self.learning_from_year,
            "evidence_horizon_months": self.evidence_horizon_months,
            "evidence_warning_months": self.evidence_warning_months,
            "evidence_horizon_note": EVIDENCE_HORIZON_NOTE,
            "guardrail": WINDOW_GUARDRAIL,
            "window_labels": WINDOW_LABEL,
            "actionability_labels": ACTIONABILITY_LABEL,
            "meaning": {
                WINDOW_ACTION: "Sólo estas relaciones pueden convertirse en expediente.",
                WINDOW_LEARNING: (
                    "Alimenta prevalencia, medianas de pares, primera aparición de proveedor "
                    "y calibración. Nunca llega a la bandeja."
                ),
            },
        }
        if available_years is not None:
            baseline = self.baseline_years(available_years)
            out["baseline_years_available"] = baseline
            # Una línea base vacía no invalida el radar, pero sí toda afirmación
            # de novedad. Decirlo es lo que permite leer bien esas señales.
            out["baseline_status"] = "SIN_LINEA_BASE" if baseline == 0 else "CON_LINEA_BASE"
        return out

    def sql_action_filter(self, column: str = "periodo") -> str:
        return f"try_cast({column} AS INTEGER) >= {int(self.action_from_year)}"

    def sql_learning_filter(self, column: str = "periodo") -> str:
        return f"try_cast({column} AS INTEGER) >= {int(self.learning_from_year)}"


def load_windows(path: str = "config/analysis_windows.yaml") -> AnalysisWindows:
    """Lee las ventanas desde configuración; los valores por defecto son el contrato."""
    p = Path(path)
    if not p.exists():
        return AnalysisWindows()
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    windows = cfg.get("windows", cfg) or {}
    defaults = AnalysisWindows()
    return AnalysisWindows(
        action_from_year=int(windows.get("action_from_year", defaults.action_from_year)),
        learning_from_year=int(windows.get("learning_from_year", defaults.learning_from_year)),
        evidence_horizon_months=int(windows.get("evidence_horizon_months", defaults.evidence_horizon_months)),
        evidence_warning_months=int(windows.get("evidence_warning_months", defaults.evidence_warning_months)),
    )
