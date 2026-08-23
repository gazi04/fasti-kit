from sqlalchemy import select

from core.database import AsyncSessionLocal
from user.models.user_model import UserModel


async def test_a_transactional_write(db):
    """
    Test 1: Write a record to the database and commit it.
    The commit should be intercepted by the Savepoint nested transaction.
    """
    user = UserModel(
        email="test_isolation_check@example.com",
        password_hash="fakehash",
        full_name="Isolation Check User",
        scopes="users:read",
    )
    db.add(user)
    await db.commit()

    result = await db.execute(
        select(UserModel).where(UserModel.email == "test_isolation_check@example.com")
    )
    assert result.scalar_one_or_none() is not None


async def test_b_transactional_read_rollback(db):
    """
    Test 2: Assert that the record written in Test 1 is NOT present in the DB.
    This verifies that the transaction was rolled back between tests
    and isolation works.
    """
    result = await db.execute(
        select(UserModel).where(UserModel.email == "test_isolation_check@example.com")
    )
    assert result.scalar_one_or_none() is None


async def test_c_async_session_local_leakage(db):
    """
    Test 3: Assert that direct usage of AsyncSessionLocal runs on
    a different connection and doesn't see the uncommitted transaction
    of the test, and doesn't get rolled back.

    Unlike the rest of the suite, this deliberately uses the application's
    real AsyncSessionLocal factory — and therefore reads the dev database
    rather than fasti_kit_test. That separation is exactly the boundary
    under test, so it must not be pointed at the test session.
    """

    user = UserModel(
        email="test_leakage_check@example.com",
        password_hash="fakehash",
        full_name="Leakage Check User",
        scopes="users:read",
    )
    db.add(user)
    await db.flush()

    try:
        async with AsyncSessionLocal() as session2:
            result = await session2.execute(
                select(UserModel).where(
                    UserModel.email == "test_leakage_check@example.com"
                )
            )
            user_found = result.scalar_one_or_none()
            assert user_found is None, (
                "AsyncSessionLocal session should not see uncommitted data "
                "from the test session"
            )
    except Exception as e:
        print(f"AsyncSessionLocal error: {e}")
        raise
