import hashlib
from pathlib import Path

from farm_data_gen.cli import generate
from farm_data_gen.config import SimConfig


def _hash_tree(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def test_same_seed_produces_byte_identical_output(tmp_path):
    config = SimConfig(random_seed=7, num_fields=10, num_seasons=6)

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    generate(config, out_a)
    generate(config, out_b)

    hashes_a = _hash_tree(out_a)
    hashes_b = _hash_tree(out_b)

    assert hashes_a, "generator produced no files"
    assert set(hashes_a) == set(hashes_b), "file sets differ between identical-seed runs"
    mismatches = [f for f in hashes_a if hashes_a[f] != hashes_b[f]]
    assert not mismatches, f"non-deterministic output files: {mismatches}"


def test_different_seed_produces_different_output(tmp_path):
    config_a = SimConfig(random_seed=7, num_fields=10, num_seasons=6)
    config_b = SimConfig(random_seed=99, num_fields=10, num_seasons=6)

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    generate(config_a, out_a)
    generate(config_b, out_b)

    hashes_a = _hash_tree(out_a)
    hashes_b = _hash_tree(out_b)

    assert set(hashes_a) == set(hashes_b), "different seeds should still produce the same files"
    assert hashes_a != hashes_b, "different seeds produced byte-identical output"
