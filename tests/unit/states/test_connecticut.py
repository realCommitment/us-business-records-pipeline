import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.states import stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "connecticut"
AS_OF = date(2026, 10, 17)


def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "ct"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    return raw


def test_stage_joins_principals(tmp_path: Path) -> None:
    raw_dir(tmp_path)

    assert stage("ct_businesses", tmp_path, min_rows=1) == 4

    rows = duckdb.sql(
        f"""select registry_id, name, zip5, entity_type, status, status_date,
                   active, formed_date, naics, officers, ct_id, as_of
            from '{tmp_path / "stage" / "registry" / "ct_businesses.parquet"}'
            order by registry_id"""
    ).fetchall()
    assert rows == [
        # principals without a designation are listed by name
        ("0002908", "ARROW WINDOW SHADE MANUFACTURING COMPANY THE", "06109", "Stock",
         "Dissolved", date(2021, 12, 18), False, date(1961, 4, 27), "442291",
         ["KRIS T HOSKINS", "MADELYN A HOSKINS"], "001t000000WmSFEAA3", AS_OF),
        # account number 0000000 is a placeholder, so the Id stands in
        ("001eq00000FpIlWAAV", "SALSCO, LLC", None, "Unauthorized", "Active", None,
         True, date(2024, 12, 19), None, None, "001eq00000FpIlWAAV", AS_OF),
        ("0074441", "STANLEY BLACK & DECKER, INC.", "06053", "Stock", "Active", None,
         True, date(1901, 6, 4), "332510",
         ["Director: Robert Manning", "Officer: James Jeremiah Butler"],
         "001t000000WmVHCAA3", AS_OF),
        # a name reservation's 01/03/0001 is no formation date
        ("2581638", "Glacier Labs, LLC", None, None, "Expired Reservation", None,
         False, None, None, None, "001t000000tyI8AAAU", AS_OF),
    ]  # fmt: skip


def test_renamed_principals_header_raises(tmp_path: Path) -> None:
    csv = raw_dir(tmp_path) / "ct_principals.csv"
    csv.write_text(csv.read_text().replace("Unique_Key,", "UniqueKey,", 1))

    with pytest.raises(ValueError, match="header changed"):
        stage("ct_businesses", tmp_path, min_rows=1)
