from pathlib import Path

import duckdb
import pytest

from include.pipeline.db import connect, copy_to_parquet


def test_writes_rows_and_leaves_no_part_file(tmp_path: Path) -> None:
    dest = tmp_path / "stage" / "x.parquet"

    rows = copy_to_parquet(connect(), "select n from range(3) t(n) -- comment", dest)

    assert rows == 3
    assert duckdb.sql(f"select n from '{dest}' order by n").fetchall() == [
        (0,),
        (1,),
        (2,),
    ]
    assert [p.name for p in dest.parent.iterdir()] == ["x.parquet"]


def test_failing_query_keeps_previous_file(tmp_path: Path) -> None:
    dest = tmp_path / "x.parquet"
    copy_to_parquet(connect(), "select 1 as n", dest)
    before = dest.read_bytes()

    with pytest.raises(duckdb.InvalidInputException, match="boom"):
        copy_to_parquet(
            connect(),
            "select case when n = 900000 then error('boom') end as e"
            " from range(1000000) t(n)",
            dest,
        )

    assert dest.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["x.parquet"]


def test_params_are_bound(tmp_path: Path) -> None:
    dest = tmp_path / "x.parquet"

    copy_to_parquet(connect(), "select ?::INTEGER as n, ? as s", dest, [7, "it's"])

    assert duckdb.sql(f"select n, s from '{dest}'").fetchall() == [(7, "it's")]
