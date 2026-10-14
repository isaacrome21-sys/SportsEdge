# Evidence anchor series

This branch carries the SportsEdge evidence anchor series: small
content-addressed payloads, one per anchored archive state, plus
the series registry at `anchors/index.json`. Anchors are the
project's external timestamp for its evidence archives (the MLB
receipt journal today; sibling payload schemas for the starter
manifest and the CFB Form 2 archive join the same series).

## What an anchor proves -- and what it does not

An anchor proves **existence-by-publication-time only**: the
archive state named by the payload's identity fields (chain head
hash, genesis, sequence range, entry count, whole-file SHA-256)
existed, byte-for-byte, at or before the GitHub publication
receipt time of the commit that introduced the payload.

An anchor does **not** prove that any individual record inside
the archive was captured when it claims, does not prove the
history accumulated gradually (only the cadence of anchors
bounds that, prospectively), and is **not** a cryptographic
signature or attestation. It carries no promotion authority and
authorizes no activation of anything.

Material written before this series began keeps the status it
already carries: locally consistent, externally **UNANCHORED**.
A first anchor gives pre-anchor history an upper bound on its
existence; it does not retroactively verify it, and the
UNANCHORED labels on pre-anchor records stay as written.
