"""Small, presentation-independent provider contract."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext


class ProviderError(Exception):
    """Only safe, fixed messages; never attach raw responses or credentials."""

    def __init__(self, message: str, kind: str = "error", retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


@dataclass(frozen=True)
class Balance:
    currency: str
    total: Decimal
    granted: Decimal | None = None
    topped_up: Decimal | None = None


@dataclass(frozen=True)
class UsageWindow:
    name: str
    remaining: Decimal | None
    resets_at: datetime | None = None


@dataclass(frozen=True)
class Snapshot:
    balances: tuple[Balance, ...] = ()
    windows: tuple[UsageWindow, ...] = ()
    note: str = ""
    demo: bool = False


def remaining_percentage(*, used_percent=None, used=None, total=None) -> Decimal | None:
    """Unknown/nonfinite/invalid inputs stay unknown; finite results are clamped."""
    def number(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            result = Decimal(str(value))
            return result if result.is_finite() else None
        except (InvalidOperation, ValueError):
            return None

    percent = number(used_percent)
    if percent is None:
        numerator, denominator = number(used), number(total)
        if numerator is None or denominator is None or numerator < 0 or denominator <= 0:
            return None
        if numerator >= denominator:
            return Decimal(0)
        with localcontext() as context:
            context.prec = 40
            percent = numerator / denominator * 100
    return Decimal(100) - max(Decimal(0), min(Decimal(100), percent))
