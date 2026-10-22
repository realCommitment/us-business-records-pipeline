# 02-tx-comptroller-extract implementation notes

## Real data, first full run (2026-10-17)

- `tx_franchise.csv` is 469,597,955 bytes and downloaded in about 3 minutes. `tx_sales_outlets.csv` is 157,294,884 bytes and took about 7 minutes. Neither returned HTTP 429, so no Socrata app token is needed.
- Franchise: 3,486,216 rows read, 31 duplicate taxpayer numbers dropped, 3,486,185 staged, as `docs/data-sources.md` predicted. `right_to_transact` breaks down as A 2,898,886, N 519,126, U 45,529 and D 22,644; none is blank today.
- Outlets: 890,307 rows, 170,950 of them with an `ein`.
- The default floors stay at the spec's 3,000,000 and 800,000, which is 86% and 90% of today's counts.

## Decisions the spec did not cover

- **Every raw field is stripped and blanks become NULL.** The raw table applies `nullif(trim(columns(*), e' \t\r\n'), '')` to every column.
  - About 13% of franchise rows (290 of the first 2,181) pad every text field with a trailing space, as in `'10101858008 '`, and leave blank codes as two spaces.
  - A few quoted fields end in a newline: 2 in `right_to_transact` (`'A\n'`), 48 in `naics`, and a handful in other columns. One-argument `trim()` strips only spaces, so the characters are listed.
  - Uncleaned, those rows would fail `right_to_transact = 'A'` in spec 04, miss the outlet-to-franchise join, and slip past the duplicate check.
  - The fixtures cover both cases: the padded `FIRST HARTFORD` row is real, and the `SANCHEZ` row ends a quoted field in a newline. With one-argument `trim()` the test fails.
- **Deterministic dedupe.** Of the 31 duplicated taxpayer numbers, 12 tie on every ordering key the spec gives. 8 of them are exact copies, and one differs only in a column the stage does not keep. Three differ in `record_type` (U against X) or `exempt_reason`, so `record_type, exempt_reason` were added as final tiebreakers and the same copy is kept every run.
- **Strict date parsing**, as in spec 01: `strptime(x, '%m/%d/%Y')` fails the stage on a malformed date instead of producing NULL, so the date assertion is the read itself. The malformed-date fixture raises, and no stage file is written.
- **Checks run before the write.** Typed rows go to a temp table, the floor, `ein`, duplicate and Texas Instruments checks run on it, and only then does `copy_to_parquet` replace the stage file. This follows the spec 01 code review.
- **The franchise dedupe goes through a `typed` CTE**, so `qualify` orders by real dates. The raw columns share the output names, and ordering by them would compare `MM/DD/YYYY` strings.
- **No accent stripping.** The 51 franchise and 121 outlet names with non-ASCII characters are mostly U+FFFD replacement characters introduced at the source (`DO�AS ARRANGEMENTS`), not accented letters. `norm_name` turns them into spaces.
- **The header check reads the first line as UTF-8.** Both exports are UTF-8 with no BOM and LF line endings (verified).

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- The whitespace cleanup used a regex where `trim(x, e' \t\r\n')` does the same job more plainly. Switched; the note above is corrected.
- The dedupe could keep a different copy on different runs for 3 taxpayers. It now has deterministic tiebreakers.
- The comment about the size check named the wrong header. Reworded: a streamed export has no Content-Length to check.

Skipped:
- "Each dataset should have its own download-then-stage chain, so one failed download does not skip the other dataset's stage." The spec sets this shape. `build` in spec 04 needs both stages, so a failed download stops that day's shortlist either way.
- "A blank taxpayer number would be folded into the dedupe." There are none today. If one appears, the uniqueness check still fails the stage, though with a less precise message.
- "`0 < dropped < 1000` and the Texas Instruments check fail on a correct export." The spec asks for both, deliberately: a change in either is a reason to re-verify the source by hand.
- "A truncated chunked stream that closes cleanly is never caught." A network failure breaks mid-chunk and raises in `requests`. A clean early close is a server bug, and the stage's row floor and strict CSV parsing would fail loudly on it.
- "Two temp tables hold the franchise data in memory." The stage takes about 4 seconds, and four concurrent stages stay well under the 8 GB per-connection limits on a 56 GB machine.
- "Skip the stage when the download is unchanged." Product decision 7 rebuilds every run on purpose.
- "`HEADERS` in texas.py shares a name with `http.HEADERS`." The name is the spec's, and texas.py does not import the other one.
