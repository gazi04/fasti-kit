from sqlalchemy import select

from core.database import AsyncSessionLocal, bind_override_var
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
    Test 3: Assert that direct usage of AsyncSessionLocal without the bind
    override runs on its own pooled connection to the test database and
    doesn't see the fixture's uncommitted row.

    The row is flushed while the override is still active, so it lands on the
    fixture's connection. Only then is the override cleared for the second
    session; with it active, AsyncSessionLocal() would resolve to that same
    connection and the separation under test would be invisible.
    """

    user = UserModel(
        email="test_leakage_check@example.com",
        password_hash="fakehash",
        full_name="Leakage Check User",
        scopes="users:read",
    )
    db.add(user)
    await db.flush()

    override_token = bind_override_var.set(None)
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
    finally:
        bind_override_var.reset(override_token)
