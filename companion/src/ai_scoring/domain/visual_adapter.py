"""Score-free offline visual input contract. Implementations are operator supplied."""
from dataclasses import dataclass
from typing import Protocol
from ai_scoring.domain.scoring import PotObservation

@dataclass(frozen=True)
class TimestampedFrame:
    data: bytes
    timestamp: str
    asset_id: str
    media_time: float
    utc_uncertainty_ms: float
    width: int = 0
    height: int = 0
    pixel_format: str = "rgb24"

@dataclass(frozen=True)
class BoundaryContext:
    frame_id: str
    run_id: str
    frame_started_at: str
    run_started_at: str
    cutoff: str

@dataclass(frozen=True)
class VisualResult:
    observations: tuple[PotObservation, ...] = ()
    baseline_reds: int | None = None
    quality_reasons: tuple[str, ...] = ()
    processed_through: str | None = None

class VisualAdapter(Protocol):
    metadata: dict
    def observe(self, frame: TimestampedFrame, context: BoundaryContext) -> VisualResult: ...
