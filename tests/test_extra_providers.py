from datetime import datetime, timezone
from decimal import Decimal, localcontext

import pytest
import requests

from dowidget import extra_providers as adapters, provider_http as http
from dowidget.models import ProviderError


def row(spend="12050.5", cap="50000", currency="USD", period="monthly", user="user_selected"):
    return {"actor": {"type": "user_actor", "user_id": user}, "amount": cap,
            "currency": currency, "period": period, "period_to_date_spend": spend}


def test_claude_source_and_periods():
    now = datetime(2026, 12, 20, tzinfo=timezone.utc)
    snapshot = adapters.parse_claude([row(), row(period="daily"), row(user="user_other")],
                                     "user_selected", observed_at=now)
    assert len(snapshot.windows) == 2
    assert snapshot.windows[0].remaining == Decimal("75.899")
    assert snapshot.windows[0].resets_at == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert snapshot.windows[1].resets_at is None
    assert snapshot.metrics[0].amount == Decimal("120.505")
    assert snapshot.metrics[1].amount == Decimal("379.495")
    assert not snapshot.balances


@pytest.mark.parametrize("spend,cap", [("0", "100"), ("5", None), ("5", "0")])
def test_claude_unknown_not_full(spend, cap):
    result = adapters.parse_claude([row(spend, cap)], "user_selected")
    assert result.windows[0].remaining is None
    assert len(result.metrics) == 1


@pytest.mark.parametrize("currency,amount,unit", [("JPY", "12050.5", "major"),
    ("KWD", "12.0505", "major"), ("XYZ", "12050.5", "minor")])
def test_currency_units(currency, amount, unit):
    metric = adapters.parse_claude([row(currency=currency)], "user_selected").metrics[0]
    assert (metric.currency, metric.amount, metric.unit) == (currency, Decimal(amount), unit)


def test_huge_exact_amounts_ignore_decimal_context():
    value = "1234567890123456789012345678901234567890"
    with localcontext() as context:
        context.prec = 6
        result = adapters.parse_grok({"total": {"val": "-" + value}})
        assert result.balances[0].total == Decimal(value[:-2] + "." + value[-2:])
        metric = adapters.parse_claude([row(value + ".125", None)], "user_selected").metrics[0]
        assert metric.amount == Decimal(value[:-2] + "." + value[-2:] + "125")


@pytest.mark.parametrize("ledger,available", [("-1000", "10"), ("250", "-2.50"), ("0", "0")])
def test_grok_signed_ledger(ledger, available):
    result = adapters.parse_grok({"total": {"val": ledger}})
    assert result.balances[0].total == Decimal(available)
    assert not result.windows


@pytest.mark.parametrize("bad", [True, 100, "NaN", "Infinity", "1e9", "1.25", None])
def test_invalid_grok_amount(bad):
    with pytest.raises(ProviderError, match="invalid usage"):
        adapters.parse_grok({"total": {"val": bad}})


@pytest.mark.parametrize("change", [{"amount": "-1"}, {"period_to_date_spend": "NaN"},
                                    {"currency": "secret"}, {"period": "<script>"}])
def test_invalid_claude_rows(change):
    data = row()
    data.update(change)
    with pytest.raises(ProviderError):
        adapters.parse_claude([data], "user_selected")


