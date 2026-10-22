import logging
import resource
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from include.pipeline import states
from include.pipeline.db import connect, copy_to_parquet
from include.pipeline.paths import DATA

log = logging.getLogger(__name__)

SQL = Path(__file__).parent / "sql" / "businesses.sql"
# Census 2017 NAICS codes and titles, 2 to 6 digits; PPP borrowers used 2017
# codes. Source: https://www.census.gov/naics/2017NAICS/2-6%20digit_2017_Codes.xlsx
NAICS_TITLES = Path(__file__).parent / "naics_2017.csv"
# the matched-share denominator leaves out owners who file as individuals
INDIVIDUALS = (
    "Sole Proprietorship",
    "Self-Employed Individuals",
    "Independent Contractors",
)
OPEN_STATUSES = ("likely_open", "likely_closed", "unknown")


def build(data: Path = DATA, run_date: date | None = None) -> dict[str, object]:
    """Merge every staged record into businesses.parquet; return the counts."""
    run_date = run_date or datetime.now(UTC).date()
    marts = data / "marts"
    # Decision 5: the national build does not fit in 8 GB, so its tables live
    # in a work database that spills to disk, and it gets 32 GB and every
    # core: it runs after every stage task has finished, so it never shares
    # the machine with them. The output is ordered explicitly.
    work = marts / "_work" / "build.duckdb"
    wal = work.with_name(work.name + ".wal")
    work.parent.mkdir(parents=True, exist_ok=True)
    work.unlink(missing_ok=True)
    wal.unlink(missing_ok=True)
    try:
        with connect(work) as con:
            return _build(con, data, run_date)
    finally:
        work.unlink(missing_ok=True)
        wal.unlink(missing_ok=True)
        shutil.rmtree(marts / "_work" / "tmp", ignore_errors=True)


def _build(
    con: duckdb.DuckDBPyConnection, data: Path, run_date: date
) -> dict[str, object]:
    stage, marts = data / "stage", data / "marts"
    tmp = str(marts / "_work" / "tmp").replace("'", "''")
    con.execute(f"SET temp_directory = '{tmp}'")
    con.execute("SET memory_limit = '32GB'")
    con.execute("SET preserve_insertion_order = false")
    variables: dict[str, object] = {
        "registry": states.stage_paths("registry", data),
        "dba": states.stage_paths("dba", data),
        "ppp": str(stage / "ppp.parquet"),
        "filings": str(stage / "dol_5500_filings.parquet"),
        "sba": str(stage / "sba_loans.parquet"),
        "sam": str(stage / "sam_entities.parquet"),
        "fmcsa": str(stage / "fmcsa_carriers.parquet"),
        "run_date": run_date,
        "naics_titles": str(NAICS_TITLES),
    }
    for name, value in variables.items():
        con.execute(f"SET VARIABLE {name} = ?", [value])
    con.execute(SQL.read_text())
    copy_to_parquet(
        con,
        "select * from businesses order by business_id",
        marts / "businesses.parquet",
    )
    copy_to_parquet(
        con,
        "select * from members order by source, rec_id",
        marts / "_work" / "members.parquet",
    )

    def tally(query: str) -> dict[str, int]:
        return {str(k): int(n) for k, n in con.execute(query).fetchall()}

    rows, industry, years, address, *statuses = con.execute(
        "select count(*), count(naics), count(years_in_business), "
        "count(lookup_address), "
        + ", ".join(
            f"count(*) filter (where open_status = '{s}')" for s in OPEN_STATUSES
        )
        + " from businesses"
    ).fetchall()[0]
    counts: dict[str, object] = {
        "run_date": run_date.isoformat(),
        "businesses": rows,
        "by_sources": tally(
            "select array_to_string(sources, '+'), count(*) from businesses "
            "group by 1 order by 1"
        ),
        "sponsors": tally(
            "select coalesce(plan_link, 'alone'), count(*) from spon_b "
            "group by 1 order by 1"
        ),
        "ppp_keys_by_tier": tally(
            "select coalesce(match_tier::VARCHAR, 'none'), count(*) from rec_b "
            "where source = 'ppp' group by 1 order by 1"
        ),
        "sba_keys_by_tier": tally(
            "select coalesce(match_tier::VARCHAR, 'none'), count(*) from rec_b "
            "where source = 'sba' group by 1 order by 1"
        ),
        "sam_records_by_tier": tally(
            "select coalesce(match_tier::VARCHAR, 'none'), count(*) from rec_b "
            "where source = 'sam' group by 1 order by 1"
        ),
        "fmcsa_records_by_tier": tally(
            "select coalesce(match_tier::VARCHAR, 'none'), count(*) from rec_b "
            "where source = 'fmcsa' group by 1 order by 1"
        ),
        "with_industry": industry,
        "with_years": years,
        "with_lookup_address": address,
        **dict(zip(OPEN_STATUSES, statuses, strict=True)),
    }
    # ru_maxrss is in KiB on Linux
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    log.info("build %s peak_rss_mb=%d", counts, peak)
    return counts


