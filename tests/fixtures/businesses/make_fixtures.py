"""Tiny stage files for test_businesses.py: one case per line of specs 04 to 06.

Years are counted to 2026-10-17; both Comptroller files are dated 2026-10-10.
IL is a fixture registry with no EINs, written straight onto the states
contract; MO and OH have no registry. Norm names come from the real macros.
"""

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import duckdb

from include.pipeline import states
from include.pipeline.db import connect
from include.pipeline.states.texas import EIN

PPP = [
    # name, address, city, zip5, naics, business_type, nonprofit, loan_status,
    # loan_status_date, jobs, approved
    # tier 1, chartered exactly 40 years ago, defined-benefit plan, sponsor signer
    ("ACME PLUMBING INC", "1200 MAIN ST", "HOUSTON", "77002", "238220",
     "Corporation", False, "Paid in Full", None, 25, 300000.0),
    # tier 2: same name and city, registered under another ZIP
    ("BRAVO ELECTRIC LLC", "500 ELM ST", "DALLAS", "75201", "238210",
     "Limited  Liability Company(LLC)", False, "Paid in Full", None, 10, 90000.0),
    # tier 3: misspelled name at the registration's ZIP and street number
    ("CHARLIE ROOFNG CO", "900 PINE RD", "AUSTIN", "78701", "238160",
     "Corporation", False, "Paid in Full", None, 8, 70000.0),
    # PO boxes in one ZIP, each near-named to a taxpayer at another PO box
    ("ECHO WELDING", "PO BOX 11", "ODESSA", "79761", "332710",
     "Corporation", False, "Paid in Full", None, 4, 30000.0),
    ("FOXTROT WELDING", "PO BOX 33", "ODESSA", "79761", "332710",
     "Corporation", False, "Paid in Full", None, 5, 35000.0),
    # tier 4: the DBA is a sole proprietor's outlet, first sales 1985, no charter
    ("MARIA LOPEZ DBA LOPEZ TIRE SHOP", "301 E MAIN ST", "ALICE", "78332", "811111",
     "Sole Proprietorship", False, "Paid in Full", None, 3, 20833.0),
    # the name fits two taxpayers in one city: stays unmatched
    ("GULF COAST PAINTING", "10 BAY DR", "CORPUS CHRISTI", "78401", "238320",
     "Corporation", False, "Paid in Full", None, 6, 40000.0),
    # no registration at all: a PPP-only KEY- business, unknown
    ("HOTEL INDIA SIGNS", "44 SIGN ST", "WACO", "76701", "339950",
     "Corporation", False, "Paid in Full", None, 2, 15000.0),
    # nonprofit
    ("JULIET FOUNDATION REPAIR", "7 CHURCH ST", "TYLER", "75701", "238110",
     "Non-Profit Organization", True, "Paid in Full", None, 9, 60000.0),
    # charged off, but its franchise row is in good standing and newer
    ("KILO CONCRETE INC", "88 ROCK RD", "LUBBOCK", "79401", "238110",
     "Corporation", False, "Charged Off", date(2022, 3, 1), 11, 80000.0),
    # 10 years old
    ("LIMA LANDSCAPING LLC", "12 GREEN ST", "FRISCO", "75034", "561730",
     "Limited  Liability Company(LLC)", False, "Paid in Full", None, 7, 50000.0),
    # two name variants of one taxpayer: one business with two PPP keys
    ("MIKES MACHINE SHOP", "50 RIVER RD", "EL PASO", "79901", "332710",
     "Corporation", False, "Paid in Full", None, 12, 150000.0),
    ("MIKES MACHINE SHOPS", "50 RIVER RD", "EL PASO", "79901", "332710",
     "Corporation", False, "Paid in Full", None, 12, 20000.0),
    # chartered 2010, pension plan since 1985: dated by the plan
    ("NOVEMBER TRUCKING LLC", "300 HWY 59", "LUFKIN", "75901", "484121",
     "Limited  Liability Company(LLC)", False, "Paid in Full", None, 15, 120000.0),
    # turns 30 on 2026-10-17
    ("OSCAR GLASS INC", "5 CRYSTAL LN", "MIDLAND", "79701", "238150",
     "Corporation", False, "Paid in Full", None, 6, 45000.0),
    # a plan "effective 1900-01-01", the sources' placeholder: dated by charter
    ("PAPA HVAC INC", "9 COLD ST", "AMARILLO", "79101", "238220",
     "Corporation", False, "Paid in Full", None, 4, 25000.0),
    # tier 4 to a corporation's outlet with no active franchise row
    ("QUEBEC MACHINE WORKS INC", "77 FORGE RD", "BEAUMONT", "77701", "332710",
     "Corporation", False, "Paid in Full", None, 9, 55000.0),
    # outside the trades, with a code from an older NAICS edition (722110)
    ("ROMEO CAFE INC", "12 MAIN PLZ", "TEMPLE", "76501", "722110",
     "Corporation", False, "Paid in Full", None, 18, 95000.0),
    # a church whose loan was not flagged nonprofit
    ("SIERRA BAPTIST CHURCH", "400 CHAPEL RD", "WACO", "76706", "813110",
     "Non-Profit Organization", False, "Paid in Full", None, 6, 30000.0),
    # tier 5 only: no registration, a sponsor with the same name and ZIP
    ("BETA BOILER SERVICE", "3 STEAM ST", "HOUSTON", "77001", "238220",
     "Corporation", False, "Paid in Full", None, 7, 52000.0),
    # tier 1 to a franchise row, tier 5 to a lone sponsor: the hop
    ("DELTA DENTAL LAB INC", "20 TOOTH LN", "PLANO", "75023", "339116",
     "Corporation", False, "Paid in Full", None, 5, 41000.0),
    # a PPP-only business charged off: likely_closed
    ("UNIFORM BAKERY", "8 FLOUR ST", "BRYAN", "77801", "311811",
     "Sole Proprietorship", False, "Charged Off", date(2023, 6, 1), 2, 9000.0),
    # tier 1 to its franchise row, which an FMCSA carrier's DBA also fits
    ("TANGO FREIGHT LLC", "6 DOCK RD", "HOUSTON", "77029", "484121",
     "Limited  Liability Company(LLC)", False, "Paid in Full", None, 4, 30000.0),
]  # fmt: skip

