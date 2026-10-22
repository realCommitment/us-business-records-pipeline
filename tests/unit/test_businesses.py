from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline import states
from include.pipeline.businesses import build, qc
from tests.fixtures.businesses.make_fixtures import SOURCES, write_stage

DAY = date(2026, 10, 17)
CONSUMER_QUERY = """
    select registry_id from '{path}'
    where state = 'TX' and list_contains(sources, 'ppp') and years_in_business >= 30
      and not nonprofit and not charged_off
      and (active or (not list_contains(sources, 'tx_franchise')
                      and entity_type in ('S', 'IS', 'PB', 'PI')))
      and not regexp_matches(coalesce(naics, ''), '^(813|814|92)')
    order by registry_id"""


def businesses(data: Path) -> Path:
    return data / "marts" / "businesses.parquet"


def row(data: Path, business_id: str, columns: str) -> tuple[object, ...]:
    rows = duckdb.sql(
        f"select {columns} from '{businesses(data)}' where business_id = ?",
        params=[business_id],
    ).fetchall()
    assert len(rows) == 1, f"{businesses(data)}: {len(rows)} rows for {business_id}"
    return rows[0]


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # the fixture stages Texas and a fixture IL registry, not every state
    monkeypatch.setattr(states, "SOURCES", SOURCES)
    write_stage(tmp_path)
    counts = build(tmp_path, DAY)
    assert counts == {
        "run_date": "2026-10-17",
        "businesses": 54,
        "by_sources": {
            "dol_5500": 4,
            "dol_5500+il_registry+ppp": 1,
            "dol_5500+ppp": 4,
            "dol_5500+ppp+tx_franchise": 4,
            "dol_5500+ppp+tx_franchise+tx_sales_outlets": 1,
            "dol_5500+tx_franchise": 1,
            "fmcsa": 3,
            "fmcsa+ppp": 1,
            "fmcsa+ppp+tx_franchise": 1,
            "il_registry+ppp+sam": 1,
            "il_registry+ppp+sba": 2,
            "ppp": 5,
            "ppp+sam": 2,
            "ppp+sba": 1,
            "ppp+tx_franchise": 8,
            "ppp+tx_sales_outlets": 2,
            "sam": 3,
            "sba": 1,
            "tx_franchise": 8,
            "tx_sales_outlets": 1,
        },
        "sponsors": {"alone": 8, "ein": 4, "hop": 2, "name": 1},
        "ppp_keys_by_tier": {
            "1": 14, "2": 2, "3": 3, "4": 2, "5": 2, "6": 1, "7": 1, "none": 9,
        },
        "sba_keys_by_tier": {"1": 1, "none": 3},
        "sam_records_by_tier": {"1": 1, "none": 6},
        "fmcsa_records_by_tier": {"1": 1, "none": 4},
        "with_industry": 46,
        "with_years": 53,
        "with_lookup_address": 53,
        "likely_open": 43,
        "likely_closed": 4,
        "unknown": 7,
    }  # fmt: skip
    return tmp_path


def test_consumer_query_reproduces_the_phase_1_shortlist(built: Path) -> None:
    rows = duckdb.sql(CONSUMER_QUERY.format(path=businesses(built))).fetchall()

    assert [r[0] for r in rows] == [
        "17411111116", "17422222224", "17433333332", "17455555556", "17512121212",
        "17513131313", "17514141414", "17516161616", "17540404040", "32012345678",
    ]  # fmt: skip


def test_every_record_lands_in_exactly_one_business(built: Path) -> None:
    members = built / "marts" / "_work" / "members.parquet"
    counts = duckdb.sql(
        f"select source, count(*), count(distinct rec_id) from '{members}' "
        "group by 1 order by 1"
    ).fetchall()

    assert counts == [
        ("dol_5500", 15, 15),
        # the carriers abroad or without a state are staged but are no business
        ("fmcsa", 5, 5),
        ("il_registry", 4, 4),
        ("ppp", 34, 34),
        ("sam", 7, 7),
        ("sba", 4, 4),
        ("tx_franchise", 23, 23),
        ("tx_sales_outlets", 4, 4),
    ]
    qc(built, min_rows=1, min_states=7, min_sba=1, min_sam=1, min_fmcsa=1)


