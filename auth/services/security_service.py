from bcrypt import checkpw, hashpw, gensalt


class SecurityService:
    def __init__(self, repo) -> None:
        self.repo = repo

    @staticmethod
    def hash_password(password: str) -> str:
        return hashpw(password.encode(), gensalt()).decode()

    @staticmethod
    def check_password(password: str, hashed_password: str) -> bool:
        return checkpw(password.encode(), hashed_password.encode())