FRANCHISE = [
    # taxpayer_number, name, address, city, zip5, org_type, charter_date,
    # right_to_transact, sos_status, sos_status_date
    ("17411111116", "ACME PLUMBING INC", "1200 MAIN ST", "HOUSTON", "77002", "CT",
     date(1986, 10, 17), "A", "A", None),
    ("17422222224", "BRAVO ELECTRIC LLC", "77 OAK AVE", "DALLAS", "75204", "CL",
     date(1980, 5, 1), "A", "A", None),
    ("17433333332", "CHARLIE ROOFING CO", "900 PINE ROAD", "AUSTIN", "78701", "CT",
     date(1975, 3, 1), "A", "A", None),
    ("32044444444", "ECHO WELDNG", "PO BOX 22", "ODESSA", "79761", "CT",
     date(1970, 1, 1), "A", "A", None),
    ("32055555555", "FOXTROT WELDNG", "PO BOX 44", "ODESSA", "79761", "CT",
     date(1971, 1, 1), "A", "A", None),
    ("17466666661", "GULF COAST PAINTING INC", "1 OCEAN DR", "CORPUS CHRISTI",
     "78404", "CT", date(1977, 1, 1), "A", "A", None),
    # its own EIN: the two taxpayers are two businesses
    ("17476666662", "GULF COAST PAINTING LLC", "2 SHORE DR", "CORPUS CHRISTI",
     "78411", "CL", date(1999, 1, 1), "A", "A", None),
    ("17477777771", "JULIET FOUNDATION REPAIR", "7 CHURCH ST", "TYLER", "75701", "CN",
     date(1970, 2, 2), "A", "A", None),
    ("17488888881", "KILO CONCRETE INC", "88 ROCK RD", "LUBBOCK", "79401", "CT",
     date(1965, 5, 5), "A", "A", None),
    ("17499999991", "LIMA LANDSCAPING LLC", "12 GREEN ST", "FRISCO", "75034", "CL",
     date(2016, 1, 1), "A", "A", None),
    ("17455555556", "MIKES MACHINE SHOP INC", "50 RIVER RD", "EL PASO", "79901", "CT",
     date(1979, 1, 1), "A", "A", None),
    ("17512121212", "NOVEMBER TRUCKING LLC", "300 HWY 59", "LUFKIN", "75901", "CL",
     date(2010, 6, 1), "A", "A", None),
    ("17513131313", "OSCAR GLASS INC", "5 CRYSTAL LN", "MIDLAND", "79701", "CT",
     date(1996, 10, 17), "A", "A", None),
    ("17514141414", "PAPA HVAC INC", "9 COLD ST", "AMARILLO", "79101", "CT",
     date(1990, 5, 5), "A", "A", None),
    ("17516161616", "ROMEO CAFE INC", "12 MAIN PLZ", "TEMPLE", "76501", "CT",
     date(1980, 2, 2), "A", "A", None),
    ("17517171717", "SIERRA BAPTIST CHURCH", "400 CHAPEL RD", "WACO", "76706",
     "CN", date(1950, 1, 1), "A", "A", None),
    # no other record, right to transact A: likely_open
    ("17520202020", "VICTOR VENDING INC", "1 COIN CT", "KILLEEN", "76541", "CT",
     date(1992, 4, 4), "A", "A", None),
    # forfeited, no other record: likely_closed on its status date
    ("17521212121", "WHISKEY WELL SERVICE INC", "2 DERRICK RD", "ODESSA", "79762",
     "CT", date(1981, 8, 8), "N", "F", date(2015, 3, 1)),
    # no EIN: its sponsor joins by name
    ("32088888888", "ZULU PAVING CO", "10 TAR RD", "KATY", "77449", "CT",
     date(2001, 1, 1), "A", "A", None),
    # carries an EIN its namesake sponsor does not share
    ("17530303030", "ALPHA DRILLING INC", "1 RIG RD", "MIDLAND", "79705", "CT",
     date(1999, 9, 9), "A", "A", None),
    # franchise tax not established yet (U), charter date a typo in the future:
    # no signal and no age
    ("17532323232", "GOLF START LLC", "3 TEE DR", "FRISCO", "75033", "CL",
     date(2027, 1, 6), "U", None, None),
    ("17531313131", "DELTA DENTAL LAB INC", "20 TOOTH LN", "PLANO", "75023", "CT",
     date(2005, 5, 5), "A", "A", None),
    ("17540404040", "TANGO FREIGHT LLC", "PO BOX 9", "HOUSTON", "77029", "CL",
     date(2012, 3, 1), "A", "A", None),
]  # fmt: skip