def test_actual_requests_and_filter(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return {"data": [row(), row(user="user_other")], "next_page": None}
    monkeypatch.setattr(adapters, "get_json", get)
    result = adapters.ClaudeProvider().fetch("admin-secret", {"user_id": "user_selected"})
    assert len(result.windows) == 1
    url, kwargs = calls[0]
    assert url == "https://api.anthropic.com/v1/organizations/spend_limits/effective"
    assert kwargs["params"]["user_ids[]"] == "user_selected"
    assert kwargs["headers"] == {"x-api-key": "admin-secret", "anthropic-version": "2023-06-01"}
    calls.clear()
    monkeypatch.setattr(adapters, "get_json", lambda url, **kwargs:
                        calls.append((url, kwargs)) or {"total": {"val": "-1000"}})
    adapters.GrokProvider().fetch("management-secret", {"team_id": "team/id"})
    assert calls[0][0] == "https://management-api.x.ai/v1/billing/teams/team%2Fid/prepaid/balance"
    assert calls[0][1]["headers"] == {"Authorization": "Bearer management-secret"}


@pytest.mark.parametrize("provider,options", [(adapters.ClaudeProvider(), {}),
    (adapters.ClaudeProvider(), {"user_id": "someone"}), (adapters.GrokProvider(), {})])
def test_setup_required_before_request(provider, options, monkeypatch):
    monkeypatch.setattr(adapters, "get_json", lambda *a, **k: pytest.fail("unexpected request"))
    with pytest.raises(ProviderError) as caught:
        provider.fetch("key", options)
    assert caught.value.kind == "setup_required"


def test_pagination_filters_and_no_partial_success(monkeypatch):
    calls = []
    pages = iter([{"data": [row()], "next_page": "cursor"},
                  {"data": [], "next_page": "cursor"}])
    def get(*args, **kwargs):
        calls.append(kwargs)
        return next(pages)
    monkeypatch.setattr(adapters, "get_json", get)
    with pytest.raises(ProviderError):
        adapters.ClaudeProvider().fetch("key", {"user_id": "user_selected"})
    assert calls[1]["params"] == {"user_ids[]": "user_selected", "limit": 100, "page": "cursor"}
    assert calls[0]["deadline"] == calls[1]["deadline"]


def test_pagination_limit(monkeypatch):
    count = 0
    def get(*args, **kwargs):
        nonlocal count
        count += 1
        return {"data": [], "next_page": str(count)}
    monkeypatch.setattr(adapters, "get_json", get)
    with pytest.raises(ProviderError, match="pagination"):
        adapters.ClaudeProvider().fetch("key", {"user_id": "user_selected"})
    assert count == adapters.MAX_PAGES


class Response:
    def __init__(self, status=200, body=b'{"number": 0.12345678901234567890123456789}', headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}
        self.closed = False
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.closed = True
    def iter_content(self, chunk_size):
        yield self.body


def transport(monkeypatch, response):
    calls = []
    monkeypatch.setattr(http.requests, "get", lambda *args, **kwargs: calls.append(kwargs) or response)
    return calls



def test_pagination_completes_all_periods(monkeypatch):
    pages = iter([{"data": [row()], "next_page": "next"},
                  {"data": [row(period="weekly")], "next_page": None}])
    monkeypatch.setattr(adapters, "get_json", lambda *a, **k: next(pages))
    snapshot = adapters.ClaudeProvider().fetch("key", {"user_id": "user_selected"})
    assert len(snapshot.windows) == 2
    assert snapshot.windows[1].resets_at is None


def test_later_page_failure_does_not_return_partial(monkeypatch):
    count = 0
    def get(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return {"data": [row()], "next_page": "next"}
        raise ProviderError("Claude is temporarily unavailable.", "unavailable")
    monkeypatch.setattr(adapters, "get_json", get)
    with pytest.raises(ProviderError) as caught:
        adapters.ClaudeProvider().fetch("key", {"user_id": "user_selected"})
    assert caught.value.kind == "unavailable"


def test_http_deadline_bounds_blocking_worker(monkeypatch):
    import threading
    release = threading.Event()
    response = Response()
    def blocked(*args, **kwargs):
        release.wait(timeout=1)
        return response
    monkeypatch.setattr(http.requests, "get", blocked)
    monkeypatch.setattr(http, "REQUEST_DEADLINE", 0.01)
    try:
        with pytest.raises(ProviderError) as caught:
            http.get_json("https://example.invalid", headers={}, provider="Claude")
        assert caught.value.kind == "timeout"
    finally:
        release.set()

def test_http_decimal_and_bounds(monkeypatch):
    response = Response()
    calls = transport(monkeypatch, response)
    result = http.get_json("https://example.invalid", headers={}, provider="Claude")
    assert result["number"] == Decimal("0.12345678901234567890123456789")
    assert calls[0]["allow_redirects"] is False
    assert calls[0]["timeout"] == (4.0, 10.0)
    assert calls[0]["stream"] is True
    assert response.closed


@pytest.mark.parametrize("status,kind", [(401, "setup_required"), (403, "setup_required"),
    (429, "rate_limited"), (503, "unavailable"), (302, "error"), (400, "error")])
def test_safe_status_errors(monkeypatch, status, kind):
    transport(monkeypatch, Response(status, b"upstream-secret", {"Retry-After": "12"}))
    with pytest.raises(ProviderError) as caught:
        http.get_json("https://example.invalid", headers={}, provider="Grok")
    assert caught.value.kind == kind
    assert "upstream-secret" not in str(caught.value)
    assert caught.value.retry_after == (12 if status == 429 else None)


@pytest.mark.parametrize("body", [b"secret-not-json", b'{"a":NaN}', b"x" * (http.MAX_BODY + 1)],
                         ids=["not-json", "nonfinite-json", "oversized"])
def test_body_errors(monkeypatch, body):
    response = Response(body=body)
    transport(monkeypatch, response)
    with pytest.raises(ProviderError, match="invalid usage"):
        http.get_json("https://example.invalid", headers={}, provider="Claude")
    assert response.closed


@pytest.mark.parametrize("error,kind", [(requests.Timeout("secret"), "timeout"),
                                       (requests.ConnectionError("secret"), "network")])
def test_network_errors_are_safe(monkeypatch, error, kind):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(http.requests, "get", fail)
    with pytest.raises(ProviderError) as caught:
        http.get_json("https://example.invalid", headers={}, provider="Grok")
    assert caught.value.kind == kind
    assert "secret" not in str(caught.value)


def test_expired_deadline_no_request(monkeypatch):
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: pytest.fail("unexpected request"))
    with pytest.raises(ProviderError) as caught:
        http.get_json("https://example.invalid", headers={}, provider="Claude", deadline=-1)
    assert caught.value.kind == "timeout"


@pytest.mark.parametrize("value,expected", [("999999", 3600), ("-2", 0), ("NaN", None),
                                          ("garbage", None), (None, None)])
def test_retry_after(value, expected):
    assert http.retry_after(value) == expected
