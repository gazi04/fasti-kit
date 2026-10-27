from core.exception import DomainException


class InvalidCredentialsError(DomainException):
    def __init__(self) -> None:
        super().__init__(
            detail="Invalid credentials",
            status_code=401,
            type_str="errors/invalid-credentials",
            title="Unauthorized",
        )


class InvalidTokenError(DomainException):
    def __init__(self, detail: str) -> None:
        super().__init__(
            detail=detail,
            status_code=400,
            type_str="errors/invalid-token",
            title="Invalid Token",
        )
