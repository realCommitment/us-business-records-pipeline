import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from include.pipeline.http import download_if_changed


class Handler(BaseHTTPRequestHandler):
    body = b"a,b\n1,2\n"
    etag = '"v1"'
    truncate = False
    gets = 0

    def do_HEAD(self) -> None:
        self.send_headers()

    def do_GET(self) -> None:
        Handler.gets += 1
        self.send_headers()
        self.wfile.write(self.body[:3] if self.truncate else self.body)

    def send_headers(self) -> None:
        self.send_response(200)
        self.send_header("ETag", self.etag)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep pytest output clean


@pytest.fixture
def url() -> Iterator[str]:
    Handler.body, Handler.etag, Handler.truncate, Handler.gets = (
        b"a,b\n1,2\n",
        '"v1"',
        False,
        0,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/loans.csv"
    server.shutdown()
    server.server_close()


def test_first_call_downloads(url: str, tmp_path: Path) -> None:
    dest = tmp_path / "loans.csv"

    assert download_if_changed(url, dest) is True

    assert dest.read_bytes() == b"a,b\n1,2\n"
    meta = json.loads((tmp_path / "loans.csv.meta.json").read_text())
    assert (meta["url"], meta["etag"], meta["bytes"]) == (url, '"v1"', 8)
    assert Handler.gets == 1


def test_unchanged_etag_sends_no_get(url: str, tmp_path: Path) -> None:
    dest = tmp_path / "loans.csv"
    download_if_changed(url, dest)

    assert download_if_changed(url, dest) is False

    assert Handler.gets == 1


def test_changed_etag_downloads_again(url: str, tmp_path: Path) -> None:
    dest = tmp_path / "loans.csv"
    download_if_changed(url, dest)
    Handler.body, Handler.etag = b"a,b\n1,2\n3,4\n", '"v2"'

    assert download_if_changed(url, dest) is True

    assert dest.read_bytes() == b"a,b\n1,2\n3,4\n"
    assert Handler.gets == 2


def test_truncated_body_raises_and_keeps_previous_file(
    url: str, tmp_path: Path
) -> None:
    dest = tmp_path / "loans.csv"
    download_if_changed(url, dest)
    Handler.body, Handler.etag, Handler.truncate = b"a,b\n1,2\n3,4\n", '"v2"', True

    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        download_if_changed(url, dest)

    assert dest.read_bytes() == b"a,b\n1,2\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "loans.csv",
        "loans.csv.meta.json",
    ]
    meta = json.loads((tmp_path / "loans.csv.meta.json").read_text())
    assert meta["etag"] == '"v1"'


def test_damaged_local_file_downloads_again(url: str, tmp_path: Path) -> None:
    dest = tmp_path / "loans.csv"
    download_if_changed(url, dest)
    dest.write_bytes(b"a,b\n")

    assert download_if_changed(url, dest) is True

    assert dest.read_bytes() == b"a,b\n1,2\n"
    assert Handler.gets == 2
