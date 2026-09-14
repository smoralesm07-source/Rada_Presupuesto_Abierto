from __future__ import annotations

"""Two horizons, not one: what can still be acted on, and what can only teach.

A finding from 2018 and a finding from this year are not the same product. The
old one cannot realistically be pursued — the contract closed, the officials
moved, the documents may no longer be retrievable — but it is exactly what a
baseline needs: it says what normal looked like before.

So the radar keeps two windows.

**Ventana de acción.** Only relations inside it can become an expediente. This
is the bandeja.

**Ventana de aprendizaje.** Everything from the first processed year onward,
including the action window. It never reaches the bandeja; it feeds prevalence,
peer medians, provider first appearance and capacity baselines.

Mixing them is what made `NEW_TO_SERIES_HIGH_SPEND` meaningless: "new" was
defined as "not present in the processed series", so a supplier active since
2015 looked new the moment the series started in 2024. With the windows split,
"new" means new *against the baseline*, and the signal reports how many years of
baseline actually back that claim.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone

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

GUARDRAIL = (
    "La ventana de acción delimita qué puede trabajarse hoy, no qué es más grave. "
    "Un patrón en la ventana de aprendizaje no es menos relevante: es menos accionable, "
    "y por eso alimenta la línea base en vez de la bandeja."
)


@dataclass(frozen=True)
class AnalysisWindows:
    """Where the action window starts and how far back the baseline reaches."""

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

    def baseline_years(self, available_years: list[int] | set[int]) -> int:
        """Years of history that sit *before* the action window.

        This is what gives a "new supplier" claim its strength. With zero
        baseline years the claim is not wrong, it is unsupported, and the signal
        has to say so instead of asserting novelty.
        """
        return len({
            int(y) for y in available_years
            if self.learning_from_year <= int(y) < self.action_from_year
        })

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
        """Whether this can still be worked, and what limits it."""
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
        if months is not None and months >= self.evidence_horizon_months:
            return {
                "window": window,
                "state": EVIDENCE_AT_RISK,
                "months_since_activity": months,
                "why": (
                    f"Última actividad hace {months:.0f} meses, por sobre el horizonte de "
                    f"evidencia configurado ({self.evidence_horizon_months}). Conviene confirmar "
                    "disponibilidad documental antes de comprometer trabajo."
                ),
            }
        if months is not None and months >= self.evidence_warning_months:
            return {
                "window": window,
                "state": EVIDENCE_AT_RISK,
                "months_since_activity": months,
                "why": (
                    f"Última actividad hace {months:.0f} meses; se acerca al horizonte de "
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

    def describe(self) -> dict:
        return {
            "action_from_year": self.action_from_year,
            "learning_from_year": self.learning_from_year,
            "evidence_horizon_months": self.evidence_horizon_months,
            "evidence_warning_months": self.evidence_warning_months,
            "evidence_horizon_note": EVIDENCE_HORIZON_NOTE,
            "guardrail": GUARDRAIL,
            "window_labels": WINDOW_LABEL,
            "actionability_labels": ACTIONABILITY_LABEL,
            "meaning": {
                WINDOW_ACTION: (
                    "Sólo estas relaciones pueden convertirse en expediente."
                ),
                WINDOW_LEARNING: (
                    "Alimenta prevalencia, medianas de pares, primera aparición de proveedor "
                    "y calibración. Nunca llega a la bandeja."
                ),
            },
        }

    def sql_action_filter(self, column: str = "periodo") -> str:
        return f"try_cast({column} AS INTEGER) >= {int(self.action_from_year)}"

    def sql_learning_filter(self, column: str = "periodo") -> str:
        return f"try_cast({column} AS INTEGER) >= {int(self.learning_from_year)}"


DEFAULT_WINDOWS = AnalysisWindows()


def from_config(config: dict | None) -> AnalysisWindows:
    cfg = (config or {}).get("analysis_windows", config or {})
    return AnalysisWindows(
        action_from_year=int(cfg.get("action_from_year", DEFAULT_WINDOWS.action_from_year)),
        learning_from_year=int(cfg.get("learning_from_year", DEFAULT_WINDOWS.learning_from_year)),
        evidence_horizon_months=int(
            cfg.get("evidence_horizon_months", DEFAULT_WINDOWS.evidence_horizon_months)
        ),
        evidence_warning_months=int(
            cfg.get("evidence_warning_months", DEFAULT_WINDOWS.evidence_warning_months)
        ),
    )
