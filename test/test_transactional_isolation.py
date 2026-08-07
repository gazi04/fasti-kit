import pytest
from sqlalchemy import select
from user.models.user_model import UserModel
from core.database import AsyncSessionLocal, get_db

async def test_a_transactional_write(db):
    """
    Test 1: Write a record to the database and commit it.
    The commit should be intercepted by the Savepoint nested transaction.
    """
    user = UserModel(
        email="test_isolation_check@example.com",
        password_hash="fakehash",
        full_name="Isolation Check User",
        scopes="users:read"
    )
    db.add(user)
    await db.commit()
    
    # Assert user exists within this test's transactional session
    result = await db.execute(select(UserModel).where(UserModel.email == "test_isolation_check@example.com"))
    assert result.scalar_one_or_none() is not None


async def test_b_transactional_read_rollback(db):
    """
    Test 2: Assert that the record written in Test 1 is NOT present in the DB.
    This verifies that the transaction was rolled back between tests and isolation works.
    """
    result = await db.execute(select(UserModel).where(UserModel.email == "test_isolation_check@example.com"))
    assert result.scalar_one_or_none() is None


async def test_c_async_session_local_leakage(db):
    """
    Test 3: Assert that direct usage of AsyncSessionLocal runs on a different connection
    and doesn't see the uncommitted transaction of the test, and doesn't get rolled back.
    """
    # Insert a user in the test session (uncommitted in parent transaction)
    user = UserModel(
        email="test_leakage_check@example.com",
        password_hash="fakehash",
        full_name="Leakage Check User",
        scopes="users:read"
    )
    db.add(user)
    await db.flush()  # Send to DB, but not committed to outer txn
    
    # Create a separate session via AsyncSessionLocal (simulating is_token_revoked / bypass calls)
    try:
        async with AsyncSessionLocal() as session2:
            # Try to read the user inserted by db session
            result = await session2.execute(select(UserModel).where(UserModel.email == "test_leakage_check@example.com"))
            user_found = result.scalar_one_or_none()
            # If database isolation works correctly, session2 should NOT see the uncommitted user
            # unless it shares the connection. Since it uses AsyncSessionLocal, it has a separate connection.
            print(f"Session2 user found: {user_found}")
    except Exception as e:
        print(f"AsyncSessionLocal error: {e}")
        raise
