import pytest

from include.pipeline.db import connect

CASES = [
    ("SUMTER COATINGS, INC.", "SUMTER COATINGS", None),
    ("Texas Instruments Incorporated", "TEXAS INSTRUMENTS", None),
    ("SOUTHWEST AIRLINES CO.", "SOUTHWEST AIRLINES", None),
    ("The Smith Co., L.L.C.", "SMITH", None),
    ("J & B ELECTRIC CO", "J AND B ELECTRIC", None),
    ("SMITH-JONES PLUMBING, LLC", "SMITH JONES PLUMBING", None),
    ("BOB'S A/C INC D/B/A COOL AIR", "BOBS AC", "COOL AIR"),
    ("COMPANY STORE INC", "COMPANY STORE", None),
    ("INC", None, None),
    ("", None, None),
    # beyond the spec's table: what the real SBA names showed
    ("PATRIOT PLACE &AMP; FINISH, LLC", "PATRIOT PLACE AND FINISH", None),
    ("GASTON&#39;S SALON &#8211; SPA", "GASTONS SALON SPA", None),
    (
        "DBA CHURCH FOUNDATION REPAIR",
        "CHURCH FOUNDATION REPAIR",
        "CHURCH FOUNDATION REPAIR",
    ),
    ("THE DBA RIVERSIDE GRILL", "RIVERSIDE GRILL", "RIVERSIDE GRILL"),
]


@pytest.mark.parametrize(("name", "norm", "dba"), CASES)
def test_name_macros(name: str, norm: str | None, dba: str | None) -> None:
    row = connect().execute("select norm_name($1), dba_name($1)", [name]).fetchall()

    assert row == [(norm, dba)]
