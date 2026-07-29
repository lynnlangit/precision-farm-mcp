"""Deterministic RNG utilities.

All randomness in the generator must be reproducible byte-for-byte given the same
--seed, across processes and machines. Python's built-in hash() is randomized per
process (PYTHONHASHSEED) unless explicitly disabled, so it must never be used to
derive seeds. hashlib.sha256 is stable and portable, so we use it exclusively.
"""

from __future__ import annotations

import hashlib

import numpy as np

_SEED_BITS = 32
_SEED_MASK = (1 << _SEED_BITS) - 1


def derive_seed(master_seed: int, *key_parts: str | int) -> int:
    """Derive a stable, process-independent sub-seed from a master seed and a key.

    The same (master_seed, key_parts) always produces the same integer, on any
    machine, in any process, regardless of PYTHONHASHSEED.
    """
    key = "|".join(str(p) for p in (master_seed, *key_parts))
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], byteorder="big") & _SEED_MASK


def derive_rng(master_seed: int, *key_parts: str | int) -> np.random.Generator:
    """Return a fresh, independent Generator for a specific (entity, purpose) key."""
    return np.random.default_rng(derive_seed(master_seed, *key_parts))