OUTLETS = [
    # taxpayer_number, org_type, outlet_number, outlet_name, outlet_address,
    # outlet_city, outlet_zip5, naics, first_sales_date
    ("32012345678", "S", "1", "LOPEZ TIRE SHOP", "301 E MAIN ST", "Alice", "78332",
     "811111", date(1985, 3, 1)),
    # later than ACME's charter, so ACME stays dated by its charter
    ("17411111116", "CT", "2", "ACME PLUMBING", "1200 MAIN ST", "Houston", "77002",
     "238220", date(1990, 1, 1)),
    ("17411111116", "CT", "10", "ACME PLUMBING NORTH", "9 NORTH RD", "Houston",
     "77003", "238220", date(1995, 1, 1)),
    ("17515151515", "CT", "1", "QUEBEC MACHINE WORKS INC", "77 FORGE RD",
     "Beaumont", "77701", "332710", date(1970, 1, 1)),
    # an outlet-only sole proprietor with no PPP loan
    ("32077777777", "S", "1", "XRAY SHOE REPAIR", "5 HEEL ST", "Alvin", "77511",
     "811430", date(1988, 4, 1)),
]  # fmt: skip

DOL = [
    # ein, sponsor_name, sponsor_dba_name, address, city, zip5,
    # earliest_plan_eff_date, signer_name, signer_source, plan_name,
    # pension_codes, ever_defined_benefit, business_code
    ("741111111", "ACME PLUMBING INC", None, "PO BOX 1", "HOUSTON", "77002",
     date(1990, 1, 1), "JOHN ACME", "sponsor", "ACME PLUMBING PENSION PLAN", "1A",
     True, "238220"),
    ("751212121", "NOVEMBER TRUCKING LLC", None, "300 HWY 59", "LUFKIN", "75901",
     date(1985, 1, 1), "NORA NOVEMBER", "admin_is_sponsor",
     "NOVEMBER TRUCKING 401(K) PLAN", "2E2J", False, "484120"),
    ("751414141", "PAPA HVAC INC", None, "9 COLD ST", "AMARILLO", "79101",
     date(1900, 1, 1), None, None, "PAPA HVAC PROFIT SHARING PLAN", "2E", False,
     "238220"),
    # sponsor-only business
    ("760000001", "YANKEE TOOL AND DIE INC", "YANKEE TOOLS", "40 LATHE ST",
     "PASADENA", "77506", date(1979, 1, 1), "YVONNE YANKEE", "sponsor",
     "YANKEE TOOL 401(K) PLAN", "2E", False, "333514"),
    # joins ZULU PAVING CO by name: the franchise row has no EIN
    ("760000002", "ZULU PAVING COMPANY", None, "10 TAR RD", "KATY", "77449",
     date(1985, 6, 1), "ZED ZULU", "sponsor", "ZULU PAVING PROFIT SHARING PLAN",
     "2E", False, "237310"),
    # same name as ALPHA DRILLING INC, whose EIN differs: its own business
    ("760000003", "ALPHA DRILLING INC", None, "1 RIG RD", "MIDLAND", "79705",
     date(2003, 1, 1), None, None, "ALPHA DRILLING 401(K) PLAN", "2E", False,
     "213111"),
    # BETA BOILER SERVICE joins it in tier 5
    ("760000004", "BETA BOILER SERVICE INC", None, "3 STEAM ST", "HOUSTON", "77001",
     date(1994, 2, 1), "BOB BETA", "sponsor", "BETA BOILER 401(K) PLAN", "2E",
     False, "238220"),
    # alone after step 2; its one tier-5 PPP key is in DELTA's business
    ("760000005", "DELTA DENTAL LAB", None, "20 TOOTH LN", "PLANO", "75023",
     date(2008, 3, 1), "DORA DELTA", "sponsor", "DELTA DENTAL LAB PLAN", "2E",
     False, "339116"),
]  # fmt: skip

