from user.entities.user import User
from user.models import UserModel

class UserRepository:
    def __init__(self, db) -> None:
        self.db = db

    async def add(self, email: str, password_hash: str) -> User:
        model = UserModel(email=email, password_hash=password_hash)
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(id=model.id, email=model.email, full_name=model.full_name, password_hash=model.password_hash, is_active=model.is_active, create_at=model.created_at, updated_at=model.updated_at)
