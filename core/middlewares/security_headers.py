from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Injects hardening headers on every HTTP response.

    HSTS is opt-in (`include_hsts=True`) because it only means anything on
    HTTPS — locally the app runs plain-HTTP behind Caddy.
    """

    def __init__(self, app: ASGIApp, include_hsts: bool = False) -> None:
        self.app = app
        self.headers: dict[str, str] = {
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            # JSON API responses ignore CSP; the server-rendered `web/` admin
            # UI is same-origin only (vendored htmx/alpine/tailwind, no CDN),
            # so 'self' is enough — form-action/base-uri don't inherit from
            # default-src, so they're listed explicitly rather than relying
            # on the browser's unrestricted default for those two.
            "Content-Security-Policy": (
                "default-src 'self'; form-action 'self'; base-uri 'self'; "
                "object-src 'none'; frame-ancestors 'none'"
            ),
            "X-Frame-Options": "DENY",
        }
        if include_hsts:
            self.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable_headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    mutable_headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
