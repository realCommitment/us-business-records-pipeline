import dataclasses
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline import states
from include.pipeline.states import stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "oregon"
AS_OF = date(2026, 10, 13)


def raw_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raw = tmp_path / "raw" / "or"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    # 11 fixture rows on 4 entities cannot fall in a range set for 1.6M rows
    source = states.SOURCES["or_active_businesses"]
    monkeypatch.setitem(
        states.SOURCES, source.name, dataclasses.replace(source, dropped=(7, 7))
    )
    return raw


def test_stage_makes_one_row_per_entity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir(tmp_path, monkeypatch)

    assert stage("or_active_businesses", tmp_path, min_rows=1) == 4

    rows = duckdb.sql(
        f"""select registry_id, address, zip5, address_kind, entity_type, active,
                   formed_date, officers, or_registered_agent, as_of
            from '{tmp_path / "stage" / "registry" / "or_active_businesses.parquet"}'
            order by registry_id"""
    ).fetchall()
    assert rows == [
        ("1333616", "220 NW BROADWAY", "97209", "physical",
         "DOMESTIC BUSINESS CORPORATION", True, date(1909, 2, 16), None,
         "C T CORPORATION SYSTEM", AS_OF),
        # no principal place of business, so the mailing address
        ("310292", "232 NW 6TH AVE", "97209", "mailing",
         "DOMESTIC LIMITED PARTNERSHIP", True, date(2001, 2, 8), None,
         "CENTRAL CITY CONCERN", AS_OF),
        # four rows, two of them registered agents: one deterministic pick
        ("461913", "2838 E BURNSIDE ST", "97214", "physical",
         "DOMESTIC NONPROFIT CORPORATION", True, date(1874, 9, 23), None,
         "SW & W REGISTERED AGENTS, INC.", AS_OF),
        ("70192852", "235 SE 6TH ST", "97526", "physical", "ASSUMED BUSINESS NAME",
         True, date(1964, 7, 1), ["AUTHORIZED REPRESENTATIVE: THOMAS HART"], None,
         AS_OF),
    ]  # fmt: skip


def test_renamed_header_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv = raw_dir(tmp_path, monkeypatch) / "or_active_businesses.csv"
    csv.write_text(csv.read_text().replace("Registry Number,", "Registry No,", 1))

    with pytest.raises(ValueError, match="header changed"):
        stage("or_active_businesses", tmp_path, min_rows=1)
