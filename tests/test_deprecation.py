"""
Tests for DeprecationRoute and the @deprecated decorator.

Uses a standalone FastAPI app (no database), mirroring the pattern in
tests/test_security_headers.py.
"""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from core.deprecation import DeprecationRoute, deprecated

SUNSET = "Sat, 01 Jan 2028 00:00:00 GMT"


def _make_client() -> TestClient:
    router = APIRouter(route_class=DeprecationRoute)

    @router.get("/old")
    @deprecated(sunset=SUNSET)
    async def old():
        return {"status": "old"}

    @router.get("/old-no-sunset")
    @deprecated()
    async def old_no_sunset():
        return {"status": "old"}

    @router.get("/current")
    async def current():
        return {"status": "current"}

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_deprecated_route_sends_deprecation_and_sunset_headers() -> None:
    response = _make_client().get("/old")

    assert response.status_code == 200
    assert response.json() == {"status": "old"}
    assert response.headers["deprecation"] == "true"
    assert response.headers["sunset"] == SUNSET


def test_deprecated_route_without_sunset_omits_sunset_header() -> None:
    response = _make_client().get("/old-no-sunset")

    assert response.headers["deprecation"] == "true"
    assert "sunset" not in response.headers


def test_undecorated_route_sends_no_deprecation_headers() -> None:
    response = _make_client().get("/current")

    assert "deprecation" not in response.headers
    assert "sunset" not in response.headers


def test_deprecated_route_is_marked_in_openapi() -> None:
    paths = _make_client().app.openapi()["paths"]  # type: ignore[attr-defined]

    assert paths["/old"]["get"]["deprecated"] is True
    assert "deprecated" not in paths["/current"]["get"]