# outside Texas: name, address, city, state, zip5, business_type
PPP_OTHER = [
    # tier 2 to its IL registry business, which sits in another ZIP of the city
    ("SPRINGFIELD PLUMBING INC", "40 OAK ST", "SPRINGFIELD", "IL", "62704",
     "Corporation"),
    # the same name in Springfield, Missouri, with no registry: a KEY- business
    ("SPRINGFIELD PLUMBING INC", "9 ELM ST", "SPRINGFIELD", "MO", "65801",
     "Corporation"),
    # tier 5 to an Ohio sponsor
    ("OHIO VALVE CO", "12 MARKET ST", "AKRON", "OH", "44301", "Corporation"),
    # tier 6: the sponsor files from another ZIP of the same city
    ("CLEVELAND CRANE SERVICE", "800 LAKE AVE", "CLEVELAND", "OH", "44114",
     "Corporation"),
    # tier 7: the sponsor misspells the name at the same ZIP and street number
    ("COLUMBUS CABINETRY", "100 N HIGH ST", "COLUMBUS", "OH", "43215",
     "Corporation"),
    # tier 3 to an IL registry row, tier 5 to a lone sponsor: the hop
    ("PEORIA PRINTING", "100 MAIN ST", "PEORIA", "IL", "61602", "Corporation"),
    # two IL namesakes, each with its own key; both keys fit one sponsor in
    # tier 6, so the hop does not fire
    ("ROCKFORD TOOL", "1 A ST", "ROCKFORD", "IL", "61101", "Corporation"),
    ("ROCKFORD TOOL", "2 B ST", "ROCKFORD", "IL", "61102", "Corporation"),
    # PPP-only until a SAM entity with its key joins it
    ("MESA DRONE WORKS", "5 MAIN ST", "MESA", "AZ", "85201", "Corporation"),
    # one SAM UEI with two registrations shares this key
    ("YUMA FENCE CO", "8 GATE RD", "YUMA", "AZ", "85364", "Corporation"),
    # an inactive FMCSA carrier with this key closed after the loan
    ("OLD MILL TRANSPORT", "1 MILL RD", "TULSA", "OK", "74103", "Corporation"),
]  # fmt: skip

IL_REGISTRY = [
    # registry_id, name, address, city, zip5, formed_date
    ("0001", "SPRINGFIELD PLUMBING INC", "1 CAPITOL AVE", "SPRINGFIELD", "62701",
     date(1955, 6, 1)),
    ("0002", "PEORIA PRINTNG CO", "100 MAIN ST", "PEORIA", "61602",
     date(1971, 2, 1)),
    ("0003", "ROCKFORD TOOL INC", "1 A ST", "ROCKFORD", "61101", date(1960, 1, 1)),
    ("0004", "ROCKFORD TOOL LLC", "2 B ST", "ROCKFORD", "61102", date(2001, 1, 1)),
]  # fmt: skip

