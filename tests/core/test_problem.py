from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from core.exception import EntityNotFoundError
from core.problem import PROBLEM_MEDIA_TYPE, install_problem_handlers

# Setup a dummy app for testing error handlers
app = FastAPI()
install_problem_handlers(app)


@app.get("/validation")
async def trigger_validation(count: int):
    return {"count": count}


@app.get("/domain")
async def trigger_domain():
    # Use our custom domain exception
    raise EntityNotFoundError(entity_name="User", identifier="123")


@app.get("/http-error")
async def trigger_http_error():
    raise HTTPException(status_code=418, detail="I'm a teapot")


@app.get("/unhandled")
async def trigger_unhandled():
    raise ValueError("Database connection lost")


@app.get("/rate-limit")
async def trigger_rate_limit():
    raise RateLimitExceeded(limit="Limit exceeded")  # type: ignore[arg-type]


client = TestClient(app)


def test_validation_error_returns_problem_details():
    # Passing a string instead of an int to trigger 422
    response = client.get("/validation?count=abc")

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE

    data = response.json()
    assert data["status"] == 422
    assert data["title"] == "Unprocessable Entity"
    assert data["detail"] == "One or more fields failed request validation."
    assert "instance" in data
    assert "correlation_id" in data

    # Check invalid_params structure
    assert "invalid_params" in data
    assert len(data["invalid_params"]) == 1

    invalid_param = data["invalid_params"][0]
    assert invalid_param["name"] == "query.count"
    assert "reason" in invalid_param
    assert invalid_param["code"] == "int_parsing"


def test_domain_exception_returns_problem_details():
    response = client.get("/domain")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE

    data = response.json()
    assert data["status"] == 404
    assert data["title"] == "Entity Not Found"
    assert "User with id 123 was not found" in data["detail"]
    assert data["type"] == "about:blank"  # Default unless customized


def test_standard_http_exception_returns_problem_details():
    response = client.get("/http-error")

    assert response.status_code == 418
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE

    data = response.json()
    assert data["status"] == 418
    assert data["detail"] == "I'm a teapot"


def test_unhandled_exception_returns_500_problem_details():
    response = client.get("/unhandled")

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE

    data = response.json()
    assert data["status"] == 500
    assert data["title"] == "Internal Server Error"
    assert data["detail"] == "An internal server error occurred."
    # The actual "Database connection lost" message is logged, but intentionally hidden from the client


def test_rate_limit_exception_returns_problem_details():
    response = client.get("/rate-limit")

    assert response.status_code == 429
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE

    data = response.json()
    assert data["status"] == 429
    assert data["title"] == "Too Many Requests"
    assert "Rate limit exceeded" in data["detail"]
