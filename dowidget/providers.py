"""Read-only balance and Codex subscription adapters; never issue model requests.

Codex owns authentication in the supplied, DoWidget-only CODEX_HOME. The -c
credential-store override requires OS keyring storage for persistent sessions
(no plaintext fallback), or keeps the session in the running server's memory.
Only stable stdio account APIs are used; these are not general ChatGPT limits.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit
import webbrowser

import requests

from .models import Balance, ProviderError, Snapshot, UsageWindow, remaining_percentage

MAX_BODY = 256 * 1024
RPC_TIMEOUT = 20.0
LOGIN_TIMEOUT = 180.0
MAX_RETRY_AFTER = 3600.0
DEEPSEEK_INVALID = "DeepSeek returned an invalid balance response."
CODEX_PROTOCOL = "Codex returned an invalid or unsupported response."
CODEX_REQUEST = "Codex could not complete the request."
CODEX_SETUP = "Sign in to Codex with ChatGPT to view subscription usage."


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        if not Decimal(str(seconds)).is_finite():
            return None
    except (ValueError, OverflowError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, min(MAX_RETRY_AFTER, seconds))


def _balance_amount(value) -> Decimal:
    if not isinstance(value, str):
        raise ProviderError(DEEPSEEK_INVALID)
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ProviderError(DEEPSEEK_INVALID) from None
    if not amount.is_finite():
        raise ProviderError(DEEPSEEK_INVALID)
    return amount


def parse_deepseek(data) -> Snapshot:
    if not isinstance(data, dict) or not isinstance(data.get("is_available"), bool):
        raise ProviderError(DEEPSEEK_INVALID)
    rows = data.get("balance_infos")
    if not isinstance(rows, list) or not rows:
        raise ProviderError(DEEPSEEK_INVALID)
    balances = []
    for row in rows:
        if not isinstance(row, dict) or row.get("currency") not in ("CNY", "USD"):
            raise ProviderError(DEEPSEEK_INVALID)
        balances.append(Balance(row["currency"], _balance_amount(row.get("total_balance")),
                                _balance_amount(row.get("granted_balance")),
                                _balance_amount(row.get("topped_up_balance"))))
    return Snapshot(balances=tuple(balances), note=("Balance available for API calls." if
                    data["is_available"] else "Balance is not sufficient for API calls."))


class DeepSeekProvider:
    def fetch(self, key: str) -> Snapshot:
        deadline = time.monotonic() + RPC_TIMEOUT
        try:
            with requests.get("https://api.deepseek.com/user/balance",
                              headers={"Authorization": "Bearer " + key},
                              timeout=(4, 10), stream=True, allow_redirects=False) as response:
                status = response.status_code
                if status in (401, 403):
                    raise ProviderError("DeepSeek rejected the API key.", "setup_required")
                if status == 429:
                    raise ProviderError("DeepSeek rate limit reached.", "rate_limited",
                                        _retry_after(response.headers.get("Retry-After")))
                if status >= 500:
                    raise ProviderError("DeepSeek is temporarily unavailable.", "unavailable")
                if status != 200:
                    raise ProviderError("DeepSeek could not complete the request.")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    # Socket reads can take another 10s; the whole stream is
                    # therefore bounded to roughly 30s even for slow senders.
                    if time.monotonic() >= deadline:
                        raise ProviderError("DeepSeek request timed out.", "timeout")
                    if len(body) + len(chunk) > MAX_BODY:
                        raise ProviderError(DEEPSEEK_INVALID)
                    body.extend(chunk)
                try:
                    data = json.loads(body, parse_float=Decimal)
                except (ValueError, UnicodeError, RecursionError):
                    raise ProviderError(DEEPSEEK_INVALID) from None
                return parse_deepseek(data)
        except requests.Timeout:
            raise ProviderError("DeepSeek request timed out.", "timeout") from None
        except requests.RequestException:
            raise ProviderError("Could not connect to DeepSeek.", "network") from None


def _reset(value) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        if value < 0:
            return None
        return datetime.fromtimestamp(float(value), timezone.utc)
    except (ValueError, OverflowError, OSError, InvalidOperation):
        return None


def _duration(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return ""
    try:
        minutes = Decimal(str(value))
        if not minutes.is_finite() or minutes <= 0:
            return ""
        if minutes % 10080 == 0:
            return f"{minutes / 10080:g} week"
        if minutes % 1440 == 0:
            return f"{minutes / 1440:g} day"
        if minutes % 60 == 0:
            return f"{minutes / 60:g} hour"
        return f"{minutes:g} minute"
    except InvalidOperation:
        return ""


def parse_codex_limits(data) -> Snapshot:
    if not isinstance(data, dict):
        raise ProviderError(CODEX_PROTOCOL)
    if "rateLimitsByLimitId" in data:
        buckets = data["rateLimitsByLimitId"]
        if not isinstance(buckets, dict):
            raise ProviderError(CODEX_PROTOCOL)
    else:
        bucket = data.get("rateLimits")
        buckets = {"codex": bucket} if isinstance(bucket, dict) else {}
    windows = []
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        limit_id = bucket.get("limitId") or key
        if not isinstance(limit_id, str) or not (limit_id == "codex" or limit_id.startswith("codex_")):
            continue
        label = bucket.get("limitName") or limit_id
        if not isinstance(label, str):
            label = limit_id
        # Bound provider-supplied display labels; never display response errors.
        label = " ".join(label.split())[:100]
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if not isinstance(window, dict):
                continue
            duration = _duration(window.get("windowDurationMins"))
            name = f"{label} · {slot}" + (f" ({duration})" if duration else "")
            windows.append(UsageWindow(name, remaining_percentage(used_percent=window.get("usedPercent")),
                                       _reset(window.get("resetsAt"))))
    if not windows:
        raise ProviderError("Codex subscription usage is unavailable.", "unavailable")
    return Snapshot(windows=tuple(windows), note="Codex subscription limits only; not general ChatGPT usage.")


class _StdioTransport:
    """Bounded JSONL transport. close() can interrupt another thread's receive."""
    def __init__(self, home: Path, persistent: bool):
        executable = shutil.which("codex")
        if not executable:
            raise ProviderError("Install the official Codex CLI and add codex to PATH.", "setup_required")
        try:
            home.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ProviderError("Could not create DoWidget's isolated Codex home.", "setup_required") from None
        env = {k: v for k, v in os.environ.items()
               if not (k.upper().endswith(("_API_KEY", "_ACCESS_TOKEN", "_AUTH_TOKEN"))
                       or k.upper().startswith(("OPENAI_", "AZURE_OPENAI_", "ANTHROPIC_", "CODEX_",
                                                "AWS_", "BEDROCK_", "DEEPSEEK_", "GEMINI_", "GOOGLE_")))}
        env["CODEX_HOME"] = str(home.resolve())
        store = "keyring" if persistent else "ephemeral"
        args = [executable, "app-server", "-c", f"cli_auth_credentials_store='{store}'"]
        launch_executable = None
        if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
            if any(c in executable for c in '%!&|<>^"\r\n'):
                raise ProviderError(CODEX_REQUEST)
            launch_executable = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe")
            args = f'"{launch_executable}" /d /s /c ""{executable}" app-server -c cli_auth_credentials_store=\'{store}\'"'
        try:
            self.process = subprocess.Popen(args, executable=launch_executable, cwd=home,
                                            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, bufsize=0,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            raise ProviderError("Could not start the official Codex CLI.", "setup_required") from None
        self.messages = queue.Queue(maxsize=64)
        self.closed = threading.Event()
        self.reader = threading.Thread(target=self._read, daemon=True, name="dowidget-codex-reader")
        self.reader.start()

    def _read(self):
        try:
            while not self.closed.is_set():
                line = self.process.stdout.readline(MAX_BODY + 1)
                if not line or len(line) > MAX_BODY or not line.endswith(b"\n"):
                    break
                try:
                    message = json.loads(line, parse_float=Decimal)
                except (ValueError, UnicodeError, RecursionError):
                    break
                if not isinstance(message, dict):
                    break
                try:
                    self.messages.put_nowait(message)
                except queue.Full:
                    break
        except (OSError, ValueError):
            pass
        finally:
            self.closed.set()

    def send(self, message):
        if self.closed.is_set():
            raise ProviderError(CODEX_REQUEST)
        try:
            self.process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise ProviderError(CODEX_REQUEST) from None

    def receive(self, deadline):
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ProviderError("Codex request timed out.", "timeout")
            try:
                return self.messages.get(timeout=min(left, 0.1))
            except queue.Empty:
                if self.closed.is_set():
                    raise ProviderError(CODEX_REQUEST)

    def close(self):
        self.closed.set()
        try:
            if self.process.poll() is None:
                if os.name == "nt":
                    # npm's .cmd launcher has a child node process; terminate
                    # the whole owned tree before its parent disappears.
                    taskkill = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) /
                                   "System32" / "taskkill.exe")
                    try:
                        subprocess.run([taskkill, "/PID", str(self.process.pid), "/T", "/F"],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=0.5,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                self.process.terminate()
                try:
                    self.process.wait(timeout=0.75)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=0.75)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


