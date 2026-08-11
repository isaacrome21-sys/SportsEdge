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
    """Stable per-candidate RNG independent of process, row order, clock, or batch."""
    return random.Random(seed_int(build_hash))


def build_hash(payload_parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for part in payload_parts:
        if not isinstance(part, str):
            raise IdentityError("identity parts must be strings")
        encoded = part.encode("utf-8")
        h.update(len(encoded).to_bytes(8, "big"))
        h.update(encoded)
    return h.hexdigest()
