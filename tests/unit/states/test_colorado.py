import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.states import stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "colorado"
AS_OF = date(2026, 10, 17)


def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "co"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    return raw


def test_stage_keeps_every_status(tmp_path: Path) -> None:
    raw_dir(tmp_path)

    assert stage("co_business_entities", tmp_path, min_rows=1) == 3

    rows = duckdb.sql(
        f"""select registry_id, norm_name, address, zip5, entity_type, status,
                   status_date, active, formed_date, as_of, co_agent_name
            from '{tmp_path / "stage" / "registry" / "co_business_entities.parquet"}'
            order by registry_id"""
    ).fetchall()
    assert rows == [
        ("18861217679", "DENVER UNION CORPROATION DISSOLVED JANUARY 17 1983",
         "1512 LARIMER STREET #760", "80202", "DPC", "Voluntarily Dissolved", None,
         False, date(1886, 3, 29), AS_OF, "JOHN O'DEA"),
        # Exists: a trust Colorado tracks no standing for, so no signal
        ("19871000035", "BIG BOTTOM DITCH", None, None, "DT", "Exists", None, None,
         date(1964, 2, 13), AS_OF, None),
        ("19871009071", "MANITOU AND PIKES PEAK RAILWAY", "555 17th Street, Suite 2400",
         "80202", "DPC", "Good Standing", None, True, date(1888, 11, 17), AS_OF,
         "C T CORPORATION SYSTEM"),
    ]  # fmt: skip


def test_renamed_header_raises(tmp_path: Path) -> None:
    csv = raw_dir(tmp_path) / "co_business_entities.csv"
    csv.write_text(csv.read_text().replace("entityid,", "entity_id,", 1))

    with pytest.raises(ValueError, match="header changed"):
        stage("co_business_entities", tmp_path, min_rows=1)
