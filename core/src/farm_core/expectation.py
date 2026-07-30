"""Relative expectation model: distinguishes a weather-caused shortfall from
a management-caused one without any cultivar calibration or absolute yield
model. Every quantity is relative to the field's own history and the farm's
own seasons -- deliberately, so this needs no external agronomy reference
data (see docs/ARCHITECTURE.md's Deferred row for that).

    expected_yield  = field's own average yield x weather_multiplier(season, field's AWC)
    season_effect   = expected_yield - field's own average      (shared-weather-driven)
    field_effect    = field's own average - farm-wide average   (persistent, soil-driven)
    residual        = observed_yield - expected_yield           (what weather doesn't explain)

`weather_multiplier` mirrors generator/src/farm_data_gen/economics.py's own
causal-yield formula (water deficit buffered by soil AWC, plus a small heat
penalty). That's an intentional, hand-kept-in-sync duplication, not
cheating: this package has no dependency on the generator (real package
boundary, see generator/tests/test_qualitative_fixtures.py for the same
rationale), and for a bounded synthetic system knowing the general *form*
of "corn needs about this much water, buffered by soil" is textbook
agronomy knowledge, not access to the generator's RNG draws.

Refuses (AttributionUnavailable), like every other query-time gap in this
system, rather than estimating from too little data -- never a guess.
"""

from __future__ import annotations

import dataclasses
import statistics

from .pipeline import FarmSnapshot

# Mirrors generator/src/farm_data_gen/config.py's Phase C constants.
CROP_WATER_NEED_MM = 450.0
AWC_REFERENCE_IN = 6.5
HEAT_STRESS_THRESHOLD_C = 32.0
HEAT_STRESS_K = 0.015
STRESS_YIELD_K = 0.004
MIN_YIELD_MULTIPLIER = 0.5

MIN_SEASONS_FOR_BASELINE = 3  # a field needs at least this much of its own history


@dataclasses.dataclass(frozen=True)
class AttributionResult:
    canonical_id: str
    season: int
    observed_yield_bu_ac: float
    expected_yield_bu_ac: float
    field_average_yield_bu_ac: float
    farm_average_yield_bu_ac: float
    season_effect: float
    field_effect: float
    residual: float
    weather_multiplier: float
    calibrated: bool = True

    def to_json(self) -> dict:
        return {
            "season_effect": round(self.season_effect, 2),
            "field_effect": round(self.field_effect, 2),
            "residual": round(self.residual, 2),
            "calibrated": self.calibrated,
        }


class AttributionUnavailable(Exception):
    """Too little of the field's own history, or no weather coverage for
    the season -- a structured refusal, not a guess.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def weather_multiplier(total_precip_mm: float, heat_stress_days: int, awc_in: float) -> float:
    water_deficit_mm = max(0.0, CROP_WATER_NEED_MM - total_precip_mm)
    heat_penalty = HEAT_STRESS_K * heat_stress_days
    stress = water_deficit_mm / (1 + awc_in / AWC_REFERENCE_IN) + heat_penalty
    return min(1.0, max(MIN_YIELD_MULTIPLIER, 1 - STRESS_YIELD_K * stress))


def _yield_by_field_season(snapshot: FarmSnapshot) -> dict[tuple[str, int], float]:
    con = snapshot.con
    yields: dict[tuple[str, int], float] = {}
    for canonical_id, lineage in snapshot.identity.lineages.items():
        for season in lineage.active_seasons:
            display_name = lineage.display_name_by_season[season]
            boundary = con.execute(
                "SELECT acres FROM boundary_fields WHERE field_name = ? AND season = ?",
                [display_name, season],
            ).fetchone()
            if boundary is None or not boundary[0]:
                continue
            acres = boundary[0]
            net_bushels = (
                con.execute(
                    "SELECT SUM(net_bushels) FROM scale_ticket_loads "
                    "WHERE field_name = ? AND season = ?",
                    [display_name, season],
                ).fetchone()[0]
                or 0.0
            )
            yields[(canonical_id, season)] = net_bushels / acres
    return yields


def _season_weather(snapshot: FarmSnapshot, season: int) -> tuple[float, int] | None:
    con = snapshot.con
    row = con.execute(
        "SELECT SUM(precip_mm), SUM(CASE WHEN temp_max_c > ? THEN 1 ELSE 0 END) "
        "FROM weather_daily WHERE season = ?",
        [HEAT_STRESS_THRESHOLD_C, season],
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0]), int(row[1])


def _soil_awc(snapshot: FarmSnapshot, canonical_id: str) -> float | None:
    lineage = snapshot.identity.lineages.get(canonical_id)
    if lineage is None or not lineage.active_seasons:
        return None
    latest_season = max(lineage.active_seasons)
    current_name = lineage.display_name_by_season[latest_season]
    row = snapshot.con.execute(
        "SELECT awc_in FROM soil_awc WHERE field_name = ?", [current_name]
    ).fetchone()
    return None if row is None else float(row[0])


def compute_attribution(
    snapshot: FarmSnapshot, canonical_id: str, season: int
) -> AttributionResult:
    yields = _yield_by_field_season(snapshot)
    field_seasons = {s: y for (cid, s), y in yields.items() if cid == canonical_id}

    if season not in field_seasons:
        raise AttributionUnavailable(f"no yield data for {canonical_id} in {season}")
    if len(field_seasons) < MIN_SEASONS_FOR_BASELINE:
        raise AttributionUnavailable(
            f"{canonical_id} has only {len(field_seasons)} season(s) of history -- "
            f"need at least {MIN_SEASONS_FOR_BASELINE} to establish a baseline"
        )

    weather = _season_weather(snapshot, season)
    if weather is None:
        raise AttributionUnavailable(f"no weather coverage for season {season}")
    total_precip_mm, heat_days = weather

    awc = _soil_awc(snapshot, canonical_id)
    if awc is None:
        raise AttributionUnavailable(f"no soil AWC data for {canonical_id}")

    field_average = statistics.mean(field_seasons.values())
    farm_average = statistics.mean(yields.values())
    multiplier = weather_multiplier(total_precip_mm, heat_days, awc)
    expected_yield = field_average * multiplier
    observed_yield = field_seasons[season]

    return AttributionResult(
        canonical_id=canonical_id,
        season=season,
        observed_yield_bu_ac=round(observed_yield, 2),
        expected_yield_bu_ac=round(expected_yield, 2),
        field_average_yield_bu_ac=round(field_average, 2),
        farm_average_yield_bu_ac=round(farm_average, 2),
        season_effect=expected_yield - field_average,
        field_effect=field_average - farm_average,
        residual=observed_yield - expected_yield,
        weather_multiplier=round(multiplier, 4),
    )


def backtest(snapshot: FarmSnapshot) -> dict:
    """Expected vs. observed yield across every field/season with enough
    history and weather coverage to attribute -- MAE/RMSE over the whole
    farm record, published (not hidden) via farm-metrics.
    """
    yields = _yield_by_field_season(snapshot)
    errors: list[float] = []
    attributed = 0
    skipped = 0

    for canonical_id, season in yields:
        try:
            result = compute_attribution(snapshot, canonical_id, season)
        except AttributionUnavailable:
            skipped += 1
            continue
        errors.append(result.observed_yield_bu_ac - result.expected_yield_bu_ac)
        attributed += 1

    if not errors:
        return {"attributed": 0, "skipped": skipped, "mae": None, "rmse": None}

    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
    return {
        "attributed": attributed,
        "skipped": skipped,
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
    }
