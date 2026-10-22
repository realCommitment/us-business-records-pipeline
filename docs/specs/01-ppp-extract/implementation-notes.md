# 01-ppp-extract implementation notes

## Real data, first full run (2026-10-17)

- 13 files, 4.9 GB in `include/data/raw/ppp/`, downloaded in about 8 minutes at three at a time. A stage run over all of them takes about 10 seconds.
- `ppp_tx.parquet` has 938,534 Texas loans (938,551 read, 17 dropped, see below) and 759,013 distinct `(norm_name, zip5)` businesses. Approval dates run from 2020-04-03 to 2021-06-30.
- `min_rows` defaults to 650,000, about 70% of the staged count.

## Decisions the spec did not cover

- **`encoding='latin-1'`.** The SBA CSVs are not UTF-8, and DuckDB's default reader rejects them. The first 30 MB of `public_up_to_150k_1_240930.csv` has 476 stray bytes (0xBF 448 times, 0xA0 27 times, 0xAE once, as in `501(c)3 ¿ Non Profit`) and not one valid multi-byte UTF-8 sequence. Latin-1 maps each byte to one character, and `norm_name` turns any non-ASCII character into a space, so matching loses nothing. One fixture row carries a 0xBF byte so the option stays tested.
- **Strict parsing in place of `try_strptime` plus a date assertion.** `strptime(nullif(DateApproved, ''), ...)` and plain casts make a malformed date or number fail the read before anything is written, so the previous `ppp_tx.parquet` survives. The spec's version asserted after writing, when the bad file had already replaced the good one. DuckDB's error names the bad value. The full run had no parse failures.
- **Loans without a ZIP or a usable name are dropped.** The spec asserted that none exist; the real data has 17 out of 938,551. Thirteen have no ZIP; most of those have `N/A` as their address. Four have no name left after normalization, such as `LLC INC` and `-`. None of them can be matched, and a NULL would merge unrelated loans in spec 04's `(norm_name, zip5)` grouping. The stage drops them, logs `dropped=<n>`, and fails if 1,000 or more are dropped. The fixtures gained a seventh row, a Texas loan without a ZIP, which the stage drops.
- **To count the dropped rows without reading 4.9 GB twice**, the stage reads the Texas rows into a temp table. It checks the floor and the dropped count there, then copies the usable rows, so a failed check never replaces the previous file.
- **Name normalization beyond the spec's nine steps.** Both changes are in `NAME_MACROS`, so they apply to every source, and each has a test row:
  - HTML entities are decoded first. 3,575 Texas names (0.4%) contain them: `&AMP;` 3,251 times, `&#39;` 209 times, `&APOS;` 82 times, and a few others. Undecoded, `PATRIOT PLACE &AMP; FINISH, LLC` normalized to `PATRIOT PLACE AND AMP FINISH` and could never match exactly.
  - A name that is only a DBA keeps the DBA as its `norm_name`. 172 Texas names such as `DBA CHURCH FOUNDATION REPAIR` would otherwise normalize to NULL.
- **Helper macros.** `name_unescape`, `name_clean` and `name_finish` exist next to the two macros the spec names, so the shared steps are written once.
- **Fixture layout.** Six listed rows with "exactly 4" Texas rows only works if one of the unspecified rows is out of state. The quoted comma name is therefore on the Texas corporation (`"SUMTER COATINGS, INC."`) and also on one out-of-state row.
- **`requests.head` gets `allow_redirects=True`**, because unlike `get` it does not follow redirects by default. The DOL host in spec 03 needs it.
- **The `.meta.json` sidecar is also written through a `.part` file and `os.replace`**, so a crash can never leave a truncated sidecar that would fail every later run.
- **`ppp_discover` logs `ppp_discover links=13 removed=[...]`** as its one summary line.
- **`parse_links` also fails when one file appears in two releases**, for example `public_up_to_150k_1_240930.csv` next to `public_up_to_150k_1_250331.csv`. A page caught mid-republish would otherwise count those loans twice.
- **A raw file whose size no longer matches its sidecar is downloaded again**, even when the ETag is unchanged.
- **The first run's `ppp_stage` failed once**, on the spec's "no row lacks zip5" assertion (13 of 938,551 rows). The fix above landed during the 5-minute retry delay, and attempt 2 passed. Two later clean runs logged `unchanged` for all 13 files and the same counts.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- The floor and dropped-count checks ran after `copy_to_parquet` had replaced the file. They now run on the temp table first.
- Two releases of one file on the page would double-count loans. `parse_links` now raises.
- A truncated raw file with an intact sidecar would never be downloaded again. The size is now compared too.
- `^THE ` did not strip a bare `THE`, so `THE DBA RIVERSIDE GRILL` normalized to `THE`. It is now `^THE( |$)`, with a test row.
- `nullif(x, '')` on CSV fields was redundant, because DuckDB reads empty fields, quoted or not, as NULL (verified). Removed.

Skipped, with evidence:
- "Store the GET's ETag and Last-Modified instead of the HEAD's." The Socrata export's GET answers with a weak ETag that has an extra suffix (`W/"...--gzip--gzip"` against the HEAD's `"...--gzip"`), so stored GET values would never equal the next HEAD's and both Texas files would download in full every day. SBA and DOL return identical values on both. HEAD values stay, as the product spec decided.
- "Strip accents instead of turning them into spaces." All 938,534 Texas PPP names are printable ASCII, so there is nothing to strip. The cp1252 0x92 apostrophe never appears in a name either.
- "Validate zip5 as five digits." Every staged `zip5` is five digits.
- "Raise the smoke script's 600 s default." The default is the spec's. It fits daily runs, and the first-download commands pass 14400 explicitly.