DOL_OTHER = [
    # ein, sponsor_name, address, city, state, zip5, earliest_plan_eff_date
    ("310000001", "OHIO VALVE COMPANY", "12 MARKET ST", "AKRON", "OH", "44301",
     date(1980, 1, 1)),
    ("340000002", "CLEVELAND CRANE SERVICE INC", "PO BOX 9", "CLEVELAND", "OH",
     "44103", date(1990, 1, 1)),
    ("310000003", "COLUMBUS CABINTRY LLC", "100 N HIGH ST", "COLUMBUS", "OH",
     "43215", date(1999, 1, 1)),
    ("370000004", "PEORIA PRINTING", "PO BOX 5", "PEORIA", "IL", "61602",
     date(1975, 1, 1)),
    ("360000005", "ROCKFORD TOOL", "PO BOX 7", "ROCKFORD", "IL", "61103",
     date(1965, 1, 1)),
    # ROMEO CAFE INC's EIN, filing from Oklahoma: joined by EIN all the same
    ("751616161", "ROMEO CAFE INC", "5 RIVER RD", "TULSA", "OK", "74103",
     date(1990, 1, 1)),
]  # fmt: skip

SBA = [
    # name, address, city, state, zip5, approval_date, naics, business_age,
    # loan_status, charge_off_date
    # the Missouri PPP key's 1990 loan: one KEY- business, dated by SBA
    ("SPRINGFIELD PLUMBING INC", "9 ELM ST", "SPRINGFIELD", "MO", "65801",
     date(1990, 10, 15), "238220", "Existing, more than 2 years old", "P I F",
     None),
    # SBA-only, charged off in 2009
    ("TULSA TIRE CO", "7 RIM RD", "TULSA", "OK", "74103", date(2005, 3, 1),
     "441320", "New, Less than 1 Year old", "CHGOFF", date(2009, 6, 1)),
    # the IL PPP key's name and ZIP, but an old address in another city: no
    # tier fits it, so it follows the PPP key into IL-0001
    ("SPRINGFIELD PLUMBING INC", "3 OLD RD", "CHATHAM", "IL", "62704",
     date(1985, 2, 1), "238220", "Existing, more than 2 years old", "P I F",
     None),
    # tier 1 to an IL registry business
    ("ROCKFORD TOOL INC", "1 A ST", "ROCKFORD", "IL", "61101", date(2015, 4, 1),
     "333514", "Existing, more than 2 years old", "P I F", None),
]  # fmt: skip

SAM = [
    # uei, eft, legal_name, dba_name, address_1, city, state, zip5, country,
    # start_date, status, activation_date, naics
    # SAM-only: its own KEY- business, open, with SAM's address
    ("SAMONLY00001", None, "TUCSON OPTICS LLC", None, "77 LENS WAY", "TUCSON",
     "AZ", "85701", "USA", date(1989, 4, 1), "A", date(2026, 3, 1), "333314"),
    # the PPP key's name and ZIP: joins it, and its address is the lookup
    ("SAMMESA00001", None, "MESA DRONE WORKS", None, "5 MAIN ST STE 200", "MESA",
     "AZ", "85201", "USA", date(2001, 6, 1), "A", date(2025, 11, 1), "336411"),
    # two UEIs with one key: two SAM- businesses
    ("SAMTWIN00001", None, "TWIN PEAKS SURVEY", None, "1 PIKE ST", "SEATTLE",
     "WA", "98101", "USA", date(1999, 1, 1), "A", date(2026, 1, 15), "541370"),
    ("SAMTWIN00002", None, "TWIN PEAKS SURVEY", None, "9 PIKE ST", "SEATTLE",
     "WA", "98101", "USA", date(2015, 1, 1), "E", date(2023, 1, 15), "541370"),
    # the legal name fits nothing; the DBA fits IL-0004 in tier 1
    ("SAMDBA000001", "0001", "R T HOLDINGS INC", "ROCKFORD TOOL LLC", "2 B ST",
     "ROCKFORD", "IL", "61102", "USA", date(1998, 1, 1), "A", date(2026, 2, 1),
     "333514"),
    # one UEI, two registrations, one key: one entity, so it joins the PPP key
    ("SAMYUMA00001", "0001", "YUMA FENCE CO", None, "8 GATE RD", "YUMA", "AZ",
     "85364", "USA", date(1979, 3, 1), "A", date(2026, 4, 1), "238990"),
    ("SAMYUMA00001", "0002", "YUMA FENCE CO", None, "8 GATE RD", "YUMA", "AZ",
     "85364", "USA", date(1979, 3, 1), "A", date(2026, 5, 1), "238990"),
    # outside the US: staged, not merged
    ("SAMABROAD001", None, "MAPLE OPTICS LTD", None, "1 KING ST", "TORONTO",
     None, None, "CAN", date(1980, 1, 1), "A", date(2026, 1, 1), "333314"),
]  # fmt: skip

