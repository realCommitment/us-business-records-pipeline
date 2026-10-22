# 10-registry-florida

Adds Florida's corporate registry from the Division of Corporations' free quarterly bulk file. That gives Florida businesses formation dates, statuses, up to six officers and published EINs.

Bound by `docs/specs/00-product/spec.md`: decisions 4 to 6, 9 to 13, 15 and 17. Also bound by `docs/data-sources.md` section 10.1. It uses spec 06's `states/` contract with Florida's own `download` and `read`.

## Goal

`states/florida.py` downloads `cordata.zip`, Florida's quarterly full corporate file, over SFTP, only when its size or modification time changed. It extracts the zip with `unzip`, because the archive uses Deflate64, which Python's `zipfile` cannot read. It then stages every record of the fixed-width members into `stage/registry/fl_corporations.parquet`.

- On 2026-10-07 the file was 1,793,034,019 bytes, holding about 13 million 1,440-byte records, roughly 18 GB unzipped. They cover active and inactive entities since the 1970s.
- Every record becomes a registry business (product decision 9, step 1). Inactive ones are `likely_closed` unless newer activity says otherwise, so Florida adds the most rows of any state, most of them closed.
- Florida has 983,321 PPP loans, the second most of any state. Its records carry the federal EIN (the FEI number).
- Florida's PPP keys, SBA borrowers and SAM entities join these businesses through tiers 1 to 4. Its plan sponsors join by exact EIN in step 2.

## What the user can do afterwards

```
scripts/smoke.sh 14400
uv run python -c "import duckdb; print(duckdb.sql(\"select open_status, count(*) businesses, count(*) filter (where list_contains(sources, 'ppp')) with_ppp, count(ein) with_ein, count(plan_eff_date) with_plan, count(registry_officers) with_officers, count(*) filter (where years_in_business >= 30) old from 'include/data/marts/businesses.parquet' where state = 'FL' group by 1\"))"
uv run python -c "import duckdb; print(duckdb.sql(\"select registry_id, name, ein, formed_date, status, officers from 'include/data/stage/registry/fl_corporations.parquet' where registry_id = '444750'\"))"
```

The second command prints RAYMOND JAMES FINANCIAL, INC. with EIN 591517485, formed 1974-01-24.

## Anti-goals

- No daily delta files (`/Public/doc/cor/YYYYMMDDc.txt`). The quarterly full file is the source, so Florida data can be up to three months old; `as_of` records the date.
- No fictitious-name (DBA), lien or partnership files from the same server. They are a later spec if wanted.
- No new Python dependency for SFTP or Deflate64. The container's `curl` speaks SFTP (libssh2, verified on 2026-10-17), and `unzip` comes from `packages.txt`.
- No status filter: inactive (`I`) records are staged and matched like any other.

## Files and interfaces