@pytest.mark.parametrize(
    ("business_id", "expected"),
    [
        # ACME: tier 1, sponsor by EIN, the lowest outlet number is the lookup
        ("EIN-741111111", (["dol_5500", "ppp", "tx_franchise", "tx_sales_outlets"],
         "17411111116", "ACME PLUMBING", "1200 MAIN ST", "tx_sales_outlets",
         "5555550100", "238220", "ppp", 40, "formed", "likely_open",
         "tx_franchise good standing 2026-10-10", 1, "ein")),
        # the outlet DBA, not the legal name, is the lookup name (tier 4)
        ("TX-32012345678", (["ppp", "tx_sales_outlets"], "32012345678",
         "LOPEZ TIRE SHOP", "301 E MAIN ST", "tx_sales_outlets", None, "811111",
         "ppp", 41, "first_sales", "likely_open",
         "tx_sales_outlets listed 2026-10-10", 4, None)),
        # a franchise entity with no other record, right to transact A
        ("EIN-752020202", (["tx_franchise"], "17520202020", "VICTOR VENDING INC",
         "1 COIN CT", "tx_franchise", None, None, None, 34, "formed", "likely_open",
         "tx_franchise good standing 2026-10-10", None, None)),
        # forfeited, no other record: closed on its status date
        ("EIN-752121212", (["tx_franchise"], "17521212121",
         "WHISKEY WELL SERVICE INC", "2 DERRICK RD", "tx_franchise", None, None,
         None, 45, "formed", "likely_closed",
         "tx_franchise not in good standing 2015-03-01", None, None)),
        # franchise tax not established (U) gives no signal, and a charter date
        # after run_date is no evidence
        ("EIN-753232323", (["tx_franchise"], "17532323232", "GOLF START LLC",
         "3 TEE DR", "tx_franchise", None, None, None, None, None, "unknown",
         None, None, None)),
        # an outlet-only sole proprietor with no PPP loan
        ("TX-32077777777", (["tx_sales_outlets"], "32077777777",
         "XRAY SHOE REPAIR", "5 HEEL ST", "tx_sales_outlets", None, "811430",
         "tx_sales_outlets", 38, "first_sales", "likely_open",
         "tx_sales_outlets listed 2026-10-10", None, None)),
        # sponsor-only: the plan dates it, the business code is the industry,
        # and the sponsor's DBA is the trading name
        # two filings: the plan date is the older one's
        ("EIN-760000001", (["dol_5500"], None, "YANKEE TOOLS", "40 LATHE ST",
         "dol_5500", "5555550100", "333514", "dol_5500", 51, "plan",
         "likely_open", "form 5500 received 2025-07-01", None, None)),
        # a sponsor joined by name to a franchise row without an EIN
        ("TX-32088888888", (["dol_5500", "tx_franchise"], "32088888888",
         "ZULU PAVING CO", "10 TAR RD", "tx_franchise", "5555550100", "237310",
         "dol_5500", 41, "plan", "likely_open",
         "tx_franchise good standing 2026-10-10", None, "name")),
        # the namesake franchise row carries another EIN: two businesses
        ("EIN-753030303", (["tx_franchise"], "17530303030", "ALPHA DRILLING INC",
         "1 RIG RD", "tx_franchise", None, None, None, 27, "formed", "likely_open",
         "tx_franchise good standing 2026-10-10", None, None)),
        ("EIN-760000003", (["dol_5500"], None, "ALPHA DRILLING INC", "1 RIG RD",
         "dol_5500", "5555550100", "213111", "dol_5500", 23, "plan",
         "likely_open", "form 5500 received 2025-07-01", None, None)),
        # a PPP key that only a sponsor fits, in tier 5
        ("EIN-760000004", (["dol_5500", "ppp"], None, "BETA BOILER SERVICE",
         "3 STEAM ST", "ppp", "5555550100", "238220", "ppp", 32, "plan",
         "likely_open", "form 5500 received 2025-07-01", 5, None)),
        # the hop: a lone sponsor whose one tier-5 key is in DELTA's business
        ("EIN-753131313", (["dol_5500", "ppp", "tx_franchise"], "17531313131",
         "DELTA DENTAL LAB INC", "20 TOOTH LN", "ppp", "5555550100", "339116",
         "ppp", 21, "formed", "likely_open",
         "tx_franchise good standing 2026-10-10", 1, "hop")),
        # PPP-only: dated by the loan, too old a signal to say
        ("KEY-76701-HOTEL INDIA SIGNS", (["ppp"], None, "HOTEL INDIA SIGNS",
         "44 SIGN ST", "ppp", None, "339950", "ppp", 6, "ppp_loan", "unknown",
         "ppp loan approved 2020-05-01", None, None)),
        # PPP-only and charged off
        ("KEY-77801-UNIFORM BAKERY", (["ppp"], None, "UNIFORM BAKERY",
         "8 FLOUR ST", "ppp", None, "311811", "ppp", 6, "ppp_loan",
         "likely_closed", "ppp loan charged off 2023-06-01", None, None)),
        # tier 2 in Illinois, which sits in another ZIP of Springfield
        # its SBA borrower, at an old address, follows the PPP key in
        ("IL-0001", (["il_registry", "ppp", "sba"], "0001", "SPRINGFIELD PLUMBING INC",
         "40 OAK ST", "ppp", None, "238220", "ppp", 71, "formed", "likely_open",
         "il_registry good standing 2026-10-01", 2, None)),
        # the same name in Missouri, which has no registry: tier 2 never
        # crosses a state line
        # its 1990 SBA loan under the same key dates it
        ("KEY-65801-SPRINGFIELD PLUMBING", (["ppp", "sba"], None,
         "SPRINGFIELD PLUMBING INC", "9 ELM ST", "ppp", None, "238220", "ppp", 36,
         "sba_loan", "unknown", "ppp loan approved 2020-05-01", None, None)),
        # SBA-only, charged off in 2009: no lookup address from SBA
        ("KEY-74103-TULSA TIRE", (["sba"], None, "TULSA TIRE CO", None, None, None,
         "441320", "sba", 21, "sba_loan", "likely_closed",
         "sba loan charged off 2009-06-01", None, None)),
        # Ohio has no registry: sponsors joined in tiers 5, 6 and 7
        ("EIN-310000001", (["dol_5500", "ppp"], None, "OHIO VALVE CO",
         "12 MARKET ST", "ppp", "5555550100", "238220", "ppp", 46, "plan",
         "likely_open", "form 5500 received 2025-07-01", 5, None)),
        ("EIN-340000002", (["dol_5500", "ppp"], None, "CLEVELAND CRANE SERVICE",
         "800 LAKE AVE", "ppp", "5555550100", "238220", "ppp", 36, "plan",
         "likely_open", "form 5500 received 2025-07-01", 6, None)),
        ("EIN-310000003", (["dol_5500", "ppp"], None, "COLUMBUS CABINETRY",
         "100 N HIGH ST", "ppp", "5555550100", "238220", "ppp", 27, "plan",
         "likely_open", "form 5500 received 2025-07-01", 7, None)),
        # the hop into an IL registry business without an EIN
        ("IL-0002", (["dol_5500", "il_registry", "ppp"], "0002", "PEORIA PRINTING",
         "100 MAIN ST", "ppp", "5555550100", "238220", "ppp", 55, "formed",
         "likely_open", "il_registry good standing 2026-10-01", 3, "hop")),
        # one sponsor fits keys of two registry businesses: no hop, three rows
        ("IL-0003", (["il_registry", "ppp", "sba"], "0003", "ROCKFORD TOOL", "1 A ST",
         "ppp", None, "238220", "ppp", 66, "formed", "likely_open",
         "il_registry good standing 2026-10-01", 1, None)),
        # a SAM entity joins it through its DBA in tier 1: its DBA becomes the
        # trading name, its address the lookup, and its start date the oldest
        ("IL-0004", (["il_registry", "ppp", "sam"], "0004", "ROCKFORD TOOL LLC",
         "2 B ST", "sam", None, "238220", "ppp", 28, "sam_start", "likely_open",
         "il_registry good standing 2026-10-01", 1, None)),
        # SAM-only, with an active registration
        ("KEY-85701-TUCSON OPTICS", (["sam"], None, "TUCSON OPTICS LLC",
         "77 LENS WAY", "sam", None, "333314", "sam", 37, "sam_start",
         "likely_open", "sam registration active 2026-03-01", None, None)),
        # a SAM entity joins a PPP-only key, and its address replaces PPP's
        ("KEY-85201-MESA DRONE WORKS", (["ppp", "sam"], None, "MESA DRONE WORKS",
         "5 MAIN ST STE 200", "sam", None, "238220", "ppp", 25, "sam_start",
         "likely_open", "sam registration active 2025-11-01", None, None)),
        # one UEI's two registrations are one entity: they join the PPP key
        ("KEY-85364-YUMA FENCE", (["ppp", "sam"], None, "YUMA FENCE CO",
         "8 GATE RD", "sam", None, "238220", "ppp", 47, "sam_start",
         "likely_open", "sam registration active 2026-05-01", None, None)),
        # two UEIs with one key stay two businesses
        ("SAM-SAMTWIN00001", (["sam"], None, "TWIN PEAKS SURVEY", "1 PIKE ST",
         "sam", None, "541370", "sam", 27, "sam_start", "likely_open",
         "sam registration active 2026-01-15", None, None)),
        ("SAM-SAMTWIN00002", (["sam"], None, "TWIN PEAKS SURVEY", "9 PIKE ST",
         "sam", None, "541370", "sam", 11, "sam_start", "unknown", None, None,
         None)),
        # a sponsor filing from another state joins by EIN all the same
        ("EIN-751616161", (["dol_5500", "ppp", "tx_franchise"], "17516161616",
         "ROMEO CAFE INC", "12 MAIN PLZ", "ppp", "5555550100", "722110", "ppp", 46,
         "formed", "likely_open", "tx_franchise good standing 2026-10-10", 1,
         "ein")),
        # the latest filing is from abroad: the last US address stands
        ("EIN-380000006", (["dol_5500"], None, "LAKE ERIE SHIPPING CO",
         "1 DOCK ST", "dol_5500", "5555550100", "483113", "dol_5500", 41, "plan",
         "likely_open", "form 5500 received 2025-07-01", None, None)),
        ("EIN-360000005", (["dol_5500"], None, "ROCKFORD TOOL", "PO BOX 7",
         "dol_5500", "5555550100", "332911", "dol_5500", 61, "plan",
         "likely_open", "form 5500 received 2025-07-01", None, None)),
        # charged off in 2022, but the franchise row in good standing is newer
        ("EIN-748888888", (["ppp", "tx_franchise"], "17488888881",
         "KILO CONCRETE INC", "88 ROCK RD", "ppp", None, "238110", "ppp", 61,
         "formed", "likely_open", "tx_franchise good standing 2026-10-10", 1,
         None)),
    ],
)  # fmt: skip
def test_business_columns(
    built: Path, business_id: str, expected: tuple[object, ...]
) -> None:
    assert (
        row(
            built,
            business_id,
            "sources, registry_id, lookup_name, lookup_address, "
            "lookup_address_source, phone, naics, naics_source, years_in_business, "
            "age_source, open_status, open_evidence, match_tier, plan_link",
        )
        == expected
    )


