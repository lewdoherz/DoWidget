"""Deterministic provider tests: no live HTTP, CLI, credentials, or browser."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import json
from unittest.mock import Mock, patch

import pytest
import requests

from dowidget.models import ProviderError
from dowidget.providers import (CodexProvider, DeepSeekProvider, MAX_BODY,
                                _retry_after, _StdioTransport, parse_codex_limits,
                                parse_deepseek)


def balance(currency="USD", total="123456789.12345678901234567890123456789"):
    return {"currency": currency, "total_balance": total,
            "granted_balance": "0.00000000000000000001", "topped_up_balance": "10.50"}


def payload(*rows, available=True):
    return {"is_available": available, "balance_infos": list(rows or [balance()])}


def response(status=200, data=None, body=None, headers=None):
    mock = Mock()
    mock.__enter__ = Mock(return_value=mock)
    mock.__exit__ = Mock(return_value=False)
    mock.status_code = status
    mock.headers = headers or {}
    mock.iter_content.return_value = [body if body is not None else json.dumps(data or payload()).encode()]
    return mock


def test_exact_decimal_and_all_currencies():
    snapshot = parse_deepseek(payload(balance(), balance("CNY", "3.00")))
    assert [b.currency for b in snapshot.balances] == ["USD", "CNY"]
    assert snapshot.balances[0].total == Decimal("123456789.12345678901234567890123456789")
    assert snapshot.balances[0].granted == Decimal("0.00000000000000000001")
    assert snapshot.balances[1].total.as_tuple().exponent == -2
    assert "not sufficient" in parse_deepseek(payload(available=False)).note


@pytest.mark.parametrize("field", ["currency", "total_balance", "granted_balance", "topped_up_balance"])
def test_balance_missing_fields(field):
    row = balance()
    del row[field]
    with pytest.raises(ProviderError):
        parse_deepseek(payload(row))


@pytest.mark.parametrize("value", [None, 0, True, "NaN", "Infinity", "-Infinity", "bad"])
@pytest.mark.parametrize("field", ["total_balance", "granted_balance", "topped_up_balance"])
def test_balance_invalid_amounts(field, value):
    row = balance()
    row[field] = value
    with pytest.raises(ProviderError):
        parse_deepseek(payload(row))


@pytest.mark.parametrize("data", [{}, [], {"is_available": True, "balance_infos": []},
                                 {"is_available": "true", "balance_infos": [balance()]},
                                 payload(balance("EUR"))])
def test_invalid_balance_schema(data):
    with pytest.raises(ProviderError):
        parse_deepseek(data)


def test_http_contract():
    with patch("dowidget.providers.requests.get", return_value=response()) as get:
        assert DeepSeekProvider().fetch("dummy-not-a-key").balances
    get.assert_called_once_with("https://api.deepseek.com/user/balance",
                                headers={"Authorization": "Bearer dummy-not-a-key"},
                                timeout=(4, 10), stream=True, allow_redirects=False)


@pytest.mark.parametrize("status,kind", [(401, "setup_required"), (403, "setup_required"),
                                        (429, "rate_limited"), (503, "unavailable"), (302, "error")])
def test_http_status_and_redaction(status, kind):
    with patch("dowidget.providers.requests.get", return_value=response(status, body=b"SECRET", headers={"Retry-After": "99999"})):
        with pytest.raises(ProviderError) as error:
            DeepSeekProvider().fetch("SECRET")
    assert error.value.kind == kind
    assert "SECRET" not in str(error.value)
    if status == 429:
        assert error.value.retry_after == 3600


@pytest.mark.parametrize("failure,kind", [(requests.Timeout("SECRET"), "timeout"),
                                         (requests.ConnectionError("SECRET"), "network")])
def test_http_failures_safe(failure, kind):
    with patch("dowidget.providers.requests.get", side_effect=failure):
        with pytest.raises(ProviderError) as error:
            DeepSeekProvider().fetch("SECRET")
    assert error.value.kind == kind
    assert "SECRET" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize("body", [b"SECRET", b"\xff", b"{}", b"x" * (MAX_BODY + 1)],
                         ids=["non-json", "invalid-encoding", "missing-data", "oversized"])
def test_invalid_and_oversized_body(body):
    with patch("dowidget.providers.requests.get", return_value=response(body=body)):
        with pytest.raises(ProviderError) as error:
            DeepSeekProvider().fetch("SECRET")
    assert "SECRET" not in str(error.value)


def test_stream_failure_and_cumulative_bound():
    stream = response()
    stream.iter_content.side_effect = requests.Timeout("SECRET")
    with patch("dowidget.providers.requests.get", return_value=stream):
        with pytest.raises(ProviderError):
            DeepSeekProvider().fetch("dummy")
    stream.iter_content.side_effect = None
    stream.iter_content.return_value = [b"x" * (MAX_BODY // 2), b"x" * (MAX_BODY // 2), b"x"]
    with patch("dowidget.providers.requests.get", return_value=stream):
        with pytest.raises(ProviderError):
            DeepSeekProvider().fetch("dummy")


def test_retry_after_seconds_dates_and_bounds():
    assert _retry_after("12") == 12
    assert _retry_after("-12") == 0
    assert _retry_after("999999") == 3600
    assert _retry_after("Thu, 01 Jan 2099 00:00:00 GMT") == 3600
    assert _retry_after("Thu, 01 Jan 1970 00:00:00 GMT") == 0
    for value in (None, "bad", "NaN", "Infinity"):
        assert _retry_after(value) is None


def window(used=25, minutes=300, reset=1730947200):
    return {"usedPercent": used, "windowDurationMins": minutes, "resetsAt": reset}


def limits(primary=None, secondary=None):
    return {"rateLimits": {"limitId": "codex", "primary": primary, "secondary": secondary}}


def test_codex_independent_windows():
    snapshot = parse_codex_limits(limits(window(), window(75, 10080, 1730950800)))
    assert [w.remaining for w in snapshot.windows] == [Decimal(75), Decimal(25)]
    assert snapshot.windows[0].resets_at == datetime.fromtimestamp(1730947200, timezone.utc)
    assert snapshot.windows[0].resets_at != snapshot.windows[1].resets_at


@pytest.mark.parametrize("reset", [None, "bad", "1730947200", True, -1, float("inf"), float("nan"), 10**100])
def test_missing_usage_and_invalid_reset(reset):
    snapshot = parse_codex_limits(limits({"resetsAt": reset}))
    assert snapshot.windows[0].remaining is None
    assert snapshot.windows[0].resets_at is None


@pytest.mark.parametrize("used,remaining", [(-5, 100), (105, 0), (None, None), ("NaN", None), (0, 100), (100, 0)])
def test_codex_clamping(used, remaining):
    actual = parse_codex_limits(limits(window(used))).windows[0].remaining
    assert actual == (Decimal(remaining) if remaining is not None else None)


def test_multibucket_precedence_and_subscription_filter():
    data = limits(window(99))
    data["rateLimitsByLimitId"] = {
        "codex": {"limitName": "Subscription", "primary": window(10)},
        "codex_other": {"primary": window(20), "secondary": window(30)},
        "chatgpt": {"primary": window(40)},
    }
    result = parse_codex_limits(data)
    assert [w.remaining for w in result.windows] == [Decimal(90), Decimal(80), Decimal(70)]
    assert result.windows[0].name.startswith("Subscription")
    assert result.windows[1].name.startswith("codex_other")
    data["rateLimitsByLimitId"] = {}
    with pytest.raises(ProviderError) as error:
        parse_codex_limits(data)
    assert error.value.kind == "unavailable"


@pytest.mark.parametrize("data", [{}, {"rateLimits": None}, limits(), {"rateLimitsByLimitId": []}])
def test_codex_missing_buckets(data):
    with pytest.raises(ProviderError):
        parse_codex_limits(data)


class ScriptTransport:
    def __init__(self, home, persistent):
        self.home, self.persistent = home, persistent
        self.sent = []
        self.responses = []
        self.closed = False
        self.results = {"initialize": {}, "account/read": {"account": {"type": "chatgpt"}},
                        "account/rateLimits/read": limits(window()), "account/logout": {}}

    def send(self, message):
        self.sent.append(message)
        if "id" in message:
            self.responses.append({"id": message["id"], "result": self.results[message["method"]]})

    def receive(self, deadline):
        if not self.responses:
            raise ProviderError("Codex request timed out.", "timeout")
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def provider(tmp_path):
    transport = ScriptTransport(tmp_path, False)
    return CodexProvider(tmp_path, False, transport_factory=lambda *_: transport), transport


def test_rpc_handshake_fetch_reuses_ephemeral_process_logout_close(tmp_path):
    client, transport = provider(tmp_path)
    client.fetch()
    client.fetch()
    client.logout()
    client.close()
    client.close()
    methods = [message["method"] for message in transport.sent]
    assert methods == ["initialize", "initialized", "account/read", "account/rateLimits/read",
                       "account/read", "account/rateLimits/read", "account/logout"]
    assert "capabilities" not in transport.sent[0]["params"]
    assert transport.sent[2]["params"] == {"refreshToken": True}
    assert transport.closed
    with pytest.raises(ProviderError):
        client.fetch()


@pytest.mark.parametrize("account", [None, {"type": "apiKey"}, {"type": "amazonBedrock"}, {}])
def test_rpc_account_requires_chatgpt(tmp_path, account):
    client, transport = provider(tmp_path)
    transport.results["account/read"] = {"account": account}
    with pytest.raises(ProviderError) as error:
        client.fetch()
    assert error.value.kind == "setup_required"
    assert "account/rateLimits/read" not in [m["method"] for m in transport.sent]


def prepare_login(tmp_path, url="https://auth.openai.com/authorize"):
    client, transport = provider(tmp_path)
    transport.results["account/login/start"] = {"type": "chatgpt", "loginId": "dummy", "authUrl": url}
    client._ensure()
    return client, transport


def test_broken_codex_transport_reconnects_on_next_refresh(tmp_path):
    first = ScriptTransport(tmp_path, True)
    replacement = ScriptTransport(tmp_path, True)
    transports = iter((first, replacement))
    client = CodexProvider(tmp_path, True, transport_factory=lambda *_: next(transports))
    assert client.fetch().windows[0].remaining == Decimal(75)
    with patch.object(first, "receive", side_effect=ProviderError("Connection failed.", "network")):
        with pytest.raises(ProviderError):
            client.fetch()
    assert first.closed
    assert client.fetch().windows[0].remaining == Decimal(75)
    client.close()


def test_login_browser_and_early_notification(tmp_path):
    client, transport = prepare_login(tmp_path)
    transport.responses.append({"method": "account/login/completed", "params": {"loginId": "dummy", "success": True}})
    with patch("dowidget.providers.webbrowser.open", return_value=True) as browser:
        client.login()
    browser.assert_called_once_with("https://auth.openai.com/authorize")
    assert not transport.closed


@pytest.mark.parametrize("url", ["http://chatgpt.com/a", "https://chatgpt.com.evil.test/", "https://evil.test/",
                                 "https://user@chatgpt.com/", "https://chatgpt.com:444/", "https://chatgpt.com/\nsecret"])
def test_login_rejects_unofficial_urls(tmp_path, url):
    client, _ = prepare_login(tmp_path, url)
    with patch("dowidget.providers.webbrowser.open") as browser:
        with pytest.raises(ProviderError):
            client.login()
    browser.assert_not_called()


def test_login_browser_failure_timeout_and_safe_error(tmp_path):
    client, transport = prepare_login(tmp_path)
    with patch("dowidget.providers.webbrowser.open", side_effect=RuntimeError("SECRET")):
        with pytest.raises(ProviderError):
            client.login()
    with patch("dowidget.providers.webbrowser.open", return_value=True):
        with pytest.raises(ProviderError) as error:
            client.login()
    assert error.value.kind == "timeout"
    transport.responses.append({"method": "account/login/completed", "params": {"loginId": "dummy", "success": False, "error": "SECRET"}})
    with patch("dowidget.providers.webbrowser.open", return_value=True):
        with pytest.raises(ProviderError) as error:
            client.login()
    assert "SECRET" not in str(error.value)


def test_rpc_error_and_timeout_redaction(tmp_path):
    client, transport = provider(tmp_path)
    client._ensure()
    transport.responses.append({"id": 2, "error": {"message": "SECRET"}})
    with pytest.raises(ProviderError) as error:
        client.fetch()
    assert "SECRET" not in str(error.value)
    transport.responses.clear()
    with patch.object(transport, "send"):
        with pytest.raises(ProviderError) as error:
            client.fetch()
    assert error.value.kind == "timeout"


def test_missing_cli_precise_message(tmp_path):
    with patch("dowidget.providers.shutil.which", return_value=None):
        with pytest.raises(ProviderError) as error:
            _StdioTransport(tmp_path, False)
    assert error.value.kind == "setup_required"


@pytest.mark.parametrize("persistent,store", [(True, "keyring"), (False, "ephemeral")])
def test_process_isolation_and_config_override(tmp_path, persistent, store):
    process = Mock()
    process.stdout.readline.return_value = b""
    process.poll.return_value = 0
    with patch("dowidget.providers.shutil.which", return_value="codex.exe"), \
         patch("dowidget.providers.subprocess.Popen", return_value=process) as popen, \
         patch.dict("os.environ", {"OPENAI_API_KEY": "SECRET", "CODEX_ACCESS_TOKEN": "SECRET", "ANTHROPIC_API_KEY": "SECRET", "CODEX_HOME": "other-home"}):
        transport = _StdioTransport(tmp_path, persistent)
        transport.close()
    args, kwargs = popen.call_args
    assert args[0] == ["codex.exe", "app-server", "-c", f"cli_auth_credentials_store='{store}'"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["env"]["CODEX_HOME"] == str(tmp_path.resolve())
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "CODEX_ACCESS_TOKEN" not in kwargs["env"]
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert kwargs["stderr"] == -3  # subprocess.DEVNULL


def test_slow_http_stream_overall_deadline():
    with patch("dowidget.providers.requests.get", return_value=response()), \
         patch("dowidget.providers.time.monotonic", side_effect=[0, 21]):
        with pytest.raises(ProviderError) as error:
            DeepSeekProvider().fetch("dummy")
    assert error.value.kind == "timeout"


@pytest.mark.parametrize("lines", [
    [b"x" * (MAX_BODY + 1)],
    [b'{"result": "SECRET"}'],
    [b"SECRET\n"],
    [b"[]\n"],
    [b"{}\n"] * 65,
])
def test_stdio_line_and_queue_bounds(tmp_path, lines):
    process = Mock()
    process.stdout.readline.side_effect = lines + [b""]
    process.poll.return_value = 0
    with patch("dowidget.providers.shutil.which", return_value="codex.exe"), \
         patch("dowidget.providers.subprocess.Popen", return_value=process), \
         patch("dowidget.providers.threading.Thread"):
        transport = _StdioTransport(tmp_path, False)
    transport._read()
    assert transport.closed.is_set()
    assert transport.messages.qsize() <= 64
    transport.close()


def test_stdio_eof_and_timeout_are_safe(tmp_path):
    process = Mock()
    process.poll.return_value = 0
    with patch("dowidget.providers.shutil.which", return_value="codex.exe"), \
         patch("dowidget.providers.subprocess.Popen", return_value=process), \
         patch("dowidget.providers.threading.Thread"):
        transport = _StdioTransport(tmp_path, False)
    with patch("dowidget.providers.time.monotonic", return_value=2):
        with pytest.raises(ProviderError) as error:
            transport.receive(1)
    assert error.value.kind == "timeout"
    transport.close()
    with patch("dowidget.providers.time.monotonic", return_value=0):
        with pytest.raises(ProviderError):
            transport.receive(1)


def test_rpc_unsupported_response_is_safe(tmp_path):
    client, transport = provider(tmp_path)
    client._ensure()
    transport.responses.append({"id": 2, "result": "SECRET"})
    with pytest.raises(ProviderError) as error:
        client.fetch()
    assert "SECRET" not in str(error.value)


def test_windows_cmd_launch_is_explicit_and_quoted(tmp_path):
    from types import SimpleNamespace
    import os
    process = Mock()
    process.poll.return_value = 0
    executable = r"C:\Program Files\nodejs\codex.cmd"
    fake_os = SimpleNamespace(name="nt", environ=dict(os.environ))
    with patch("dowidget.providers.os", fake_os), \
         patch("dowidget.providers.shutil.which", return_value=executable), \
         patch("dowidget.providers.subprocess.Popen", return_value=process) as popen, \
         patch("dowidget.providers.threading.Thread"):
        transport = _StdioTransport(tmp_path, False)
        transport.close()
    args, kwargs = popen.call_args
    assert kwargs["executable"].endswith("cmd.exe")
    assert f'""{executable}" app-server' in args[0]
    assert "/d /s /c" in args[0]
    assert "shell" not in kwargs


def test_windows_cmd_metacharacter_path_is_rejected(tmp_path):
    from types import SimpleNamespace
    import os
    with patch("dowidget.providers.os", SimpleNamespace(name="nt", environ=dict(os.environ))), \
         patch("dowidget.providers.shutil.which", return_value=r"C:\bad%PATH%\codex.cmd"), \
         patch("dowidget.providers.subprocess.Popen") as popen:
        with pytest.raises(ProviderError):
            _StdioTransport(tmp_path, False)
    popen.assert_not_called()


@pytest.mark.parametrize("method", ["account/rateLimitResetCredit/consume", "thread/start", "turn/start"])
def test_monitor_cannot_redeem_resets_or_start_quota_consuming_work(tmp_path, method):
    client, transport = provider(tmp_path)
    client._ensure()
    before = list(transport.sent)
    with pytest.raises(ProviderError) as error:
        client._rpc(method)
    assert error.value.kind == "unavailable"
    assert transport.sent == before
    assert client.fetch().windows[0].remaining == Decimal(75)
