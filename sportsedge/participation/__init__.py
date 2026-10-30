"""NFL participation evidence foundation (research-side data infrastructure).

Implements the archive, collectors, and as-of reader specified by
``phase2_v2_design/participation_data_foundation.md``. DATA ONLY: no model
code, no pricing, no evaluation. Nothing in this package is imported by
production pricing paths.
"""

from .archive import ParticipationArchive
from .reader import AsOfReader
from .schema import ParticipationRecord

__all__ = ["ParticipationArchive", "AsOfReader", "ParticipationRecord"]
