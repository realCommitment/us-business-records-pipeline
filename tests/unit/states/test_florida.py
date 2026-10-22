import json
import os
import shutil
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.states import florida, stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "florida"

# Stands in for curl over SFTP: a listing, a one-byte read that sets the file
# time, or the whole file, sized and dated by FAKE_SIZE and FAKE_MTIME.
FAKE_CURL = """#!/bin/sh
out=""; range=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output) out="$2"; shift ;;
    --range) range="$2"; shift ;;
    --hostpubsha256|--user) shift ;;
    -*) ;;
    *) url="$1" ;;
  esac
  shift
done
case "$url" in
  */) echo "----------    1 nobody   nobody   $FAKE_SIZE Oct 07 11:45 cordata.zip" ;;
  *) if [ -n "$range" ]; then printf x > "$out"
     else head -c "$FAKE_SIZE" /dev/zero > "$out"; fi
     touch -d "@$FAKE_MTIME" "$out" ;;
esac
"""


@pytest.fixture
def fake_curl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "curl"
    script.write_text(FAKE_CURL)
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SIZE", "1000")
    monkeypatch.setenv("FAKE_MTIME", "1791387922")  # 2026-10-07 15:45:22 UTC
    return tmp_path


def test_download_skips_an_unchanged_file(
    fake_curl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = fake_curl / "raw" / "fl" / "cordata.zip"

    assert florida.download(florida.CORDATA, fake_curl) is True
    meta = json.loads(dest.with_name("cordata.zip.meta.json").read_text())
    assert (dest.stat().st_size, meta["bytes"], meta["last_modified"]) == (
        1000,
        1000,
        "Wed, 07 Oct 2026 15:45:22 GMT",
    ), f"{dest}: {dest.stat().st_size} bytes, sidecar {meta}"

    assert florida.download(florida.CORDATA, fake_curl) is False

    monkeypatch.setenv("FAKE_MTIME", "1799163922")  # three months later
    assert florida.download(florida.CORDATA, fake_curl) is True


def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "fl"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    return raw


def test_stage_cuts_the_fixed_width_records(tmp_path: Path) -> None:
    raw_dir(tmp_path)

    assert stage("fl_corporations", tmp_path, min_rows=1) == 3

    rows = duckdb.sql(
        f"""select registry_id, ein, name, address, city, zip5, entity_type, status,
                   status_date, active, formed_date, officers, as_of,
                   fl_registered_agent_name, fl_state_country, fl_address_line_2
            from '{tmp_path / "stage" / "registry" / "fl_corporations.parquet"}'
            order by registry_id"""
    ).fetchall()
    as_of = date(2026, 10, 7)
    assert rows == [
        # inactive since its last transaction
        ("000123", "650064991", "RIPLEY AND COMPANY", "4810 GALLOWAY RD, SW", "MIAMI",
         "33165", "DOMP", "I", date(1996, 8, 23), False, date(1876, 5, 15),
         ["CPTS: PAREKH, KISHOR MANUBHAI", "V: PAREKH, DIPAKRAY M.",
          "V: PAREKH VASANTIKABEN M"], as_of, "PAREKH, KISHOR MANUBHAI", "FL", None),
        ("002385", "590228455", "EAST COAST LUMBER & SUPPLY COMPANY", "308 AVE A",
         "FORT PIERCE", "34950", "DOMP", "A", date(1989, 1, 27), True,
         date(1902, 5, 15), ["VSD: OSTEEN, PAUL ALLEN", "PTD: OSTEEN, W DONALD"],
         as_of, "OSTEEN, WILLIAM D.", "FL", None),
        # the sentinel: its FEI is its EIN, and it lists six officers
        ("444750", "591517485", "RAYMOND JAMES FINANCIAL, INC.",
         "880 Carillon Parkway", "ST. PETERSBURG", "33716", "DOMP", "A",
         date(2022, 5, 20), True, date(1974, 1, 24),
         ["Chie: Konefal Richard", "Dire: Begor Mark W", "Cont: Ray Jorge",
          "Chie: Miller Brock D", "Secr: Davis AnnMarie H",
          "Assi: Serbanos E. Michael"], as_of, "CT CORPORATION SYSTEM", "FL", None),
    ]  # fmt: skip


def rezip(raw: Path, change: Callable[[dict[str, bytes]], None]) -> None:
    with zipfile.ZipFile(FIXTURES / "cordata.zip") as z:
        members = {n: z.read(n) for n in z.namelist()}
    change(members)
    with zipfile.ZipFile(raw / "cordata.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, body)


@pytest.mark.parametrize(
    "body",
    [
        lambda b: b[:-3] + b"\r\n",  # a short line
        lambda b: b + b"\r\n",  # a blank line, which reads as NULL
    ],
)
def test_a_line_of_another_width_raises(
    tmp_path: Path, body: Callable[[bytes], bytes]
) -> None:
    def change(members: dict[str, bytes]) -> None:
        members["cordata0.txt"] = body(members["cordata0.txt"])

    rezip(raw_dir(tmp_path), change)

    with pytest.raises(ValueError, match="1 lines are not 1440 characters"):
        stage("fl_corporations", tmp_path, min_rows=1)


def test_a_placeholder_fei_is_no_ein(tmp_path: Path) -> None:
    def change(members: dict[str, bytes]) -> None:
        # RIPLEY AND COMPANY's FEI, at bytes 481 to 494
        line = members["cordata1.txt"]
        members["cordata1.txt"] = line[:480] + b"999999999".ljust(14) + line[494:]

    rezip(raw_dir(tmp_path), change)
    stage("fl_corporations", tmp_path, min_rows=1)

    eins = duckdb.sql(
        f"""select registry_id, ein
            from '{tmp_path / "stage" / "registry" / "fl_corporations.parquet"}'
            order by registry_id"""
    ).fetchall()
    assert eins == [("000123", None), ("002385", "590228455"), ("444750", "591517485")]