def qc(
    data: Path = DATA,
    min_rows: int = 3_000_000,
    min_states: int = 51,
    match_floors: dict[str, float] | None = None,
    min_sba: int = 1_280_000,
    min_sam: int = 600_000,
    min_fmcsa: int = 3_070_000,
) -> None:
    """Fail the run when the business file just written looks wrong.

    match_floors maps a registry state to its minimum matched share of PPP
    keys; by default each state's floor is its sources' min_match_share.
    """
    path = data / "marts" / "businesses.parquet"
    members = data / "marts" / "_work" / "members.parquet"
    stage = data / "stage"
    con = connect()
    for view, file in (("b", path), ("m", members)):
        quoted = str(file).replace("'", "''")
        con.execute(f"create temp view {view} as from read_parquet('{quoted}')")

    rows, unique, stateless, state_count = con.execute(
        "select count(*), count(distinct business_id), count(*) - count(state), "
        "count(distinct state) from b"
    ).fetchall()[0]
    assert rows >= min_rows, f"{path}: {rows} businesses, expected >= {min_rows}"
    assert unique == rows, f"{path}: {rows - unique} repeated business_id values"
    assert stateless == 0, f"{path}: {stateless} businesses without a state"
    assert state_count >= min_states, (
        f"{path}: {state_count} states, expected >= {min_states}"
    )
    with_sba = con.execute(
        "select count(*) from b where list_contains(sources, 'sba')"
    ).fetchall()[0][0]
    assert with_sba >= min_sba, (
        f"{path}: {with_sba} businesses with an SBA loan, expected >= {min_sba}"
    )
    with_sam = con.execute(
        "select count(*) from b where list_contains(sources, 'sam')"
    ).fetchall()[0][0]
    assert with_sam >= min_sam, (
        f"{path}: {with_sam} businesses with a SAM entity, expected >= {min_sam}"
    )
    with_fmcsa = con.execute(
        "select count(*) from b where list_contains(sources, 'fmcsa')"
    ).fetchall()[0][0]
    assert with_fmcsa >= min_fmcsa, (
        f"{path}: {with_fmcsa} businesses with an FMCSA carrier, "
        f"expected >= {min_fmcsa}"
    )

    # Conservation: every staged record is in exactly one business, and every
    # business holds a record.
    ppp, filings = stage / "ppp.parquet", stage / "dol_5500_filings.parquet"
    # source: (stage file, record key, which rows are records); a sponsor
    # that only ever filed from abroad is not a US business
    record: dict[str, tuple[Path, str, str]] = {
        "dol_5500": (filings, "ein", "state is not null"),
        "ppp": (ppp, "(norm_name, zip5)", "true"),
        "sba": (stage / "sba_loans.parquet", "(norm_name, zip5)", "true"),
        "sam": (
            stage / "sam_entities.parquet",
            "uei || coalesce('-' || eft_indicator, '')",
            "country = 'USA'",
        ),
        # a carrier abroad or without a state is staged but is no business
        "fmcsa": (
            stage / "fmcsa_carriers.parquet",
            "dot_number::VARCHAR",
            "phy_country = 'US' and phy_state is not null",
        ),
    }
    for s in states.SOURCES.values():
        record[s.name] = (states.stage_path(s, data), "registry_id", "true")
    for source, (file, key, where) in record.items():
        expected = int(
            con.execute(
                f"select count(distinct {key}) from read_parquet(?) where {where}",
                [str(file)],
            ).fetchall()[0][0]
        )
        landed, distinct = con.execute(
            "select count(*), count(distinct rec_id) from m where source = ?", [source]
        ).fetchall()[0]
        assert landed == distinct == expected, (
            f"{members}: {source} has {landed} memberships of {distinct} records, "
            f"expected each of the {expected} staged in {file} exactly once"
        )
    orphans, empty = con.execute(
        """select (select count(distinct business_id) from m
                   where business_id not in (select business_id from b)),
                  (select count(*) from b
                   where business_id not in (select business_id from m))"""
    ).fetchall()[0]
    assert orphans == 0, f"{members}: {orphans} business_id values missing from {path}"
    assert empty == 0, f"{path}: {empty} businesses hold no record in {members}"
    keys, loans = con.execute(
        "select count(distinct (norm_name, zip5)), count(*) from read_parquet(?)",
        [str(ppp)],
    ).fetchall()[0]
    key_sum, loan_sum = con.execute(
        "select sum(ppp_key_count), sum(ppp_loan_count) from b"
    ).fetchall()[0]
    assert key_sum == keys, f"{path}: sum(ppp_key_count) {key_sum}, staged {keys}"
    assert loan_sum == loans, f"{path}: sum(ppp_loan_count) {loan_sum}, staged {loans}"
    sba = stage / "sba_loans.parquet"
    sba_loans = con.execute(
        "select count(*) from read_parquet(?)", [str(sba)]
    ).fetchall()[0][0]
    sba_sum = con.execute("select sum(sba_loan_count) from b").fetchall()[0][0]
    assert sba_sum == sba_loans, (
        f"{path}: sum(sba_loan_count) {sba_sum}, staged {sba_loans} in {sba}"
    )

    # The matched share of non-individual PPP keys in each registry state.
    floors = match_floors
    if floors is None:
        floors = {}
        for s in states.SOURCES.values():
            if s.kind == "registry":
                floors[s.state] = min(floors.get(s.state, 1.0), s.min_match_share)
    shares = con.execute(
        """select k.state, count(*), count(m.match_tier)
           from m join (
               select zip5 || '|' || norm_name as rec_id,
                      arg_max(state, (date_approved, loan_number)) as state,
                      arg_max(business_type, (date_approved, loan_number))
                          as business_type
               from read_parquet(?) group by norm_name, zip5
           ) k using (rec_id)
           where m.source = 'ppp' and list_contains(?, k.state)
             and not list_contains(?, coalesce(k.business_type, ''))
           group by 1 order by 1""",
        [str(ppp), list(floors), list(INDIVIDUALS)],
    ).fetchall()
    seen = {state: (eligible, matched) for state, eligible, matched in shares}
    for state, floor in sorted(floors.items()):
        eligible, matched = seen.get(state, (0, 0))
        share = matched / eligible if eligible else 0.0
        log.info("qc %s matched_share=%.3f (%d of %d)", state, share, matched, eligible)
        assert share >= floor, (
            f"{members}: {state} matched {matched} of {eligible} PPP keys "
            f"({share:.1%}), expected >= {floor:.0%}"
        )

    bad_age, negative, bad_status, no_evidence = con.execute(
        """select count(*) filter (where (age_source is null)
                                         != (oldest_evidence_date is null)),
                  count(*) filter (where years_in_business < 0),
                  count(*) filter (where open_status is null
                                   or not list_contains(?, open_status)),
                  count(*) filter (where open_status != 'unknown'
                                   and open_evidence is null)
           from b""",
        [list(OPEN_STATUSES)],
    ).fetchall()[0]
    assert bad_age == 0, f"{path}: {bad_age} rows where age_source and date disagree"
    assert negative == 0, f"{path}: {negative} rows with negative years_in_business"
    assert bad_status == 0, f"{path}: {bad_status} rows with an invalid open_status"
    assert no_evidence == 0, f"{path}: {no_evidence} rows decided without evidence"

    for state, *coverage in con.execute(
        "select state, count(*), count(naics), count(years_in_business), "
        "count(lookup_address), "
        + ", ".join(
            f"count(*) filter (where open_status = '{s}')" for s in OPEN_STATUSES
        )
        + " from b group by 1 order by 1"
    ).fetchall():
        log.info(
            "qc coverage %s rows=%d industry=%d years=%d lookup_address=%d "
            "likely_open=%d likely_closed=%d unknown=%d",
            state, *coverage,
        )  # fmt: skip
