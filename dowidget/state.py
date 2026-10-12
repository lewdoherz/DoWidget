"""UI-independent refresh gating and stale-data retention using monotonic time."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math

from .models import ProviderError, Snapshot


@dataclass
class ProviderState:
    snapshot: Snapshot | None = None
    updated_at: datetime | None = None
    status: str = "setup_required"
    message: str = ""
    busy: bool = False
    next_due: float = 0.0
    failure_count: int = 0

    def begin(self, now: float, manual: bool = False) -> bool:
        if self.busy:
            return False
        # Manual refresh bypasses an ordinary interval, never a failure cooldown.
        if now < self.next_due and (not manual or self.failure_count > 0):
            return False
        self.busy = True
        return True

    def succeed(
        self, snapshot: Snapshot, now: float, wall_time: datetime, interval_seconds: float
    ) -> None:
        self.snapshot = snapshot
        self.updated_at = (
            wall_time.replace(tzinfo=timezone.utc)
            if wall_time.tzinfo is None
            else wall_time.astimezone(timezone.utc)
        )
        self.status = "ready"
        self.message = ""
        self.busy = False
        self.failure_count = 0
        self.next_due = now + max(0.0, interval_seconds)

    def fail(self, error: ProviderError, now: float, interval_seconds: float) -> None:
        self.busy = False
        self.failure_count += 1
        # Cap the exponent too, so prolonged outages never create huge integers.
        delay = min(3600.0, max(30.0, interval_seconds) * 2 ** min(self.failure_count - 1, 7))
        retry_after = error.retry_after
        if (
            isinstance(retry_after, (int, float))
            and not isinstance(retry_after, bool)
            and math.isfinite(retry_after)
            and retry_after > 0
        ):
            delay = max(delay, retry_after)
        self.next_due = now + delay
        self.status = "stale" if self.snapshot is not None else error.kind
        self.message = str(error)

    def reset(self, status: str = "setup_required", message: str = "") -> None:
        self.snapshot = None
        self.updated_at = None
        self.status = status
        self.message = message
        self.busy = False
        self.next_due = 0.0
        self.failure_count = 0
