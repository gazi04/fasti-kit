from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from core.problem import PROBLEM_MEDIA_TYPE, ProblemDetails


def custom_openapi(app: FastAPI) -> dict[str, Any]:
    """
    Overrides FastAPI's default openapi schema to standardize error responses
    according to RFC 9457 (application/problem+json).
    """
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )

    components = openapi_schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})

    # 1. Register ProblemDetails and InvalidParam in OpenAPI components
    problem_schema = ProblemDetails.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )

    # Extract embedded definitions ($defs) if present and place them in components/schemas
    if "$defs" in problem_schema:
        defs = problem_schema.pop("$defs")
        for def_name, def_schema in defs.items():
            schemas[def_name] = def_schema

    schemas["ProblemDetails"] = problem_schema

    # 2. Remove FastAPI's default validation schemas from docs
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)

    # 3. Patch all endpoints to use application/problem+json for 4xx/5xx responses
    paths = openapi_schema.get("paths", {})
    for path in paths.values():
        for operation in path.values():
            if not isinstance(operation, dict):
                continue

            responses = operation.setdefault("responses", {})

            for status_code, response in list(responses.items()):
                # Check for HTTP status codes (e.g., '422', '400', '500')
                if status_code.isdigit() and int(status_code) >= 400:
                    description = response.get("description", "Error Response")
                    responses[status_code] = {
                        "description": description,
                        "content": {
                            PROBLEM_MEDIA_TYPE: {
                                "schema": {
                                    "$ref": "#/components/schemas/ProblemDetails"
                                }
                            }
                        },
                    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


def problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """
    Helper to declare RFC 9457 error responses on individual router endpoints.

    Usage:
        @router.post("/login", responses=problem_responses(401, 404, 422))
        async def login(...):
            ...
    """
    return {
        code: {
            "description": f"RFC 9457 Problem Details for status {code}",
            "model": ProblemDetails,
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        }
        for code in status_codes
    }


def setup_openapi(app: FastAPI) -> None:
    """
    Attaches the custom OpenAPI schema generator to the FastAPI app instance.
    """

    def schema_lambda() -> dict[str, Any]:
        return custom_openapi(app)

    app.openapi = schema_lambda  # type: ignore[method-assign]
