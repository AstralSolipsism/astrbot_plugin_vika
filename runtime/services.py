from __future__ import annotations

from dataclasses import dataclass, field

from .artifacts import ArtifactStore
from .write_plans import WritePlanStore


@dataclass
class RuntimeServices:
    artifact_store: ArtifactStore = field(default_factory=ArtifactStore)
    write_plans: WritePlanStore = field(default_factory=WritePlanStore)
