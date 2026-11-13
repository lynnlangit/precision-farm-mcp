"""The two example farms the grower web app can switch between.

Both are the same twelve fields over the same ten seasons, from the same
seed, so every true profit figure is identical. Only the record keeping
differs:

- Farm 1, clean records: what the farm's files look like when nothing went
  wrong. Every record agrees with every other.
- Farm 2, messy records: the default data/synthetic/ farm, with the mistakes
  real records have -- a mistyped seed cost, yield monitors out of
  calibration, a GPS dropout, a field name spelled five ways, a cost tab in
  total dollars instead of $/ac, and more (see data/synthetic/README.md).

Asking the same question of both farms shows what the checks are for: on
Farm 1 they pass quietly; on Farm 2 they catch the problems.

A farm is only a data directory plus its confirmed-mappings file; the MCP
servers read both from FARM_DATA_DIR / FARM_CONFIRM_STORE, so switching farms
means talking to servers started with a different environment.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclasses.dataclass(frozen=True)
class Farm:
    key: str
    name: str  # "Farm 1"
    records: str  # "clean records"
    blurb: str  # one sentence for growers
    data_dir: Path
    confirm_store: Path
    generate_cmd: str
    ingest_cmd: str

    @property
    def label(self) -> str:
        return f"{self.name} · {self.records}"

    def server_env(self) -> dict[str, str]:
        return {
            "FARM_DATA_DIR": str(self.data_dir),
            "FARM_CONFIRM_STORE": str(self.confirm_store),
        }


FARMS: dict[str, Farm] = {
    "farm1": Farm(
        key="farm1",
        name="Farm 1",
        records="clean records",
        blurb="Every record agrees with every other, so the checks pass quietly.",
        data_dir=REPO_ROOT / "data" / "synthetic-clean",
        confirm_store=REPO_ROOT / "data" / "confirmed_mappings_clean.json",
        generate_cmd=(
            "uv run --project generator python -m farm_data_gen.cli "
            "--seed 42 --clean --out data/synthetic-clean"
        ),
        ingest_cmd=(
            "uv run --project host farm-ingest --auto-approve-synthetic-only "
            "--data-dir data/synthetic-clean --confirm-store data/confirmed_mappings_clean.json"
        ),
    ),
    "farm2": Farm(
        key="farm2",
        name="Farm 2",
        records="messy records",
        blurb=(
            "The same fields, with the mistakes real records have: a mistyped seed cost, "
            "a yield monitor out of calibration, a field name spelled five ways."
        ),
        data_dir=REPO_ROOT / "data" / "synthetic",
        confirm_store=REPO_ROOT / "data" / "confirmed_mappings.json",
        generate_cmd="uv run --project generator python -m farm_data_gen.cli --seed 42 --out data/synthetic",
        ingest_cmd="uv run --project host farm-ingest --auto-approve-synthetic-only",
    ),
}

DEFAULT_FARM = "farm1"
