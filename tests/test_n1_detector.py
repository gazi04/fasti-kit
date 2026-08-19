"""
Tests for the N+1 Query Detector middleware.

Verifies that:
  - The X-Query-Count response header is always present.
  - The query_counter fixture correctly counts queries within a test.
"""

from httpx import AsyncClient
from sqlalchemy import text


async def test_query_count_header_present(client: AsyncClient) -> None:
    """X-Query-Count header must be injected by the middleware on every response."""
    response = await client.get("/api/v1/users/me")
    assert "x-query-count" in response.headers
    count = int(response.headers["x-query-count"])
    assert count >= 0


async def test_query_counter_fixture_counts_queries(db, query_counter) -> None:
    """The query_counter fixture should increment for each SQL statement."""
    initial_count = query_counter["count"]

    # Execute a trivial query. Note: the `db` session uses join_transaction_mode=
    # "create_savepoint", so SQLAlchemy may emit a SAVEPOINT statement alongside
    # the SELECT — giving >= 1 new events rather than exactly 1.
    await db.execute(text("SELECT 1"))

    assert query_counter["count"] >= initial_count + 1


async def test_query_counter_resets_between_tests(db, query_counter) -> None:
    """Each test gets its own freshly-zeroed counter."""
    assert query_counter["count"] == 0
