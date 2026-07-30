"""Synthetic daily weather: one series per season, shared across every field
active that season -- a farm sees roughly one weather, not one per field.
Autocorrelated via a simple AR(1) latent process so wet/dry and hot/cool
regimes cluster across consecutive days rather than looking like independent
day-to-day noise. This is a synthetic-data generation technique chosen to
make attribution possible (see core/expectation.py), not a meteorological
model -- it makes no claim to match real North Dakota climatology.

Soil available water capacity, which determines how a shared season of
weather affects each field differently, is assigned separately in
`economics.assign_soil_awc`.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime
import io
import math
from typing import TYPE_CHECKING

import numpy as np

from . import rng as rng_mod
from .config import SimConfig
from .field_identity import FarmIdentity

if TYPE_CHECKING:
    from .farm import FarmModel

GROWING_SEASON_START_MONTH_DAY = (5, 1)  # May 1
GROWING_SEASON_DAYS = 153  # through ~Sept 30

_AR1_PHI = 0.6  # day-to-day persistence of the latent weather state
_RAIN_PROB_BASE = 0.35
_RAIN_PROB_SPREAD = 0.15
_RAIN_GAMMA_SHAPE = 2.0
_RAIN_GAMMA_SCALE_MM = 4.0

_TEMP_SEASON_MEAN_C = 19.0
_TEMP_SEASON_AMPLITUDE_C = 8.0  # warmer mid-season than at the shoulders
_TEMP_NOISE_SPREAD_C = 4.0
_TEMP_DIURNAL_HALF_RANGE_C = 8.0


@dataclasses.dataclass(frozen=True)
class DailyWeather:
    date: str
    precip_mm: float
    temp_min_c: float
    temp_max_c: float


@dataclasses.dataclass(frozen=True)
class SeasonWeather:
    season: int
    daily: tuple[DailyWeather, ...]

    @property
    def total_precip_mm(self) -> float:
        return round(sum(d.precip_mm for d in self.daily), 1)

    def heat_stress_days(self, threshold_c: float) -> int:
        return sum(1 for d in self.daily if d.temp_max_c > threshold_c)


def _ar1_series(rng: np.random.Generator, n: int, phi: float = _AR1_PHI) -> np.ndarray:
    eps = rng.standard_normal(n)
    z = np.empty(n)
    z[0] = eps[0]
    for t in range(1, n):
        z[t] = phi * z[t - 1] + math.sqrt(1 - phi**2) * eps[t]
    return z


def _generate_season(config: SimConfig, season: int) -> SeasonWeather:
    days = GROWING_SEASON_DAYS
    start = datetime.date(season, *GROWING_SEASON_START_MONTH_DAY)

    precip_rng = rng_mod.derive_rng(config.random_seed, "weather", "precip", season)
    z_precip = _ar1_series(precip_rng, days)
    rain_prob = np.clip(_RAIN_PROB_BASE + _RAIN_PROB_SPREAD * z_precip, 0.05, 0.9)
    is_rain = precip_rng.random(days) < rain_prob
    amounts = precip_rng.gamma(_RAIN_GAMMA_SHAPE, _RAIN_GAMMA_SCALE_MM, size=days)
    amounts = amounts * (1 + 0.3 * z_precip)
    precip_mm = np.where(is_rain, np.clip(amounts, 0.0, None), 0.0)

    temp_rng = rng_mod.derive_rng(config.random_seed, "weather", "temp", season)
    z_temp = _ar1_series(temp_rng, days)
    day_frac = np.arange(days) / days
    seasonal_mean = _TEMP_SEASON_MEAN_C + _TEMP_SEASON_AMPLITUDE_C * np.sin(math.pi * day_frac)
    daily_mean = seasonal_mean + _TEMP_NOISE_SPREAD_C * z_temp
    temp_max = daily_mean + _TEMP_DIURNAL_HALF_RANGE_C
    temp_min = daily_mean - _TEMP_DIURNAL_HALF_RANGE_C

    daily = tuple(
        DailyWeather(
            date=(start + datetime.timedelta(days=i)).isoformat(),
            precip_mm=round(float(precip_mm[i]), 1),
            temp_min_c=round(float(temp_min[i]), 1),
            temp_max_c=round(float(temp_max[i]), 1),
        )
        for i in range(days)
    )
    return SeasonWeather(season=season, daily=daily)


def build_weather_by_season(config: SimConfig) -> dict[int, SeasonWeather]:
    return {season: _generate_season(config, season) for season in config.seasons}


def force_drought(weather: SeasonWeather, factor: float = 0.35) -> SeasonWeather:
    """Deliberately override a season's precipitation to a fraction of what it
    would otherwise be. Used by DEF-WEATHERSHORTFALL to guarantee a real,
    attributable weather-caused shortfall regardless of --seed -- temperature
    is left untouched, since only the water-deficit channel is being forced.
    """
    scaled_daily = tuple(
        dataclasses.replace(d, precip_mm=round(d.precip_mm * factor, 1)) for d in weather.daily
    )
    return dataclasses.replace(weather, daily=scaled_daily)


def select_drought_season(identity: FarmIdentity, config: SimConfig) -> dict:
    """DEF-WEATHERSHORTFALL's season+representative-field pick. Structural
    (config index + fixed role), not RNG-driven, so it's always present
    regardless of --seed -- same shape as the fixed roster roles in
    field_identity.py. The drought itself affects every field active that
    season (weather is shared); the field named here is only the one the
    attribution test checks.
    """
    seasons = config.seasons
    season = seasons[min(config.weathershortfall_season_index, len(seasons) - 1)]
    field = next(f for f in identity.canonical_fields.values() if f.role == "continuous_corn")
    return {"season": season, "field_id": field.field_id}


_WEATHER_HEADER = ["season", "date", "precip_mm", "temp_min_c", "temp_max_c"]


def build_weather_csv_by_season(farm: "FarmModel") -> dict[int, str]:
    """One CSV per season -- daily weather is season-wide, shared across every
    field active that season, so unlike scale_tickets.py there's no
    field_name column here.
    """
    out: dict[int, str] = {}
    for season, season_weather in farm.weather_by_season.items():
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(_WEATHER_HEADER)
        for day in season_weather.daily:
            writer.writerow([season, day.date, day.precip_mm, day.temp_min_c, day.temp_max_c])
        out[season] = buf.getvalue()
    return out


_SOIL_AWC_HEADER = ["field_name", "awc_in"]


def build_soil_awc_csv(farm: "FarmModel") -> str:
    """One row per field, keyed by its current (most recent active season's)
    display name -- AWC is a static soil property, not season-indexed, so
    unlike every other raw file here there's no naming drift to preserve.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_SOIL_AWC_HEADER)
    for field_id, field in sorted(farm.identity.canonical_fields.items()):
        if field_id not in farm.soil_awc_by_field:
            continue
        latest_season = field.active_seasons[-1]
        name = field.display_name_by_season[latest_season]
        writer.writerow([name, farm.soil_awc_by_field[field_id]])
    return buf.getvalue()
