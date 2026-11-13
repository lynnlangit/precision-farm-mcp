"""One app version (eval-fix P5): farm_host.__version__ is the version users
see (farm-cli --version, farm-preflight). Every package -- generator, core,
model, host, web and the six MCP servers -- carries the same number, so a
release bump can't leave one behind. The generator's number is also written
into ground_truth.json.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import farm_core
import farm_model
import pytest

import farm_host
from farm_host import cli

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PYPROJECTS = [
    REPO_ROOT / "generator" / "pyproject.toml",
    REPO_ROOT / "core" / "pyproject.toml",
    REPO_ROOT / "model" / "pyproject.toml",
    REPO_ROOT / "host" / "pyproject.toml",
    REPO_ROOT / "web" / "pyproject.toml",
    *sorted((REPO_ROOT / "servers").glob("*/pyproject.toml")),
]


def test_app_version_is_0_1_0():
    assert farm_host.__version__ == "0.1.0"


@pytest.mark.parametrize("pyproject", APP_PYPROJECTS, ids=lambda p: p.parent.name)
def test_every_app_package_has_the_app_version(pyproject):
    version = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert version == farm_host.__version__


def test_package_dunder_versions_match():
    assert farm_core.__version__ == farm_host.__version__
    assert farm_model.__version__ == farm_host.__version__


def test_there_are_six_servers():
    assert len(APP_PYPROJECTS) == 5 + 6


def test_farm_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out.strip() == f"Precision Farm MCP {farm_host.__version__}"