def test_two_ppp_keys_of_one_taxpayer_are_one_business(built: Path) -> None:
    assert row(
        built,
        "EIN-745555555",
        "ppp_key_count, ppp_loan_count, ppp_total_approved::DOUBLE, ppp_names, "
        "match_tier, run_date",
    ) == (2, 2, 170000.0, ["MIKES MACHINE SHOP", "MIKES MACHINE SHOPS"], 1, DAY)


def test_industry_titles_and_placeholder_dates(built: Path) -> None:
    rows = duckdb.sql(
        f"""select business_id, sector, industry_group, naics_title,
                   plan_eff_date, oldest_evidence_date
            from '{businesses(built)}'
            where business_id in ('EIN-741111111', 'EIN-751616161', 'EIN-751414141')
            order by business_id"""
    ).fetchall()

    assert rows == [
        ("EIN-741111111", "Construction", "Building Equipment Contractors",
         "Plumbing, Heating, and Air-Conditioning Contractors", date(1990, 1, 1),
         date(1986, 10, 17)),
        # PAPA's plan "effective 1900-01-01" is a placeholder, so its charter dates it
        ("EIN-751414141", "Construction", "Building Equipment Contractors",
         "Plumbing, Heating, and Air-Conditioning Contractors", None,
         date(1990, 5, 5)),
        # 722110 left NAICS in 2012; its three-digit prefix still has a title
        ("EIN-751616161", "Accommodation and Food Services", None,
         "Food Services and Drinking Places", date(1990, 1, 1), date(1980, 2, 2)),
    ]  # fmt: skip


