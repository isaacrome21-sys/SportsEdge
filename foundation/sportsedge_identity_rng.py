#!/usr/bin/env python3
"""Reusable candidate-identity RNG policy for SportsEdge production engines."""
from __future__ import annotations
import hashlib
import re
import numpy as np

SEED_POLICY = "sha256_build_hash_seedsequence_v1"
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

def candidate_seed_sequence(build_hash: str) -> np.random.SeedSequence:
    if not isinstance(build_hash, str) or not _HEX64.fullmatch(build_hash):
        raise ValueError("build_hash must be exactly 64 hexadecimal characters")
    digest = hashlib.sha256(build_hash.encode("ascii")).digest()
    entropy_words = [int.from_bytes(digest[i:i+4], "big") for i in range(0, 32, 4)]
    if len(entropy_words) != 8:
        raise RuntimeError("seed entropy width regression")
    return np.random.SeedSequence(entropy_words)

def candidate_rng(build_hash: str) -> np.random.Generator:
    return np.random.default_rng(candidate_seed_sequence(build_hash))
