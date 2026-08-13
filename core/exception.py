from typing import Any


class DomainException(Exception):
    """
    Base exception for all domain-level errors.
    FastAPI will catch this and format it as an RFC 7807 Problem Details JSON.
    """

    def __init__(
        self,
        detail: str,
        status_code: int = 400,
        type_str: str = "about:blank",
        title: str | None = None,
        extensions: dict[str, Any] | None = None,
    ):
        self.detail = detail
        self.status_code = status_code
        self.type_str = type_str
        self.title = title
        self.extensions = extensions
        super().__init__(detail)


class EntityNotFoundError(DomainException):
    def __init__(self, entity_name: str, identifier: str | int):
        super().__init__(
            detail=f"{entity_name} with identifier '{identifier}' was not found.",
            status_code=404,
            type_str="errors/not-found",
            title="Entity Not Found",
        )


class UnauthorizedActionError(DomainException):
    def __init__(
        self, detail: str = "You do not have permission to perform this action."
    ):
        super().__init__(
            detail=detail,
            status_code=403,
            type_str="errors/unauthorized-action",
            title="Forbidden",
        )


class ConflictError(DomainException):
    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            status_code=409,
            type_str="errors/conflict",
            title="Resource Conflict",
        )
