from typing import Annotated

from pydantic import AfterValidator

BCRYPT_MAX_PASSWORD_BYTES = 72


def fits_bcrypt(password: str) -> bool:
    return len(password.encode()) <= BCRYPT_MAX_PASSWORD_BYTES


def _require_bcrypt_length(password: str) -> str:
    if not fits_bcrypt(password):
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes long."
        )
    return password


NewPassword = Annotated[str, AfterValidator(_require_bcrypt_length)]
