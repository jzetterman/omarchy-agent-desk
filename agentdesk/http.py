"""HTTPS fetch with default TLS, no redirects, no proxy, deadline timeouts."""

from __future__ import annotations

import errno
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class HttpResult:
    """Outcome of one GET/POST. body is bytes on success or error payload."""

    outcome: str
    status: int | None = None
    body: bytes | None = None
    error: str | None = None


class RedirectRefused(urllib.error.HTTPError):
    """Raised by the opener when any 3xx arrives; never followed."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectRefused(req.full_url, code, msg, headers, fp)


class Http:
    """The only module that opens sockets. Verification is never disabled."""

    def __init__(self, cafile: str | None = None):
        self.cafile = cafile

    def _context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if self.cafile:
            ctx.load_verify_locations(cafile=self.cafile)
        return ctx

    def _opener(self, ctx: ssl.SSLContext) -> urllib.request.OpenerDirector:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPSHandler(context=ctx),
        )

    def get(self, url: str, headers: dict | None = None, timeout: float = 10) -> HttpResult:
        return self._request("GET", url, body=None, headers=headers, timeout=timeout)

    def post(self, url: str, body=None, headers: dict | None = None, timeout: float = 10, cap: float = 10) -> HttpResult:
        budget = min(float(cap), float(timeout))
        return self._request("POST", url, body=body, headers=headers, timeout=budget)

    def _request(self, method: str, url: str, body, headers: dict | None, timeout: float) -> HttpResult:
        if not isinstance(url, str) or not url.startswith("https://"):
            return HttpResult("failed", error="url-not-https")
        data = body if body is None or isinstance(body, bytes) else str(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            opener = self._opener(self._context())
            with opener.open(req, timeout=timeout) as resp:
                payload = resp.read()
                return HttpResult("ok", status=getattr(resp, "status", 200), body=payload)
        except RedirectRefused as exc:
            try:
                exc.close()
            except Exception:
                pass
            return HttpResult("failed", status=exc.code, error="redirect")
        except urllib.error.HTTPError as exc:
            payload = b""
            try:
                payload = exc.read()
            except Exception:
                pass
            try:
                exc.close()
            except Exception:
                pass
            if exc.code == 429:
                return HttpResult("rate-limited", status=exc.code, body=payload)
            if exc.code in (401, 403):
                return HttpResult("auth", status=exc.code, body=payload)
            return HttpResult("failed", status=exc.code, body=payload)
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.timeout):
                return HttpResult("failed", error="timeout")
            err = getattr(reason, "errno", None)
            if isinstance(reason, socket.gaierror) or err in (
                errno.ECONNREFUSED,
                errno.ENETUNREACH,
                errno.EHOSTUNREACH,
            ):
                return HttpResult("offline", error=str(reason))
            if isinstance(reason, ssl.SSLError):
                return HttpResult("failed", error="tls")
            return HttpResult("failed", error=str(reason))
        except (TimeoutError, socket.timeout):
            return HttpResult("failed", error="timeout")
        except ssl.SSLError:
            return HttpResult("failed", error="tls")
        except Exception as exc:
            return HttpResult("failed", error=exc.__class__.__name__)
