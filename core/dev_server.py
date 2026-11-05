import errno
import logging
import socket

logger = logging.getLogger(__name__)


def _is_missing_address(error: OSError) -> bool:
    return error.errno == errno.EADDRNOTAVAIL


def _close_all(sockets: list[socket.socket]) -> None:
    for sock in sockets:
        sock.close()


def bind_sockets(hosts: list[str], port: int) -> list[socket.socket]:
    sockets: list[socket.socket] = []
    for host in hosts:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as error:
            sock.close()
            if not _is_missing_address(error):
                _close_all(sockets)
                raise
            logger.info("Not listening on %s: no such address on this machine", host)
            continue
        sockets.append(sock)
        logger.info("Listening on http://%s:%d", host, port)

    if not sockets:
        raise OSError(f"None of the addresses {hosts} exist on this machine")
    return sockets
