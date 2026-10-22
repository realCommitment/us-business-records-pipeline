# 09-sam-start-dates

Stages the SAM.gov monthly public entity extract, the federal registrations of contractors and grantees. Each entity joins the business it belongs to, or becomes a business of its own, bringing a NAICS code, a self-reported start date, a physical address and points of contact.

Bound by `docs/specs/00-product/spec.md`: decisions 4 to 9, 11, 12 and 16 to 20, and `docs/data-sources.md` section 8. It follows `national/sba.py`'s shape.

## Goal

The DAG gains a SAM chain:

1. **List** the public V2 extract files. No API key is needed.
2. **Download** the newest monthly UTF-8 file, but only when its dated name is not already on disk.
3. **Stage** every record into `stage/sam_entities.parquet`.

On 2026-10-05 there were 905,712 records, 868,763 of them in the US. 868,161 US records have an entity start date. 247,395 US entities started in 1996 or earlier, and 235,277 of those are active.

**In the transform**, each entity is a record in product decision 9:

- Step 3: it joins through its legal name, or failing that its DBA name, with the same tiers as PPP keys.
- Step 4: it joins the leftover group with its `(norm_name, zip5)`.
- Two UEIs that share a key stay separate rows, `SAM-<uei>`.

**What it adds, by column group:**

- **Industry:** its primary NAICS, third in decision 18's order.
- **Years:** its start date, the `sam_start` candidate.
- **Lookup:** its physical address, second in decision 20's order, and its DBA as a trading name.
- **Open status:** an active registration is an activity signal, dated by its activation date.
- **Columns:** `sam_uei`, `sam_cage`, `sam_start_date`, `sam_registration_status`, `sam_expiration_date`, `sam_entity_structure`, `sam_poc_names`.

## What the user can do afterwards

```
scripts/smoke.sh 7200
uv run python -c "import duckdb; print(duckdb.sql(\"select state, count(*) filter (where list_contains(sources, 'sam')) with_sam, count(*) filter (where sources = ['sam']) sam_only, count(*) filter (where age_source = 'sam_start') dated_by_sam, count(*) filter (where lookup_address_source = 'sam') address_from_sam from 'include/data/marts/businesses.parquet' group by 1 order by 2 desc limit 15\"))"
```

## Anti-goals

- No `api.sam.gov` key and no account. The keyless endpoint the sam.gov website uses was verified on 2026-10-17. If it ever needs a key, the task fails and a new spec decides.
- No daily SAM files, which are FOUO and restricted, and no older months. Raw keeps every month it has downloaded, but the stage reads only the newest.
- No exclusion of government, nonprofit or large entities. `sam_entity_structure` and the industry let a consumer filter them out.

## Files and interfaces

- **`include/pipeline/zips.py`.** SAM is the second user of zip extraction, so move `extract` from `national/dol.py` to plumbing, with a `suffix` argument: `.csv` for DOL, `.zip` and then `.dat` for SAM. DOL imports it from there, with unchanged behavior and tests.
- **`include/pipeline/national/sam.py`**
  - `LIST = "https://sam.gov/api/prod/fileextractservices/v1/api/listfiles?domain=Entity%20Registration/Public%20V2&privacy=Public"`. The response is JSON with `_embedded.customS3ObjectSummaryList[].displayKey`.
  - `DOWNLOAD = "https://sam.gov/api/prod/fileextractservices/v1/api/download/Entity%20Registration/Public%20V2/{name}?privacy=Public"`. It answers 303 with a signed S3 link that expires after 45 minutes and rejects HEAD (verified).
  - `discover() -> str` returns the newest `SAM_PUBLIC_UTF-8_MONTHLY_V2_YYYYMMDD.ZIP`, by the date in the name. It raises when the listing has none.
  - `download(name: str, data: Path = DATA) -> bool` has its own change rule, because HEAD cannot be used:
    - If `raw/sam/<name>` exists and its `.meta.json` records the same byte count, log `unchanged <name>` and return `False`. The name is dated, so a new month is a new name.
    - Otherwise stream the GET, following the 303, to `.part`, then `os.replace` it and write the sidecar.
  - `stage(name: str, data: Path = DATA, min_rows: int = <calibrated>) -> int`
    - Extract the inner zip, then the `.dat` member, beside the outer zip, with `zips.extract`.
    - The file is pipe-delimited with no header row. Its first line is `BOF PUBLIC V2 00000000 <date> <record count> <sequence>`, its last line starts with `EOF`, and every record has 142 fields.
    - Pin the field positions from GSA's published "SAM Public V2 extract" layout and record the source in the notes. Field 25 is the entity start date, `YYYYMMDD` (verified).
    - Stage every record with:
      - UEI, CAGE code, registration status, activation and expiration dates
      - legal business name and `norm_name`; DBA name and `norm_dba_name`
      - physical address 1 and 2, city (uppercased), state, `zip5`, country
      - entity start date, typed strictly
      - entity structure, primary NAICS, NAICS list
      - government business POC first and last name; electronic business POC first and last name
    - **Record-count check:** the staged count must equal the count in the `BOF` line. This catches truncation exactly.
    - Assert the floor and a sentinel: one well-known UEI with its start date, chosen from the real file and recorded.
- **`sql/businesses.sql`**
  - `sam` records are US entities, keyed by `(norm_name, zip5)`, with `norm_dba_name` as a second name for tiers 1 to 4 and for the trading name.
  - They enter steps 3 and 4 next to PPP and SBA records. In step 4, a key held by two or more SAM records leaves those records out of the group, and each becomes `SAM-<uei>`.
  - `sources` gains `sam`. Industry, years, lookup, open status and `names` gain SAM as in the goal. When two SAM records join one business, take the earliest start date and the latest activation.
- **`qc`:** conservation counts every US SAM record. It also checks at least a calibrated floor of businesses with `sam` in `sources`.
- **DAG:** `sam_discover`, then `sam_download`, then `sam_stage(name)`. Add it to the stages `build` waits on.
- **Tests:**
  - `tests/fixtures/national/sam/` holds a tiny outer zip with an inner zip and a `.dat` file. It has a real `BOF` line, five real records copied from the file (the sentinel among them) and an `EOF` line.
  - The listing JSON is trimmed from the real one.
  - `tests/unit/national/test_sam.py` checks that:
    - `discover` picks the newest UTF-8 monthly name
    - `stage` types the records
    - a fixture whose `BOF` count disagrees raises
  - The businesses fixtures gain:
    - a SAM-only business with a start date and a physical address: it becomes `KEY-…`, is `likely_open` and uses the SAM address
    - a SAM entity that joins a PPP-only business by key, where SAM's physical address replaces the PPP address in the lookup
    - two UEIs sharing a key, which become two `SAM-` rows

## End-to-end verification

1. Run `scripts/smoke.sh 7200` and paste its output. The first run downloads about 150 MB.
2. Paste the query above, and the national totals of businesses gaining a SAM start date 30 or more years old and a SAM lookup address.
3. Spot-check two businesses dated by `sam_start` against `https://sam.gov/entity/<UEI>/coreData`. Paste what the page shows for the start date, or record that the page needs JavaScript and check against the raw `.dat` line instead.
4. A second run logs `unchanged <name>` and the file's `sha256sum` is identical.
5. `mise run check` passes.