FMCSA = [
    # dot_number, legal_name, dba_name, phy_street, phy_city, phy_state, zip5,
    # phy_country, status_code, add_date, mcs150_date, company_officer_1,
    # classdef, phone
    # the legal name is the owner's; the DBA fits TANGO FREIGHT LLC's franchise
    # row in tier 1, so the carrier dates it and gives its address and phone
    (1000001, "TOMAS ORTEGA", "TANGO FREIGHT LLC", "6 DOCK RD STE B", "HOUSTON",
     "TX", "77029", "US", "A", date(1994, 5, 2), date(2026, 4, 1), "TOMAS ORTEGA",
     "AUTHORIZED FOR HIRE", "7135550100"),
    # carrier-only, for hire: a KEY- business in truck transportation
    (1000002, "ROAD RUNNER HAULING", None, "40 MESA DR", "ALBUQUERQUE", "NM",
     "87101", "US", "A", date(2001, 7, 1), date(2026, 3, 15), "JANE DOE",
     "AUTHORIZED FOR HIRE", "5055550100"),
    # inactive since 2024, after its 2020 PPP loan: likely_closed; added on
    # the census's 1974-06-01 load date, which is no age
    (1000003, "OLD MILL TRANSPORT", None, "1 MILL RD", "TULSA", "OK", "74103",
     "US", "I", date(1974, 6, 1), date(2024, 2, 1), "AL MILLER",
     "PRIVATE PROPERTY", "9185550100"),
    # two carriers with one key: two DOT- businesses
    (1000004, "TWIN CITY CARTAGE", None, "1 HENNEPIN AVE", "MINNEAPOLIS", "MN",
     "55401", "US", "A", date(1999, 9, 9), date(2026, 1, 10), None,
     "AUTHORIZED FOR HIRE", "6125550100"),
    (1000005, "TWIN CITY CARTAGE", None, "9 HENNEPIN AVE", "MINNEAPOLIS", "MN",
     "55401", "US", "A", date(2015, 5, 5), date(2025, 12, 1), None,
     "AUTHORIZED FOR HIRE", "6125550199"),
    # outside the US, or in the US without a state: staged, not merged
    (1000006, "TRANSPORTES DEL NORTE", None, "1 AV JUAREZ", "MONTERREY", "NL",
     None, "MX", "A", date(1990, 1, 1), date(2026, 1, 1), None,
     "AUTHORIZED FOR HIRE", "5281555010"),
    (1000007, "TEST SHUTTLE LLC", None, "1 TEST AVE", "DC", None, "20007", "US",
     "I", date(2020, 1, 1), date(2020, 1, 1), None, "PRIVATE PROPERTY", None),
]  # fmt: skip

# The fixture registry, as a state module would declare it.
IL_SOURCE = states.Source(
    name="il_registry",
    state="IL",
    kind="registry",
    files=(),
    select="",
    min_rows=1,
    dropped=(0, 0),
    sentinel=None,
)


# The sources these stage files stand for; build and qc read only these.
SOURCES = {
    **{n: states.SOURCES[n] for n in ("tx_franchise", "tx_sales_outlets")},
    "il_registry": IL_SOURCE,
}


def write(
    con: duckdb.DuckDBPyConnection,
    dest: Path,
    columns: str,
    rows: Sequence[tuple[object, ...]],
    derived: str,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"create or replace temp table t ({columns})")
    con.executemany(f"insert into t values ({', '.join('?' * len(rows[0]))})", rows)
    con.execute(f"copy (select {derived} from t) to '{dest}' (format parquet)")


PPP_COLUMNS = (
    "borrower_name VARCHAR, address VARCHAR, city VARCHAR, state VARCHAR, "
    "zip5 VARCHAR, naics VARCHAR, business_type VARCHAR, nonprofit BOOLEAN, "
    "loan_status VARCHAR, loan_status_date DATE, jobs_reported INTEGER, "
    "current_approval_amount DOUBLE"
)
FILING_COLUMNS = (
    "ein VARCHAR, sponsor_name VARCHAR, sponsor_dba_name VARCHAR, "
    "address VARCHAR, city VARCHAR, state VARCHAR, zip5 VARCHAR, "
    "plan_eff_date DATE, signer_name VARCHAR, signer_source VARCHAR, "
    "plan_name VARCHAR, pension_codes VARCHAR, is_defined_benefit BOOLEAN, "
    "business_code VARCHAR, date_received DATE, phone VARCHAR"
)


