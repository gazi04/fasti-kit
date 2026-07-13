from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """The incoming JSON payload contract for logging in."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """The public API response contract: bearer token delivered in the response body."""

    access_token: str
    token_type: str = "bearer"


class ResendVerficationRequest(BaseModel):
    email: EmailStr
