import socket

import pytest

from core.dev_server import bind_sockets

ADDRESS_NOT_ON_ANY_MACHINE = "192.0.2.1"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_skips_an_address_this_machine_does_not_have() -> None:
    port = _free_port()

    sockets = bind_sockets(["127.0.0.1", ADDRESS_NOT_ON_ANY_MACHINE], port)
    try:
        assert [sock.getsockname() for sock in sockets] == [("127.0.0.1", port)]
    finally:
        for sock in sockets:
            sock.close()


def test_a_taken_port_still_stops_the_server() -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]

        with pytest.raises(OSError) as raised:
            bind_sockets(["127.0.0.1"], port)

    assert "no such address" not in str(raised.value)


def test_fails_when_no_address_exists() -> None:
    with pytest.raises(OSError, match="None of the addresses"):
        bind_sockets([ADDRESS_NOT_ON_ANY_MACHINE], _free_port())