def write_stage(data: Path) -> None:
    stage = data / "stage"
    con = connect()
    ppp = [(*r[:3], "TX", *r[3:]) for r in PPP] + [
        (name, address, city, state, zip5, "238220", kind, False, "Paid in Full",
         None, 5, 50000.0)
        for name, address, city, state, zip5, kind in PPP_OTHER
    ]  # fmt: skip
    write(
        con,
        stage / "ppp.parquet",
        PPP_COLUMNS,
        ppp,
        "*, norm_name(borrower_name) as norm_name, "
        "dba_name(borrower_name) as dba_norm_name, "
        "'Existing or more than 2 years old' as business_age_description, "
        "date '2020-05-01' as date_approved, row_number() over () as loan_number",
    )
    write(
        con,
        states.stage_path(states.SOURCES["tx_franchise"], data),
        "taxpayer_number VARCHAR, taxpayer_name VARCHAR, address VARCHAR, "
        "city VARCHAR, zip5 VARCHAR, org_type VARCHAR, charter_date DATE, "
        "right_to_transact VARCHAR, sos_status VARCHAR, sos_status_date DATE",
        FRANCHISE,
        f"""'TX' as state, taxpayer_number as registry_id, {EIN} as ein,
            taxpayer_name as name, norm_name(taxpayer_name) as norm_name, address,
            city, 'TX' as address_state, zip5, 'mailing' as address_kind,
            org_type as entity_type, sos_status as status,
            sos_status_date as status_date,
            case when right_to_transact = 'A' then true
                 when right_to_transact is distinct from 'U' then false
            end as active,
            charter_date as formed_date, null::VARCHAR as naics,
            null::VARCHAR[] as officers, '0800000000' as tx_sos_file_number,
            right_to_transact as tx_right_to_transact,
            sos_status_date as tx_sos_status_date, date '2026-10-10' as as_of""",
    )
    write(
        con,
        states.stage_path(IL_SOURCE, data),
        "registry_id VARCHAR, name VARCHAR, address VARCHAR, city VARCHAR, "
        "zip5 VARCHAR, formed_date DATE",
        IL_REGISTRY,
        """'IL' as state, registry_id, null::VARCHAR as ein, name,
           norm_name(name) as norm_name, address, city,
           null::VARCHAR as address_state, zip5, 'physical' as address_kind,
           'CORP' as entity_type, 'Active' as status, null::DATE as status_date,
           true as active, formed_date, null::VARCHAR as naics,
           ['PRESIDENT: ' || name] as officers, 'Cook' as il_county,
           date '2026-10-01' as as_of""",
    )
    write(
        con,
        states.stage_path(states.SOURCES["tx_sales_outlets"], data),
        "taxpayer_number VARCHAR, org_type VARCHAR, outlet_number VARCHAR, "
        "outlet_name VARCHAR, outlet_address VARCHAR, outlet_city VARCHAR, "
        "outlet_zip5 VARCHAR, outlet_naics VARCHAR, first_sales_date DATE",
        OUTLETS,
        f"""'TX' as state, taxpayer_number as registry_id, {EIN} as ein,
            org_type as entity_type, outlet_name as dba_name,
            norm_name(outlet_name) as norm_dba_name, outlet_address as address,
            upper(outlet_city) as city, outlet_zip5 as zip5,
            first_sales_date as first_seen_date, true as active,
            outlet_naics as naics, outlet_number as tx_outlet_number,
            'TAXPAYER ' || taxpayer_number as tx_taxpayer_name,
            date '2026-10-10' as as_of""",
    )
    write(
        con,
        stage / "sba_loans.parquet",
        "borrower_name VARCHAR, address VARCHAR, city VARCHAR, state VARCHAR, "
        "zip5 VARCHAR, approval_date DATE, naics VARCHAR, business_age VARCHAR, "
        "loan_status VARCHAR, charge_off_date DATE",
        SBA,
        """'7A' as program, borrower_name, norm_name(borrower_name) as norm_name,
           dba_name(borrower_name) as dba_norm_name, address, city, state, zip5,
           approval_date, year(approval_date) as approval_fy,
           100000.00::DECIMAL(18, 2) as gross_approval, naics,
           'CORPORATION' as business_type, business_age, loan_status,
           null::DATE as paid_in_full_date, charge_off_date, 5 as jobs_supported,
           null::VARCHAR as franchise_name, 'TEST BANK' as lender_name,
           'FOIA_7a_test.csv' as source_file""",
    )
    write(
        con,
        stage / "sam_entities.parquet",
        "uei VARCHAR, eft_indicator VARCHAR, legal_name VARCHAR, dba_name VARCHAR, "
        "address_1 VARCHAR, city VARCHAR, state VARCHAR, zip5 VARCHAR, "
        "country VARCHAR, start_date DATE, registration_status VARCHAR, "
        "activation_date DATE, primary_naics VARCHAR",
        SAM,
        """uei, eft_indicator, 'CAGE1' as cage, registration_status,
           activation_date, activation_date + interval 1 year as expiration_date,
           legal_name, norm_name(legal_name) as norm_name, dba_name,
           norm_name(dba_name) as norm_dba_name, address_1,
           null::VARCHAR as address_2, city, state, zip5, country, start_date,
           '2L' as entity_structure, primary_naics, primary_naics as naics_list,
           'GINA' as gov_poc_first_name, 'GOV' as gov_poc_last_name,
           null::VARCHAR as elec_poc_first_name,
           null::VARCHAR as elec_poc_last_name""",
    )
    write(
        con,
        stage / "fmcsa_carriers.parquet",
        "dot_number BIGINT, legal_name VARCHAR, dba_name VARCHAR, "
        "phy_street VARCHAR, phy_city VARCHAR, phy_state VARCHAR, zip5 VARCHAR, "
        "phy_country VARCHAR, status_code VARCHAR, add_date DATE, "
        "mcs150_date DATE, company_officer_1 VARCHAR, classdef VARCHAR, "
        "phone VARCHAR",
        FMCSA,
        """dot_number, legal_name, norm_name(legal_name) as norm_name, dba_name,
           norm_name(dba_name) as norm_dba_name, phy_street, phy_city, phy_state,
           zip5, phy_country, status_code, add_date, mcs150_date,
           company_officer_1, null::VARCHAR as company_officer_2,
           'INDIVIDUAL' as business_org_desc, 'A' as carrier_operation, classdef,
           1 as power_units, 1 as truck_units, 1 as total_drivers, phone,
           null::VARCHAR as email_address, date '2026-10-16' as as_of""",
    )
    filings = [
        (ein, name, dba, address, city, "TX", zip5, eff, signer, source, plan,
         codes, db, code, date(2025, 7, 1), "5555550100")
        for ein, name, dba, address, city, zip5, eff, signer, source, plan, codes,
        db, code in DOL
    ] + [
        (ein, name, None, address, city, state, zip5, eff, None, None,
         f"{name} 401(K) PLAN", "2E", False, "332911", date(2025, 7, 1),
         "5555550100")
        for ein, name, address, city, state, zip5, eff in DOL_OTHER
    ] + [
        # an older filing of YANKEE: an older plan, another signer and phone
        ("760000001", "YANKEE TOOL AND DIE INC", "YANKEE TOOLS", "40 LATHE ST",
         "PASADENA", "TX", "77506", date(1975, 1, 1), "OLD YANKEE", "sponsor",
         "YANKEE TOOL PENSION PLAN", "1A", True, "333514", date(2019, 7, 1),
         "5555550199"),
        # the latest filing comes from abroad; the address is the last US one
        ("380000006", "LAKE ERIE SHIPPING CO", None, "1 DOCK ST", "CLEVELAND",
         "OH", "44101", date(1985, 1, 1), None, None, "LAKE ERIE PLAN", "2E",
         False, "483113", date(2019, 7, 1), "5555550100"),
        ("380000006", "LAKE ERIE SHIPPING CO", None, None, None, None, None,
         date(1985, 1, 1), "LEE ERIE", "sponsor", "LAKE ERIE PLAN", "2E", False,
         "483113", date(2025, 7, 1), "5555550100"),
        # only ever filed from abroad: not a US business
        ("980000007", "MAPLE HARBOUR LTD", None, None, None, None, None,
         date(1990, 1, 1), None, None, "MAPLE HARBOUR PLAN", "2E", False,
         "483113", date(2025, 7, 1), "5555550100"),
    ]  # fmt: skip
    write(
        con,
        stage / "dol_5500_filings.parquet",
        FILING_COLUMNS,
        filings,
        """'ACK' || ein || date_received as ack_id, *,
           norm_name(sponsor_name) as norm_name, plan_eff_date as plan_year_begin,
           10 as participants, 10 as active_participants, '5500' as form,
           year(date_received) - 1 as form_year""",
    )
