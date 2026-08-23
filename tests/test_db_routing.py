"""
Unit tests for RoutingSession.get_bind() — the read/write routing decision
logic in core/database.py.

Note the class under test is the *sync* RoutingSession, not the AsyncSession
subclass: SQLAlchemy resolves binds through the sync Session that
AsyncSession proxies to, so that is the only place an override takes effect.

get_bind() only inspects a SQL clause object and returns an engine
reference; it never opens a connection, so these run without any live
Postgres dependency (not a mock — it's the real method, real engine
objects, just no I/O).
"""

import pytest
from sqlalchemy import delete, insert, select, text, update

from core.database import (
    RoutingSession,
    force_primary_var,
    primary_engine,
    replica_engine,
)
from user.models import UserModel


@pytest.fixture(autouse=True)
def _reset_force_primary():
    """Isolate force_primary_var per test — it's a global ContextVar and
    must not leak True into other tests in this file or elsewhere."""
    token = force_primary_var.set(False)
    yield
    force_primary_var.reset(token)


def _session() -> RoutingSession:
    return RoutingSession(bind=primary_engine.sync_engine)


def test_select_routes_to_replica() -> None:
    bind = _session().get_bind(clause=select(UserModel))
    assert bind is replica_engine.sync_engine


def test_insert_routes_to_primary_and_sets_sticky() -> None:
    bind = _session().get_bind(clause=insert(UserModel))
    assert bind is primary_engine.sync_engine
    assert force_primary_var.get() is True


def test_update_routes_to_primary_and_sets_sticky() -> None:
    bind = _session().get_bind(clause=update(UserModel))
    assert bind is primary_engine.sync_engine
    assert force_primary_var.get() is True


def test_delete_routes_to_primary_and_sets_sticky() -> None:
    bind = _session().get_bind(clause=delete(UserModel))
    assert bind is primary_engine.sync_engine
    assert force_primary_var.get() is True


def test_write_pins_subsequent_select_to_primary() -> None:
    """Sticky-primary: once a write happens, later reads in the same
    request must not go back to the replica (read-your-writes)."""
    session = _session()

    session.get_bind(clause=insert(UserModel))
    bind = session.get_bind(clause=select(UserModel))

    assert bind is primary_engine.sync_engine


def test_raw_text_write_keyword_routes_to_primary() -> None:
    bind = _session().get_bind(clause=text("UPDATE users SET is_active = false"))
    assert bind is primary_engine.sync_engine
    assert force_primary_var.get() is True


def test_raw_text_select_falls_back_to_primary_safety_net() -> None:
    """A raw text() SELECT is not recognized as a Select clause — get_bind()
    only sniffs text() for write keywords, so a plain text("SELECT ...")
    falls through to the primary safety net rather than the replica. This
    documents current behavior (it is not routed like select(), on purpose
    or not)."""
    bind = _session().get_bind(clause=text("SELECT 1"))
    assert bind is primary_engine.sync_engine


def test_no_clause_falls_back_to_primary_safety_net() -> None:
    bind = _session().get_bind(clause=None)
    assert bind is primary_engine.sync_engine


def test_force_primary_var_already_true_short_circuits_to_primary() -> None:
    """Even a Select clause must hit primary once force_primary_var is set —
    this is what read-after-write call sites (login, refresh, verify-email,
    reset-password) rely on."""
    force_primary_var.set(True)
    bind = _session().get_bind(clause=select(UserModel))
    assert bind is primary_engine.sync_engine