class CodexProvider:
    """Methods are serialized by the UI; close may run concurrently at shutdown."""
    def __init__(self, home: Path, persistent: bool, *, transport_factory=_StdioTransport):
        self.home = Path(home)
        self.persistent = persistent
        self._factory = transport_factory
        self._transport = None
        self._id = 0
        self._notifications = deque(maxlen=64)
        self._closed = threading.Event()
        self._lifecycle_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return shutil.which("codex") is not None

    def _ensure(self):
        with self._lifecycle_lock:
            if self._closed.is_set():
                raise ProviderError(CODEX_REQUEST)
            if self._transport is not None:
                return
            self._transport = self._factory(self.home, self.persistent)
            transport = self._transport
        try:
            self._rpc("initialize", {"clientInfo": {"name": "dowidget", "title": "DoWidget", "version": "0.1.0"}})
            transport.send({"method": "initialized", "params": {}})
        except ProviderError:
            self._drop_transport()
            raise

    def _drop_transport(self):
        with self._lifecycle_lock:
            transport, self._transport = self._transport, None
        if transport:
            transport.close()
        self._notifications.clear()

    def _rpc(self, method, params=None):
        if method not in ("initialize", "account/read", "account/rateLimits/read",
                          "account/login/start", "account/logout"):
            raise ProviderError("DoWidget permits only authentication and read-only account usage methods.", "unavailable")
        transport = self._transport
        if transport is None or self._closed.is_set():
            raise ProviderError(CODEX_REQUEST)
        self._id += 1
        request_id = self._id
        try:
            transport.send({"id": request_id, "method": method, "params": params or {}})
        except ProviderError:
            self._drop_transport()
            raise
        deadline = time.monotonic() + RPC_TIMEOUT
        while True:
            try:
                message = transport.receive(deadline)
            except ProviderError:
                self._drop_transport()
                raise
            if message.get("id") == request_id:
                if "error" in message:
                    raise ProviderError(CODEX_REQUEST)
                result = message.get("result")
                if not isinstance(result, dict):
                    raise ProviderError(CODEX_PROTOCOL)
                return result
            if "id" in message:
                raise ProviderError(CODEX_PROTOCOL)
            if message.get("method") == "account/login/completed":
                self._notifications.append(message)

    def fetch(self) -> Snapshot:
        self._ensure()
        account = self._rpc("account/read", {"refreshToken": True}).get("account")
        if not isinstance(account, dict) or account.get("type") != "chatgpt":
            raise ProviderError(CODEX_SETUP, "setup_required")
        return parse_codex_limits(self._rpc("account/rateLimits/read"))

    def login(self) -> None:
        self._ensure()
        result = self._rpc("account/login/start", {"type": "chatgpt"})
        url, login_id = result.get("authUrl"), result.get("loginId")
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
            valid = (parsed is not None and parsed.scheme == "https" and
                     parsed.hostname in ("chatgpt.com", "auth.openai.com") and
                     parsed.port in (None, 443) and not parsed.username and not parsed.password and
                     not any(c.isspace() or ord(c) < 32 for c in url))
        except ValueError:
            valid = False
        if not valid or not isinstance(login_id, str) or not login_id or result.get("type") != "chatgpt":
            raise ProviderError(CODEX_PROTOCOL)
        try:
            opened = webbrowser.open(url)
        except Exception:
            raise ProviderError("Could not open the Codex sign-in browser.") from None
        if not opened:
            raise ProviderError("Could not open the Codex sign-in browser.")
        deadline = time.monotonic() + LOGIN_TIMEOUT
        transport = self._transport
        if transport is None:
            raise ProviderError(CODEX_REQUEST)
        while True:
            if self._closed.is_set():
                raise ProviderError(CODEX_REQUEST)
            if time.monotonic() >= deadline:
                raise ProviderError("Codex request timed out.", "timeout")
            message = self._notifications.popleft() if self._notifications else transport.receive(deadline)
            if "id" in message:
                raise ProviderError(CODEX_PROTOCOL)
            if message.get("method") != "account/login/completed":
                continue
            params = message.get("params")
            if not isinstance(params, dict):
                raise ProviderError(CODEX_PROTOCOL)
            if params.get("loginId") != login_id:
                continue
            if params.get("success") is not True:
                raise ProviderError("Codex sign-in did not complete.", "setup_required")
            return

    def logout(self) -> None:
        self._ensure()
        self._rpc("account/logout")

    def close(self) -> None:
        self._closed.set()
        self._drop_transport()
