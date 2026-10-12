"""Read-only Claude Enterprise spend caps and xAI API prepaid credit sources."""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import re
import time
from urllib.parse import quote

from .models import Balance, MoneyMetric, ProviderError, Snapshot, UsageWindow, remaining_percentage
from .provider_http import get_json, REQUEST_DEADLINE

CLAUDE_INVALID = "Claude returned an invalid usage response."
GROK_INVALID = "Grok returned an invalid usage response."
MAX_PAGES = 10
# Unlisted ISO codes deliberately stay in minor units rather than guessing.
CURRENCY_EXPONENTS = {
    "USD": 2, "EUR": 2, "GBP": 2, "CNY": 2, "CHF": 2, "CAD": 2,
    "AUD": 2, "NZD": 2, "HKD": 2, "SGD": 2, "INR": 2,
    "JPY": 0, "KRW": 0, "VND": 0, "CLP": 0,
    "BHD": 3, "KWD": 3, "OMR": 3, "JOD": 3, "TND": 3,
}


def _number(value, message, *, signed=False, integer=False):
    pattern = r"-?[0-9]+" if signed else r"[0-9]+"
    if not integer:
        pattern += r"(?:\.[0-9]{1,3})?"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ProviderError(message)
    return Decimal(value)


def _money(amount, currency):
    exponent = CURRENCY_EXPONENTS.get(currency)
    if exponent is None:
        return amount, "minor"
    parts = amount.as_tuple()
    return Decimal((parts.sign, parts.digits, parts.exponent - exponent)), "major"


def _monthly_reset(now):
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return datetime(year, month, 1, tzinfo=timezone.utc)


def parse_claude(rows, user_id, *, observed_at=None):
    """Parse only the requested actor, never an organization-wide aggregate."""
    now = observed_at or datetime.now(timezone.utc)
    windows, metrics, seen = [], [], set()
    ambiguous = False
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderError(CLAUDE_INVALID)
        actor = row.get("actor")
        if not isinstance(actor, dict):
            raise ProviderError(CLAUDE_INVALID)
        if actor.get("type") != "user_actor" or actor.get("user_id") != user_id:
            continue
        period, currency = row.get("period"), row.get("currency")
        if (not isinstance(period, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", period)
                or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)
                or period in seen or "amount" not in row):
            raise ProviderError(CLAUDE_INVALID)
        seen.add(period)
        cap = None if row["amount"] is None else _number(row["amount"], CLAUDE_INVALID, integer=True)
        spend = _number(row.get("period_to_date_spend"), CLAUDE_INVALID)
        amount, unit = _money(spend, currency)
        metrics.append(MoneyMetric(period + " reported spend", currency, amount, unit))
        remaining = None
        ambiguous |= spend == 0
        if cap is not None and cap > 0 and spend > 0:
            remaining = remaining_percentage(used=spend, total=cap)
            with localcontext() as context:
                context.prec = max(len(cap.as_tuple().digits), len(spend.as_tuple().digits)) + 8
                available = max(Decimal(0), cap - spend)
            amount, unit = _money(available, currency)
            metrics.append(MoneyMetric(period + " remaining spend cap", currency, amount, unit))
        suffix = " (unlimited)" if cap is None else " (included usage only)" if cap == 0 else ""
        windows.append(UsageWindow("Claude Enterprise " + period + suffix, remaining,
                                   _monthly_reset(now) if period == "monthly" else None))
    note = "Claude Enterprise member spend caps; not a wallet or Claude Pro/Max message limits."
    if ambiguous:
        note += " Reported zero spend may mean the reading is unavailable; remaining is unknown."
    if not windows:
        note += " No effective spend caps were reported for the selected member."
    return Snapshot(windows=tuple(windows), metrics=tuple(metrics), note=note, observed_at=now)


class ClaudeProvider:
    def fetch(self, key: str, options: dict[str, str]) -> Snapshot:
        user_id = options.get("user_id", "")
        if not key or not isinstance(user_id, str) or not re.fullmatch(r"user_[A-Za-z0-9_-]+", user_id):
            raise ProviderError("Claude requires an Enterprise Admin key with read:spend_limits and a user_ member ID.", "setup_required")
        deadline = time.monotonic() + REQUEST_DEADLINE
        params = {"user_ids[]": user_id, "limit": 100}
        rows, cursors = [], set()
        for _ in range(MAX_PAGES):
            data = get_json("https://api.anthropic.com/v1/organizations/spend_limits/effective",
                            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                            params=dict(params), provider="Claude", deadline=deadline)
            if not isinstance(data, dict) or not isinstance(data.get("data"), list) or "next_page" not in data:
                raise ProviderError(CLAUDE_INVALID)
            rows.extend(data["data"])
            cursor = data["next_page"]
            if cursor is None:
                return parse_claude(rows, user_id)
            if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in cursors:
                raise ProviderError(CLAUDE_INVALID)
            cursors.add(cursor)
            params["page"] = cursor
        raise ProviderError("Claude pagination exceeded the safe request limit.")


def parse_grok(data):
    if not isinstance(data, dict) or not isinstance(data.get("total"), dict):
        raise ProviderError(GROK_INVALID)
    ledger = _number(data["total"].get("val"), GROK_INVALID, signed=True, integer=True)
    # Purchases are negative ledger entries; available funds have opposite sign.
    amount, _ = _money(ledger.copy_negate(), "USD")
    return Snapshot(balances=(Balance("USD", amount),),
                    note="xAI team API prepaid credit; negative balance means debt. Not SuperGrok subscription usage.",
                    observed_at=datetime.now(timezone.utc))


class GrokProvider:
    def fetch(self, key: str, options: dict[str, str]) -> Snapshot:
        team_id = options.get("team_id", "")
        if not key or not isinstance(team_id, str) or not team_id.strip() or len(team_id) > 256:
            raise ProviderError("Grok requires a separate xAI management key and team ID.", "setup_required")
        data = get_json("https://management-api.x.ai/v1/billing/teams/" + quote(team_id, safe="") + "/prepaid/balance",
                        headers={"Authorization": "Bearer " + key}, provider="Grok")
        return parse_grok(data)