def test_a_sponsor_takes_its_latest_filing_and_its_earliest_plan(
    built: Path,
) -> None:
    assert row(
        built,
        "EIN-760000001",
        "plan_signer_name, phone, plan_name, plan_eff_date, ever_defined_benefit, "
        "plan_last_filed",
    ) == (
        "YVONNE YANKEE", "5555550100", "YANKEE TOOL 401(K) PLAN", date(1975, 1, 1),
        True, date(2025, 7, 1),
    )  # fmt: skip


def test_sba_columns(built: Path) -> None:
    assert row(
        built,
        "IL-0003",
        "sba_loan_count, sba_total_approved::DOUBLE, sba_first_loan_date, "
        "sba_first_business_age, sba_programs, sba_charged_off, match_tier",
    ) == (
        1, 100000.0, date(2015, 4, 1), "Existing, more than 2 years old", ["7A"],
        False, 1,
    )  # fmt: skip


def test_extras_pass_through_by_prefix(built: Path) -> None:
    assert row(
        built,
        "IL-0001",
        "registry_officers, il_county, tx_sos_file_number, tx_outlet_number",
    ) == (["PRESIDENT: SPRINGFIELD PLUMBING INC"], "Cook", None, None)
    assert row(built, "TX-32012345678", "tx_outlet_number, il_county") == ("1", None)


