"""Bounded, read-only HTTP transport for administrative usage sources."""
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import json
import queue
import threading
import time

import requests

from .models import ProviderError

MAX_BODY = 256 * 1024
REQUEST_DEADLINE = 20.0


def retry_after(value):
    try:
        seconds = float(value)
        if not Decimal(str(seconds)).is_finite():
            return None
    except (TypeError, ValueError, OverflowError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, min(3600.0, seconds))


def _reject_constant(value):
    raise ValueError("Invalid JSON numeric constant")


def get_json(url, *, headers, provider, params=None, deadline=None):
    """GET only, no redirects; caller's deadline also bounds a pagination sequence.

    A daemon worker bounds the caller even when an individual socket read blocks.
    The worker checks the same deadline and closes its response on exit; it never
    publishes raw exceptions, bodies or headers.
    """
    if provider not in ("Claude", "Grok"):
        raise ValueError("Unsupported HTTP provider")
    deadline = min(float("inf") if deadline is None else deadline,
                   time.monotonic() + REQUEST_DEADLINE)
    invalid = provider + " returned an invalid usage response."
    timeout = provider + " request timed out."
    results = queue.Queue(maxsize=1)
    def request():
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError(timeout, "timeout")
            with requests.get(url, headers=headers, params=params,
                              timeout=(min(4.0, remaining), min(10.0, remaining)),
                              stream=True, allow_redirects=False) as response:
                status = response.status_code
                if status in (401, 403):
                    raise ProviderError(provider + " rejected the key or its permissions.", "setup_required")
                if status == 429:
                    raise ProviderError(provider + " rate limit reached.", "rate_limited",
                                        retry_after(response.headers.get("Retry-After")))
                if status >= 500:
                    raise ProviderError(provider + " is temporarily unavailable.", "unavailable")
                if status != 200:
                    raise ProviderError(provider + " could not complete the request.")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    if time.monotonic() >= deadline:
                        raise ProviderError(timeout, "timeout")
                    if len(body) + len(chunk) > MAX_BODY:
                        raise ProviderError(invalid)
                    body.extend(chunk)
                if time.monotonic() >= deadline:
                    raise ProviderError(timeout, "timeout")
                try:
                    data = json.loads(body, parse_float=Decimal,
                                      parse_constant=_reject_constant)
                except (ValueError, UnicodeError, RecursionError):
                    raise ProviderError(invalid) from None
                results.put((data, None))
        except requests.Timeout:
            results.put((None, ProviderError(timeout, "timeout")))
        except requests.RequestException:
            results.put((None, ProviderError("Could not connect to " + provider + ".", "network")))
        except ProviderError as error:
            results.put((None, error))
        except Exception:
            results.put((None, ProviderError(invalid)))

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProviderError(timeout, "timeout")
    threading.Thread(target=request, daemon=True, name="usage-get").start()
    try:
        data, error = results.get(timeout=remaining)
    except queue.Empty:
        raise ProviderError(timeout, "timeout") from None
    if error is not None:
        raise error from None
    return data
