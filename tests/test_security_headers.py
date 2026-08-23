"""
Tests for the SecurityHeadersMiddleware.

Uses a standalone FastAPI app (no database), mirroring the pattern in
tests/core/test_problem.py.
"""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.middlewares.security_headers import SecurityHeadersMiddleware

EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "x-frame-options": "DENY",
}


def _make_app(include_hsts: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, include_hsts=include_hsts)

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @app.get("/error")
    async def error():
        raise HTTPException(400, detail="nope")

    return app


def test_security_headers_present_on_success():
    client = TestClient(_make_app())
    response = client.get("/ok")

    assert response.status_code == 200
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers[name] == value
    # HSTS only makes sense on HTTPS; must be off by default (local dev).
    assert "strict-transport-security" not in response.headers


def test_security_headers_present_on_error_response():
    """Headers must also ride on error responses, not just 200s."""
    client = TestClient(_make_app())
    response = client.get("/error")

    assert response.status_code == 400
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers[name] == value


def test_hsts_present_when_enabled():
    """main.py enables this when ENVIRONMENT=production."""
    client = TestClient(_make_app(include_hsts=True))
    hsts = client.get("/ok").headers["strict-transport-security"]

    assert "max-age=31536000" in hsts
