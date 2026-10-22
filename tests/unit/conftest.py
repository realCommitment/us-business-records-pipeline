import socket

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never reach the network; a test server on 127.0.0.1 is allowed."""
    connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> None:
        if not (isinstance(address, tuple) and address[0] == "127.0.0.1"):
            raise RuntimeError(f"unit tests are offline: refused {address!r}")
        connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
