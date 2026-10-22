import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.states import stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "district_of_columbia"
AS_OF = date(2026, 10, 17)


def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "dc"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    return raw


def test_stage_reads_past_the_bom_and_keeps_one_row_per_file_number(
    tmp_path: Path,
) -> None:
    csv = raw_dir(tmp_path) / "dc_corporations.csv"
    assert csv.read_bytes().startswith(b"\xef\xbb\xbfOBJECTID,")

    assert stage("dc_corporations", tmp_path, min_rows=1) == 4

    rows = duckdb.sql(
        f"""select registry_id, name, zip5, status, active, formed_date,
                   dc_last_report_filed, as_of
            from '{tmp_path / "stage" / "registry" / "dc_corporations.parquet"}'
            order by registry_id"""
    ).fetchall()
    assert rows == [
        ("540000", "GEORGETOWN UNIVERSITY (THE)", "20057", "Active - In Good Standing",
         True, date(1844, 6, 10), date(2026, 3, 27), AS_OF),
        ("571294", "WASHINGTON GAS LIGHT Company", "20024", "Active - In Good Standing",
         True, date(1957, 3, 25), date(2025, 3, 17), AS_OF),
        # listed twice, revoked and active: the row that filed a report last
        ("L00007017355", "PBD Consulting Service PLLC", "20017",
         "Active - In Good Standing", True, date(2021, 5, 30), date(2026, 2, 2), AS_OF),
        ("L51864", "TMC-COMPCO L.L.C.", None, "Revoked", False, date(2010, 8, 27),
         date(2013, 4, 1), AS_OF),
    ]  # fmt: skip


def test_renamed_header_raises(tmp_path: Path) -> None:
    csv = raw_dir(tmp_path) / "dc_corporations.csv"
    csv.write_bytes(csv.read_bytes().replace(b"FILE_NUMBER,", b"FILENUMBER,", 1))

    with pytest.raises(ValueError, match="header changed"):
        stage("dc_corporations", tmp_path, min_rows=1)
