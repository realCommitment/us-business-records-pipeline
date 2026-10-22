import io
import json
import zipfile
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.national.sam import newest, stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "national" / "sam"
NAME = "SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005.ZIP"
# five real records of the 2026-10-05 file, with the BOF count set to 5
DAT = FIXTURES / "SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005.dat"


def write_extract(tmp_path: Path, dat: bytes) -> None:
    """A zip holding a zip holding the .dat, as SAM.gov publishes it."""
    raw = tmp_path / "raw" / "sam"
    raw.mkdir(parents=True)
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005_897fa9aa.dat", dat)
    with zipfile.ZipFile(raw / NAME, "w") as z:
        z.writestr(NAME, inner.getvalue())


def test_newest_picks_the_latest_utf8_monthly_file() -> None:
    listing = json.loads((FIXTURES / "listfiles.json").read_text())

    assert newest(listing) == NAME


def test_stage_types_every_record(tmp_path: Path) -> None:
    write_extract(tmp_path, DAT.read_bytes())
    raw = tmp_path / "raw" / "sam" / NAME
    published = raw.read_bytes()

    assert stage(NAME, tmp_path, min_rows=1) == 5

    # the inner zip shares the outer one's name and must not replace it
    assert raw.read_bytes() == published, f"{raw}: changed by the stage"

    rows = duckdb.sql(
        f"""select uei, eft_indicator, cage, registration_status, activation_date,
                   expiration_date, norm_name, dba_name, city, state, zip5,
                   country, start_date, entity_structure, primary_naics,
                   gov_poc_last_name, elec_poc_last_name
            from '{tmp_path / "stage" / "sam_entities.parquet"}' order by uei"""
    ).fetchall()
    assert rows == [
        # the sentinel; IBM's state registry dates it to the same day
        ("J64CSQTQNRC1", None, "30874", "A", date(2026, 4, 18), date(2027, 4, 7),
         "INTERNATIONAL BUSINESS MACHINES", "IBM", "ARMONK", "NY", "10504", "USA",
         date(1911, 6, 16), "2L", "541519", "SHERMAN", "YOUNG"),
        # its division name holds a pipe inside NUL quotes; the fields stay aligned
        ("MJWHA9EU11G5", None, "9RKW3", "A", date(2026, 9, 10), date(2027, 9, 9),
         "SEH DESIGNBUILD", None, "SAINT PAUL", "MN", "55110", "USA",
         date(2000, 11, 13), "2L", None, "SPRAGUE", "SPRAGUE"),
        # two registrations in one record (A~E): the first is kept
        ("VLNHKZKSFEF3", None, "1HUX0", "A", date(2025, 9, 9), date(2027, 8, 24),
         "ENGINEERED MACHINED PRODUCTS", None, "ESCANABA", "MI", "49829", "USA",
         date(1991, 7, 31), "2L", "333996", "SCOTT", "PIFKE"),
        ("VZCLHNYYTGM7", None, "21C39", "A", date(2026, 6, 16), date(2027, 6, 4),
         "JLBB ENTERPRISES", None, "METAIRIE", "LA", "70005", "USA",
         date(2026, 5, 27), "2K", "561210", "LEA", "LEA"),
        # staged although outside the US; a Canadian postal code is no ZIP
        ("YXAQJHEXYXN8", None, "L10H9", "A", date(2026, 7, 21), date(2027, 7, 8),
         "ABRO MANUFACTURING", None, "KITCHENER", "ON", None, "CAN",
         date(2025, 5, 7), "2L", "332710", "ALI", "ALI"),
    ]  # fmt: skip


def test_a_bof_count_that_disagrees_raises(tmp_path: Path) -> None:
    dat = DAT.read_bytes().replace(b" 0000005 ", b" 0000006 ", 1)
    write_extract(tmp_path, dat)

    with pytest.raises(AssertionError, match="5 records, the BOF line says 6"):
        stage(NAME, tmp_path, min_rows=1)

    assert not (tmp_path / "stage" / "sam_entities.parquet").exists()