def rewrite(path: Path, query: str) -> None:
    duckdb.sql(f"copy ({query}) to '{path}.tmp' (format parquet)")
    Path(f"{path}.tmp").replace(path)


def test_qc_raises_on_a_duplicated_business_id(built: Path) -> None:
    path = businesses(built)
    rewrite(path, f"from '{path}' union all (from '{path}' limit 1)")

    with pytest.raises(AssertionError, match="1 repeated business_id values"):
        qc(built, min_rows=1, min_states=7, min_sba=1, min_sam=1, min_fmcsa=1)


def test_qc_raises_on_a_removed_ppp_key(built: Path) -> None:
    members = built / "marts" / "_work" / "members.parquet"
    rewrite(members, f"from '{members}' where rec_id != '76701|HOTEL INDIA SIGNS'")

    with pytest.raises(AssertionError, match="ppp has 33 memberships of 33 records"):
        qc(built, min_rows=1, min_states=7, min_sba=1, min_sam=1, min_fmcsa=1)


def test_qc_raises_on_a_removed_franchise_taxpayer(built: Path) -> None:
    members = built / "marts" / "_work" / "members.parquet"
    rewrite(members, f"from '{members}' where rec_id != '17520202020'")

    with pytest.raises(
        AssertionError, match="tx_franchise has 22 memberships of 22 records"
    ):
        qc(built, min_rows=1, min_states=7, min_sba=1, min_sam=1, min_fmcsa=1)


