import re
from pathlib import Path

PIPELINE = Path(__file__).parents[2] / "include" / "pipeline"
CODES = (
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI "
    "WY PR GU VI MP AS"
).split()
QUOTED = re.compile(r"""['"](""" + "|".join(CODES) + r""")['"]""")


def test_only_state_modules_name_a_state() -> None:
    allowed = {PIPELINE / "naics_2017.csv"}
    offenders = [
        f"{path.relative_to(PIPELINE)}: {m.group(0)}"
        for path in sorted(PIPELINE.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path not in allowed
        and not (path.parent.name == "states" and path.name != "__init__.py")
        for m in QUOTED.finditer(path.read_text())
    ]

    assert offenders == [], f"{PIPELINE}: state codes outside states/: {offenders}"
