import hashlib
import random
import re
from typing import Iterable

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class IdentityError(ValueError):
    pass


def validate_build_hash(build_hash: str) -> str:
    if not isinstance(build_hash, str) or not _SHA256_RE.fullmatch(build_hash):
        raise IdentityError("build_hash must be exactly 64 hexadecimal characters")
    return build_hash.lower()


def entropy_words(build_hash: str) -> tuple[int, ...]:
    digest = bytes.fromhex(validate_build_hash(build_hash))
    return tuple(int.from_bytes(digest[i:i+4], "big") for i in range(0, 32, 4))


def seed_int(build_hash: str) -> int:
    digest = bytes.fromhex(validate_build_hash(build_hash))
    return int.from_bytes(digest, "big")


def candidate_rng(build_hash: str) -> random.Random:
    """Stable pure-Python per-candidate RNG for non-Monte-Carlo plumbing."""
    return random.Random(seed_int(build_hash))


def candidate_numpy_seed_sequence(build_hash: str):
    """Validated Hits/TB MC seed policy using all 256 digest bits.

    The canonical 64-hex candidate identity is SHA-256 hashed once more and all
    eight uint32 words are fed into numpy SeedSequence. This preserves the
    production-logic result that fixed the correlated-seed holdout bug while
    keeping the existing pure-Python candidate_rng stable for other callers.
    """
    import numpy as np
    canonical = validate_build_hash(build_hash)
    digest = hashlib.sha256(canonical.encode("ascii")).digest()
    words = [int.from_bytes(digest[i:i+4], "big") for i in range(0, 32, 4)]
    return np.random.SeedSequence(words)


def candidate_numpy_rng(build_hash: str):
    import numpy as np
    return np.random.default_rng(candidate_numpy_seed_sequence(build_hash))


def build_hash(payload_parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for part in payload_parts:
        if not isinstance(part, str):
            raise IdentityError("identity parts must be strings")
        encoded = part.encode("utf-8")
        h.update(len(encoded).to_bytes(8, "big"))
        h.update(encoded)
    return h.hexdigest()
