"""Pure-ASGI protections that sit in front of the whole application: request-size limit, browser security
headers (including a Content-Security-Policy that matches what the game's pages actually load) and a generic
error responder. No request or response content is ever read or logged here."""
import json
import logging
import os

log = logging.getLogger("camorra.security")

MAX_BODY_BYTES = int(os.environ.get("CAMORRA_MAX_BODY_BYTES", "65536") or 65536)   # game requests are a few hundred bytes

# The page loads: its own scripts and styles, Google Fonts (CSS + font files), its own images and sounds (also data:/blob:),
# and talks only to itself. The one inline handler (the non-blocking font stylesheet) is allowed by hash, not by 'unsafe-inline'.
FONT_ONLOAD_HASH = "'sha256-MhtPZXr7+LpJUY5qtMutB+qWfQtMaPccfe7QXtCcEYc='"
CSP = "; ".join([
    "default-src 'self'",
    f"script-src 'self' 'unsafe-hashes' {FONT_ONLOAD_HASH}",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' data: blob:",
    "media-src 'self' data: blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def _json_response(status, payload):
    body = json.dumps(payload).encode("utf-8")
    return ([(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
             (b"cache-control", b"no-store")], body, status)


async def _send(send, status, payload):
    headers, body, status = _json_response(status, payload)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Rejects request bodies larger than MAX_BODY_BYTES with 413, whether the size is announced in Content-Length or
    only discovered while the body streams in."""

    def __init__(self, app, max_bytes=None):
        self.app, self.max_bytes = app, max_bytes or MAX_BODY_BYTES

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                declared = int(declared)
            except ValueError:
                await _send(send, 400, {"detail": "Invalid Content-Length header."})
                return
        seen, started = {"n": 0}, {"v": False}

        async def counting_receive():
            message = await receive()
            if message["type"] == "http.request":
                seen["n"] += len(message.get("body", b""))
                if seen["n"] > self.max_bytes:
                    raise _TooLarge()
            return message

        async def tracking_send(message):
            if message["type"] == "http.response.start":
                started["v"] = True
            await send(message)

        try:
            if declared is not None and declared > self.max_bytes:
                raise _TooLarge()                      # announced size too big: refuse without reading the body
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started["v"]:
                await _send(send, 413, {"detail": "The request is too large."})


class SecurityHeadersMiddleware:
    """Adds conservative response headers. Nothing about the page content changes."""
    HEADERS = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
               (b"referrer-policy", b"no-referrer"), (b"content-security-policy", CSP.encode()),
               (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
               (b"cross-origin-opener-policy", b"same-origin"), (b"cross-origin-resource-policy", b"same-origin")]

    def __init__(self, app):
        self.app = app
        self.hsts = os.environ.get("CAMORRA_HSTS", "").strip() == "1"     # set when the app is served over HTTPS

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = list(self.HEADERS)
        if self.hsts:
            extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                have = {k.lower() for k, _ in message.get("headers", [])}
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [h for h in extra if h[0] not in have]
            await send(message)

        await self.app(scope, receive, send_wrapper)
