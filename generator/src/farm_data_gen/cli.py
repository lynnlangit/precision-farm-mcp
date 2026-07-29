"""Single CLI entry point for the synthetic farm data generator.

uv run python -m farm_data_gen.cli --seed 42 --fields 12 --seasons 10 --out data/synthetic
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .as_applied import build_as_applied_files
from .boundaries import build_boundaries_by_season
from .config import SimConfig
from .cost_ledger import build_cost_ledger_workbook
from .defects import plan_defects
from .farm import build_farm
from .ground_truth import build_ground_truth
from .readme import render_readme
from .scale_tickets import build_scale_tickets_by_season
from .writer import write_json, write_text, write_workbook
from .yield_monitor import build_yield_monitor_files


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="farm-data-gen",
        description="Deterministic synthetic data generator for Precision Farm MCP.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Master RNG seed (default: 42)")
    parser.add_argument(
        "--fields", type=int, default=12, help="Number of root fields (default: 12, min 10)"
    )
    parser.add_argument(
        "--seasons", type=int, default=10, help="Number of seasons starting 2016 (default: 10)"
    )
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"), help="Output directory")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional JSON file overriding SimConfig fields (e.g. yield/cost ranges)",
    )
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> SimConfig:
    config = SimConfig(random_seed=args.seed, num_fields=args.fields, num_seasons=args.seasons)
    if args.config is not None:
        overrides = json.loads(args.config.read_text(encoding="utf-8"))
        valid_fields = {f.name for f in dataclasses.fields(SimConfig)}
        unknown = set(overrides) - valid_fields
        if unknown:
            raise ValueError(f"Unknown SimConfig field(s) in --config: {sorted(unknown)}")
        config = config.with_overrides(**overrides)
    return config


def generate(config: SimConfig, out_dir: Path) -> None:
    farm = build_farm(config)
    plan = plan_defects(farm)

    boundaries_by_season = build_boundaries_by_season(farm)
    for season, geojson in boundaries_by_season.items():
        write_json(out_dir / "boundaries" / f"field_boundaries_{season}.geojson", geojson)

    scale_tickets_by_season = build_scale_tickets_by_season(farm)
    for season, csv_text in scale_tickets_by_season.items():
        write_text(out_dir / "scale_tickets" / f"scale_tickets_{season}.csv", csv_text)

    yield_monitor_files, ym_defects = build_yield_monitor_files(farm, plan)
    for _key, (filename, csv_text) in sorted(yield_monitor_files.items()):
        write_text(out_dir / "yield_monitor" / filename, csv_text)

    as_applied_files, aa_defects = build_as_applied_files(farm, plan)
    for _season, (filename, csv_text) in sorted(as_applied_files.items()):
        write_text(out_dir / "as_applied" / filename, csv_text)

    cost_wb, cl_defects = build_cost_ledger_workbook(farm, plan)
    write_workbook(out_dir / "cost_ledger.xlsx", cost_wb)

    ground_truth = build_ground_truth(farm, plan, ym_defects + aa_defects + cl_defects)
    write_json(out_dir / "ground_truth.json", ground_truth)

    write_text(out_dir / "README.md", render_readme(config, ground_truth))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = build_config(args)
        generate(config, args.out)
    except (ValueError, AssertionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Generated {config.num_seasons} seasons of synthetic farm data in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
