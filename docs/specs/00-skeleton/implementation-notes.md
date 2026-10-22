# 00-skeleton implementation notes

## Decisions the spec did not cover

- **`USER: astro` in `docker-compose.override.yml`.** With only `user: "1000:0"`, every Airflow service crash-looped: uid 1000 has no passwd entry in the image, and the Airflow CLI wrapper calls `getpass.getuser()`, which raised `OSError: No username set in the environment`. The single-container check in `docs/data-sources.md` passed because `airflow version` never calls it. `getpass` reads `USER` first, so the override sets it on the same four services. The name is only a label; the image's own user is also called `astro`.
- **`astro dev run` output.** The Airflow CLI's structured warnings and a `Running: airflow ...` line go to stdout, not stderr, so `scripts/smoke.sh` keeps only the line that starts with `[` before `jq`. Exit codes do pass through: `astro dev run dags trigger no_such_dag` exits 1. `dags unpause` on a missing DAG exits 0 with "No paused DAGs were found", so only the trigger step proves the DAG exists.
- **The skip/xfail hook uses `language: pygrep`**, pre-commit's built-in regex hook. It runs no tool, so there is no version to take from `uv.lock`. The other three hooks are `language: system` through `uv run`. The regex is `pytest\.(mark\.)?skip|xfail`, which also catches an imperative `pytest.skip(`.
- **`tests/dags/test_dag_example.py` is in ruff's `extend-exclude`.** The template fails `I001` and `ruff format`. I read "kept apart from ruff fixes" as "left as the template wrote it". It passes as-is: `astro dev pytest tests/dags/test_dag_example.py` gave 3 passed.
- **`force-exclude = true` in the ruff config.** Pre-commit passes file names explicitly, and ruff applies `exclude` to explicit paths only when forced, so `.astro/` would otherwise be linted on every commit.
- **`airflow_settings.yaml` and `.env` are copied from the template but gitignored by the template's own `.gitignore`**, so they exist only in this checkout. `.env` is empty, because phase 1 has no secrets. `.worktreeinclude` copies `.env` into new worktrees.
- **`copy_to_parquet` escapes `'` in the destination path** before formatting it into `COPY ... TO '<path>'`. DuckDB would also accept `TO ?` (verified), but formatting the path in follows the spec and keeps caller parameters positional.

## Things worth knowing

- The scheduler created `scheduled__2026-10-17T00:00:00+00:00` as soon as the DAG was first parsed, as the product spec predicts for `catchup=False`. Triggered runs wait behind a running scheduled run because of `max_active_runs=1`.
- DuckDB 1.5.6 deletes its own partial output when a query fails during `COPY ... TO` (verified with a query that raises at row 900,000). The `.part` cleanup in `copy_to_parquet` therefore matters for failures after the COPY: the row count and the `os.replace`.
- Task logs are JSON lines at `/usr/local/airflow/logs/dag_id=<dag>/run_id=<run>/task_id=<task>/attempt=<n>.log`, with a `map_index=<n>/` directory for mapped tasks. Logger output from `logging.getLogger(__name__)` in the DAG file appears there.
- Astro CLI 1.46 also prints `Airflow UI: http://retiringbuinsinessowners.localhost:6563`, its local hostname proxy. http://localhost:8080 still works, and `scripts/smoke.sh` and `CLAUDE.md` use it.
- The repo is registered in Orca as `RetiringBuinsinessOwners` (id `861cf418-922f-47de-80d5-94fef808549f`).
- `copy_to_parquet` takes the row count from `COPY` itself, which returns the number of rows it wrote (verified on 1.5.6). Spec step 3 re-read the `.part` file with `read_parquet`; the code review pointed out that the second read is redundant, so it is gone.

## Code review (`/code-review high HEAD~1..HEAD`)

Fixed:
- `scripts/smoke.sh` exited 1 with no message when one `list-runs` poll failed or printed no JSON. It now prints the reason and the CLI output before exiting.
- A query ending in a `--` comment would swallow the closing parenthesis of `COPY (...)`. The query is now wrapped in newlines, and `test_writes_rows_and_leaves_no_part_file` uses a trailing comment.
- The redundant `read_parquet` count, as described above.

Skipped:
- "The fixed 8 GB memory limit is not enforced by a pool." By construction the DAG runs at most four stage tasks at once (`ppp_stage`, two `tx_stage`, `dol_stage`) on a 56 GB machine. That is product decision 5.
- "DuckDB connections are never closed." CPython frees a connection when its last reference goes, which is when the task function returns, and no task holds two at once.
- "Test asserts carry no message." I read the Mistakes rule as covering pipeline assertions. Pytest already prints both sides of a failed test assert.
- "The socket guard allows only the literal 127.0.0.1 and patches only `connect`." That is what the spec asks for, and nothing the tests use calls `connect_ex`.
- "The `requirements.txt` comment contradicts pyproject, which also pins requests." The comment text is from the spec. `requests` is left out because the image ships the same 2.34.2.
- "uid 1000 is hard-coded four times." That is product decision 2, specific to this machine.
- "The WIP commit has no evidence." It was squashed into the final commit.