- **`packages.txt`:** add `unzip`. Rebuild with `astro dev restart`, then verify with `docker exec <scheduler> unzip -v` that Deflate64 support is compiled in. Record the output line in the notes.
- **`include/pipeline/states/florida.py`**
  - A docstring naming the publisher (Florida Department of State, Division of Corporations), the server, the quarterly rhythm (January, April, July, October), the record layout source, and that the login is the public one the Division publishes for its data downloads.
  - `URL = "sftp://sftp.floridados.gov/Public/doc/quarterly/cor/cordata.zip"`, user `Public`, password `PubAccess1845!`. These are public credentials published by the state, not secrets (product decision 15). The SFTP listing with them worked on 2026-10-17. The server's banner says unauthorized access is prohibited; this login is the authorized public path.
  - **Host key:** record the server's host key SHA-256 on the first run (`ssh-keyscan sftp.floridados.gov`), and pass it on every call with `curl --hostpubsha256`. A changed key fails the task instead of trusting a new server.
  - **`download(file, data) -> bool`:**
    1. Run `curl --head` over SFTP to get the size and modification time. Verify the output shape on the first run and record it.
    2. Compare them with the sidecar `raw/fl/cordata.zip.meta.json`. If they match and the file has that size, log `unchanged cordata.zip` and return `False`.
    3. Otherwise download to `.part` with `curl --fail`, check the size, `os.replace`, and write the sidecar.

    Run `curl` with `subprocess.run(check=True)` and an argument list, never a shell string.
  - **`read(con, file, data)`:**
    1. Extract every member beside the zip with `unzip -o`, through `.part` names and `os.replace`. Skip a member that is newer than the zip, as `dol.extract` does.
    2. Assert the member list matches `cordata0.txt` to `cordata9.txt`, and record the real list on the first run.
    3. Read all members as one `VARCHAR` column per line, in Latin-1, so that byte offsets equal character offsets. Use no quoting and a delimiter that never occurs.
    4. Assert every line is exactly 1,440 characters.
  - The **select** cuts fields by the 1-based offsets below:

    | Field | Columns |
    | --- | --- |
    | Document number, the `registry_id` | 1–12 |
    | Name | 13–204 |
    | Status (`A` or `I`) | 205 |
    | Filing type, the `entity_type` (DOMP, DOMNP, FLAL, FORP, FORL, …) | 206–220 |
    | Principal address 1 | 221–262 |
    | Principal city | 305–332 |
    | Principal state | 333–334 |
    | Principal ZIP | 335–344 |
    | Mailing address | 347–472 |
    | File date (`MMDDYYYY`), the `formed_date` | 473–480 |
    | FEI | 481–494 |
    | More-than-six-officers flag | 495 |
    | Last transaction date | 496–503 |
    | State or country of origin | 504–505 |
    | Registered agent name | 545–586 |
    | Registered agent type | 587 |
    | Registered agent address | 588–629 |
    | Registered agent city | 630–657 |
    | Registered agent state | 658–659 |
    | Registered agent ZIP | 660–668 |
    | Officer 1: title, type, name, address, city, state, ZIP | 669–672, 673, 674–715, 716–757, 758–785, 786–787, 788–796 |
    | Officers 2 to 6 | each block 128 bytes after the one before |

    Its outputs:
    - Every field is trimmed, and blanks become NULL.
    - `formed_date` is a strict `strptime(…, '%m%d%Y')`.
    - `ein` is the FEI's digits when there are exactly 9 and they are not all zeros, else NULL. Record the share of records with an EIN.
    - `active = status = 'A'`.
    - `status_date` is the last transaction date. Check on the first run that inactive records carry their dissolution there, and record it.
    - `address_kind = 'physical'`, from the principal address.
    - `officers` is the list of `title || ': ' || name` for the officer blocks with a name.
    - `as_of` is the SFTP modification time, so Florida's activity signals are up to a quarter old.
  - Extras: `fl_mailing_address`, `fl_registered_agent_name`, `fl_state_country`, `fl_more_than_six_officers`.
  - `min_rows` is about 70% of the first run; `dropped=(0, 0)`. If document numbers repeat, record how often, dedupe deterministically on `last_transaction_date desc`, and set the range from the first run.
  - Sentinel `("444750", date(1974, 1, 24))`. The stage also asserts that its `ein` is `591517485`.
- **`states/__init__.py`:** `STATES` gains `florida`.
- **Tests:**
  - `tests/fixtures/states/florida/` holds three real 1,440-byte records cut from a member file: Raymond James, one inactive record and one with six officers. They are written into a small standard-deflate zip, because the test exercises `read`'s parsing, not Deflate64.
  - `tests/unit/states/test_florida.py`:
    - asserts the staged rows exactly, including `ein` and `officers`
    - asserts that a 1,439-character line raises
    - runs `download` against a fake `curl` on `PATH` (a tiny script in `tmp_path`) and checks the unchanged and changed paths without the network

## End-to-end verification

1. After adding `unzip`, run `astro dev restart`. Paste the `unzip -v` Deflate64 line and the pinned host key fingerprint.
2. Run `scripts/smoke.sh 14400` and paste its output. Record the download duration, the size on disk of the zip and the members, and the stage duration.
3. Paste both DuckDB commands above. Record:
   - Florida's matched share of PPP keys among non-individual businesses, and its calibrated `min_match_share`
   - how many sponsors joined by EIN (`plan_link = 'ein'`), by name and by the hop
   - `build`'s duration and peak memory, which grow with about 13 million more anchors
4. Spot-check two old Florida businesses against their raw records: `grep -a '^<document number>' raw/fl/cordata*.txt` gives the line, and the fields are cut by the offsets above. Paste the side-by-side.
5. A second run logs `unchanged cordata.zip` and skips extraction, and the file's `sha256sum` is identical.
6. `mise run check` passes.