def test_qc_raises_on_a_removed_business(built: Path) -> None:
    path = businesses(built)
    rewrite(path, f"from '{path}' where business_id != 'EIN-752020202'")

    with pytest.raises(AssertionError, match="1 business_id values missing"):
        qc(built, min_rows=1, min_states=7, min_sba=1, min_sam=1, min_fmcsa=1)


def test_qc_raises_when_a_registry_state_matches_too_few_keys(built: Path) -> None:
    # 4 of IL's 4 non-individual keys matched
    with pytest.raises(AssertionError, match=r"IL matched 4 of 4 PPP keys"):
        qc(
            built,
            min_rows=1,
            min_states=7,
            min_sba=1,
            min_sam=1,
            min_fmcsa=1,
            match_floors={"IL": 1.01},
        )


def test_qc_raises_on_too_few_states(built: Path) -> None:
    with pytest.raises(AssertionError, match="9 states, expected >= 51"):
        qc(built, min_rows=1)


def test_fmcsa_carriers(built: Path) -> None:
    rows = duckdb.sql(
        f"""select business_id, sources, lookup_name, lookup_address,
                   lookup_address_source, phone, naics, naics_source, industry_group,
                   years_in_business, age_source, open_status, open_evidence,
                   usdot_number, fmcsa_status, fmcsa_officers
            from '{businesses(built)}' where list_contains(sources, 'fmcsa')
            order by business_id"""
    ).fetchall()
    assert rows == [
        # two carriers with one key stay apart under their USDOT numbers
        ("DOT-1000004", ["fmcsa"], "TWIN CITY CARTAGE", "1 HENNEPIN AVE", "fmcsa",
         "6125550100", "484", "fmcsa", None, 27, "fmcsa_added", "likely_open",
         "fmcsa carrier active 2026-01-10", 1000004, "A", None),
        ("DOT-1000005", ["fmcsa"], "TWIN CITY CARTAGE", "9 HENNEPIN AVE", "fmcsa",
         "6125550199", "484", "fmcsa", None, 11, "fmcsa_added", "likely_open",
         "fmcsa carrier active 2025-12-01", 1000005, "A", None),
        # joined through its DBA: industry from PPP, age from the add date,
        # address and phone from FMCSA
        ("EIN-754040404", ["fmcsa", "ppp", "tx_franchise"], "TANGO FREIGHT LLC",
         "6 DOCK RD STE B", "fmcsa", "7135550100", "484121", "ppp",
         "General Freight Trucking", 32,
         "fmcsa_added", "likely_open", "tx_franchise good standing 2026-10-10",
         1000001, "A", ["TOMAS ORTEGA"]),
        # its newest signal is the carrier's inactive status, after the loan;
        # the 1974-06-01 load date is no age, so the loan dates it
        ("KEY-74103-OLD MILL TRANSPORT", ["fmcsa", "ppp"], "OLD MILL TRANSPORT",
         "1 MILL RD", "fmcsa", "9185550100", "238220", "ppp",
         "Building Equipment Contractors", 6, "ppp_loan", "likely_closed",
         "fmcsa carrier inactive 2024-02-01", 1000003, "I", ["AL MILLER"]),
        # carrier-only and for hire: truck transportation
        ("KEY-87101-ROAD RUNNER HAULING", ["fmcsa"], "ROAD RUNNER HAULING",
         "40 MESA DR", "fmcsa", "5055550100", "484", "fmcsa", None, 25,
         "fmcsa_added",
         "likely_open", "fmcsa carrier active 2026-03-15", 1000002, "A",
         ["JANE DOE"]),
    ]  # fmt: skip
