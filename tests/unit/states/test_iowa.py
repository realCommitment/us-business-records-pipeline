import dataclasses
import shutil
import threading
import zipfile
from collections.abc import Iterator
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import duckdb
import pytest

from include.pipeline.states import iowa, stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "iowa"


class Handler(BaseHTTPRequestHandler):
    body = b""

    def do_GET(self) -> None:
        # like the portal: no Content-Length, no ETag, no Last-Modified
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep pytest output clean


@pytest.fixture
def portal(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    Handler.body = (FIXTURES / "ia_business_entities.zip").read_bytes()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    local = dataclasses.replace(
        iowa.ENTITIES, url=f"http://127.0.0.1:{server.server_port}/x"
    )
    monkeypatch.setattr(iowa, "ENTITIES", local)
    yield
    server.shutdown()
    server.server_close()


def test_download_keeps_the_old_copy_when_the_hash_is_unchanged(
    portal: None, tmp_path: Path
) -> None:
    dest = tmp_path / "raw" / "ia" / "ia_business_entities.zip"

    assert iowa.download(iowa.ENTITIES, tmp_path) is True
    first = dest.stat().st_mtime_ns
    assert iowa.download(iowa.ENTITIES, tmp_path) is False
    assert dest.stat().st_mtime_ns == first
    assert not dest.with_name(dest.name + ".part").exists()

    Handler.body += b"\0"
    assert iowa.download(iowa.ENTITIES, tmp_path) is True
    assert dest.read_bytes() == Handler.body


def test_a_cut_off_download_keeps_the_good_copy(portal: None, tmp_path: Path) -> None:
    dest = tmp_path / "raw" / "ia" / "ia_business_entities.zip"
    assert iowa.download(iowa.ENTITIES, tmp_path) is True
    good = dest.read_bytes()

    Handler.body = good[: len(good) // 2]
    with pytest.raises(zipfile.BadZipFile):
        iowa.download(iowa.ENTITIES, tmp_path)

    assert dest.read_bytes() == good
    assert not dest.with_name(dest.name + ".part").exists()


def test_stage_reads_the_zipped_csv(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "ia"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)

    assert stage("ia_business_entities", tmp_path, min_rows=1) == 3

    rows = duckdb.sql(
        f"""select registry_id, name, entity_type, zip5, active, formed_date,
                   ia_ho_country, as_of
            from '{tmp_path / "stage" / "registry" / "ia_business_entities.parquet"}'
            order by registry_id"""
    ).fetchall()
    as_of = date(2026, 10, 18)
    assert rows == [
        ("019862", "HY-VEE, INC.", "DOMESTIC PROFIT", "50266", True,
         date(1938, 1, 3), "USA", as_of),
        ("072499", "FORT MADISON LODGE #374, B. P. O. E.",
         "REVISED DOMESTIC NON-PROFIT", "52627", True, date(1828, 6, 7), "USA",
         as_of),
        # a Canadian postal code of five digits is no ZIP
        ("708112", "SURESOURCE COMMODITIES ORGANIC FOOD DIVISION",
         "FOREIGN LIMITED LIABILITY COMPANY", None, True, date(2022, 4, 14), "CAN",
         as_of),
    ]  # fmt: skip
