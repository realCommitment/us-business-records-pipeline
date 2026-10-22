import os
from pathlib import Path
from typing import Literal

import duckdb

from include.pipeline.names import NAME_MACROS


def connect(database: Path | None = None) -> duckdb.DuckDBPyConnection:
    """An in-memory connection, or one on a database file whose tables spill."""
    # Below Airflow's own processes, never above where it already is: at full
    # priority a build or the Florida stage on every core starved the
    # scheduler and the API server, so Airflow killed a task as orphaned and
    # a retried XCom push failed (spec 13 notes). DuckDB's threads, started
    # here, inherit it; every idle core is still used.
    os.setpriority(os.PRIO_PROCESS, 0, max(os.getpriority(os.PRIO_PROCESS, 0), 10))
    con = duckdb.connect(database or ":memory:")
    # up to five stage tasks run at once (three state stages, PPP and DOL);
    # DuckDB's default of 80% of RAM each could OOM the machine
    con.execute("SET memory_limit = '8GB'")
    con.execute(NAME_MACROS)
    return con


def copy_to_parquet(
    con: duckdb.DuckDBPyConnection,
    query: str,
    dest: Path,
    params: list[object] | None = None,
    fmt: Literal["parquet", "csv"] = "parquet",
) -> int:
    """Write the query's rows to dest through a .part file and return the count.

    On failure the .part file is removed and the previous dest is left untouched.
    fmt="csv" writes a CSV with a header row instead.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        quoted = str(part).replace("'", "''")
        # the newlines keep a trailing -- comment in query from eating the ")"
        copy = f"COPY (\n{query}\n) TO '{quoted}' (FORMAT {fmt})"
        rows = int(con.execute(copy, params).fetchall()[0][0])  # COPY returns its count
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return rows
