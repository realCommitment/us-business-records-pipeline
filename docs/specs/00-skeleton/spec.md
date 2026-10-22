# 00-skeleton

The Astro project in this repo starts, runs one task that writes to the shared data folder, and carries the gates every later spec uses.

Bound by `docs/specs/00-product/spec.md` (decisions 1 to 4 and 13 to 15). Toolchain facts are in `docs/data-sources.md`, section "Toolchain".

## Goal

After this spec, `astro dev start` brings up Airflow 3.3.2 locally, and `scripts/smoke.sh` runs the `tx_retiring_owners` DAG and waits for it to succeed. The DAG has one placeholder task, `smoke`. It writes `include/data/stage/_smoke.parquet` through the shared atomic Parquet writer. That proves three things: the containers can write the host-mounted data folder, DuckDB is in the image, and the host can read and delete what the containers wrote. `mise run check` is the one validation command. Spec 01 replaces the placeholder task with real ones.

## What the user can do afterwards

```
mise trust && mise install && uv sync && uv run pre-commit install
astro dev start
scripts/smoke.sh
uv run python -c "import duckdb; print(duckdb.sql(\"from 'include/data/stage/_smoke.parquet'\"))"
mise run check
```

`scripts/smoke.sh` prints `tx_retiring_owners smoke__<timestamp>: success` and exits 0. The query prints today's UTC date and DuckDB's version. `mise run check` passes.

## Anti-goals

- No pipeline logic. That is specs 01 to 04.
- No compose file of our own beyond `docker-compose.override.yml`, and no services besides the ones the Astro CLI starts.
- No Airflow stack per worktree (checklist item 2).
- No CI. This machine is the only environment.
- No `plugins/` code, and no Airflow connections or variables.

## Checklist decisions

From `docs/skeleton-checklist.md`, one entry per item.

1. **Services in compose with health checks: adapt.** The Astro CLI owns the compose stack: Postgres for Airflow metadata, scheduler, dag-processor, api-server and triggerer, all `restart: unless-stopped`. It waits for `/api/v2/monitor/health` on start. We add only `docker-compose.override.yml`. There is no app database, because the data is files read with DuckDB.
2. **One compose stack per worktree: skip.** Astro publishes fixed ports 8080 and 5432, and each checkout would need its own 10 GB of downloads. Worktrees get mise and `.venv` through `orca.yaml`, enough for unit tests and lint. Only one checkout runs `astro dev start` at a time.
3. **Bootstrap and smoke: adapt.** There are no migrations and no seed. Airflow migrates its own database on start, and the seed data is the fixture files each spec adds under `tests/fixtures/`. Bootstrap is the first line under "What the user can do afterwards". Smoke is `scripts/smoke.sh`.
4. **Strict types: adopt for `include/` and `tests/unit/`, with `mypy --strict`.** `dags/` is excluded because Airflow is not installed on the host; `astro dev parse` checks it in the image. Skip `ty`, because one type checker is enough. Skip Pydantic, because the boundaries are CSV headers, which each stage checks with assertions.
5. **Tests: adopt.** Tests run on the host as `uv run pytest tests/unit/<file>::<test>`. They stay offline: an autouse fixture refuses socket connections to anything but 127.0.0.1. `run_date` is passed in explicitly, so no frozen time is needed. Assertions are exact. The first real test is in `test_db.py`.
6. **End-to-end: adapt.** The end-to-end check is one DAG run through `scripts/smoke.sh` plus a DuckDB query on its output. There is no browser test.
7. **Agent access to the running system: adopt.** The agent has five ways in:
   - `astro dev run <airflow cli args>`
   - `astro dev logs`
   - the API on http://localhost:8080
   - task log files, read with `docker exec` on the scheduler container (command in CLAUDE.md)
   - DuckDB on the host, reading `include/data/`
8. **Logging: adapt.** Airflow already captures task logs. Each task logs one summary line with its counts through the standard `logging` module. The no-secrets test waits until phase 2 adds API keys.
9. **Gates: adopt.** Pre-commit runs `ruff check`, `ruff format --check`, `mypy --strict`, and a `pygrep` hook that rejects `pytest.mark.skip` and `xfail` under `tests/`. All hooks are `language: system` and run through `uv run`, so tool versions come from `uv.lock`. `mise run check` is the one command; `make` is not installed on this machine.
10. **Fail loud: adopt.** These rules go under Mistakes in CLAUDE.md:
    - no fallback defaults that hide a failure
    - no swallowed exceptions
    - no `ignore_errors` in CSV reads
    - no `sleep` to fix a race
    - every assertion message names the file and the numbers
11. **Module boundary lint: adapt, with one rule.** Ruff's `TID251` bans importing `airflow` everywhere except `dags/`, `tests/dags/` and `.astro/`, so pipeline code stays testable on the host.
12. **Review standards file: skip.** The owner is a solo developer. Revisit if `/code-review` findings repeat.

Two more entries from the checklist, both from the template defaults:
- **Scope limits: not adopted.**
- **Memory beyond CLAUDE.md Mistakes: not adopted.**

## Files and interfaces

- **Template files.** Run `astro dev init -n retiring-business-owners` in a scratch directory, so it cannot touch `README.md` or `CLAUDE.md`. Copy in:
  - `Dockerfile` (`FROM astrocrpublic.azurecr.io/runtime:3.3-9`)
  - `.dockerignore`
  - `packages.txt` (empty)
  - `.astro/config.yaml`, `.astro/test_dag_integrity_default.py` and `.astro/dag_integrity_exceptions.txt`
  - `dags/.airflowignore`
  - `tests/dags/test_dag_example.py`, kept apart from ruff fixes. It requires tags and `retries >= 2` on every DAG.
  - `airflow_settings.yaml`

  Do not copy `dags/exampledag.py`, which calls an external API daily, or the template's README.
- `.gitignore`: the template's lines plus `include/data/`, `.ruff_cache/`, `.mypy_cache/` and `.pytest_cache/`.
- `.dockerignore`: the template's lines plus the same four entries. Without `include/data/` every image build would send gigabytes of build context.
- `docker-compose.override.yml`: `user: "1000:0"` on `scheduler`, `dag-processor`, `api-server` and `triggerer`. Add this comment: `# host uid 1000 owns the bind mounts; the image's uid 50000 gets Permission denied writing include/data. gid 0 keeps the image's group-writable dirs writable.`
- `mise.toml`:
  - `[tools]`: `python = "3.14"`, `uv = "0.13.0"` and `astro = "1.46.0"`. The mise registry maps `astro` to `github:astronomer/astro-cli`.
  - `[env]`: `_.python.venv = { path = ".venv", create = true }`
  - `[tasks.check]`: `run = ["uv run pre-commit run --all-files", "uv run pytest tests/unit -q", "astro dev parse"]`
- `orca.yaml` and `.worktreeinclude` (listing `.env`), per step 7 of the `setup-repo` skill. The setup script runs `mise trust`, `mise install`, `mise exec -- uv sync` and `mise exec -- uv run pre-commit install`. Register the repo in Orca per step 6 of that skill if it is not registered yet.
- `pyproject.toml`:
  - Project `retiring-business-owners`, with `requires-python = ">=3.14,<3.15"`.
  - Dependencies: `duckdb==1.5.6`, and `requests==2.34.2`, which is the version the image ships.
  - Dev dependency group: `pytest`, `ruff`, `mypy`, `pre-commit` and `types-requests`.
  - Ruff: default line length; `extend-exclude = [".astro"]`, because those files are generated and marked do-not-edit; lint rules `select = ["E", "F", "I", "B", "UP", "TID"]`; `banned-api` for `airflow` with the reason from item 11; `per-file-ignores` for `dags/**` and `tests/dags/**`.
  - Mypy: `strict = true`, `files = ["include", "tests/unit"]`.
  - Pytest: `pythonpath = ["."]`, `testpaths = ["tests/unit"]`.
- `requirements.txt`: `duckdb==1.5.6`, with the comment `# keep equal to pyproject.toml; the image installs from this file`.
- `.pre-commit-config.yaml`: the four local hooks from item 9.
- `include/__init__.py` and `include/pipeline/__init__.py`, both empty. The image puts `/usr/local/airflow` on `PYTHONPATH`, so `from include.pipeline import ...` works in the containers. Pytest's `pythonpath` makes the same import work on the host.
- `include/pipeline/paths.py`: `DATA = Path(__file__).resolve().parents[1] / "data"`. It resolves to `include/data` on the host and to `/usr/local/airflow/include/data` in the containers.
- `include/pipeline/db.py`:
  - `connect() -> duckdb.DuckDBPyConnection`: an in-memory connection that runs `SET memory_limit = '8GB'`, with the comment `up to four stage tasks run at once; DuckDB's default of 80% of RAM each could OOM the machine`.
  - `copy_to_parquet(con, query: str, dest: Path, params: list[object] | None = None) -> int`:
    1. Create `dest.parent`.
    2. Run `COPY (<query>) TO '<dest>.part' (FORMAT parquet)` with `params` bound. Parameter binding inside COPY works in DuckDB 1.5.6 (verified).
    3. Count the rows with `read_parquet('<dest>.part')`. The explicit reader is required: DuckDB cannot infer the format from a `.part` suffix (verified).
    4. `os.replace` the file onto `dest` and return the count.

    On any exception it deletes the `.part` file and re-raises, so the previous `dest` survives untouched.
- `dags/tx_retiring_owners.py`:
  - The DAG: `@dag(schedule="@daily", start_date=pendulum.datetime(2026, 10, 1, tz="UTC"), catchup=False, max_active_runs=1, is_paused_upon_creation=False, tags=["texas"], default_args={"retries": 2, "retry_delay": timedelta(minutes=5)})`.
  - One `@task`, `smoke`, which runs `copy_to_parquet(connect(), "select current_date as run_date, version() as duckdb_version", DATA / "stage" / "_smoke.parquet")` and logs `smoke rows=1 path=...`.
- `tests/unit/conftest.py`: the autouse socket guard from item 5.
- `tests/unit/test_db.py`:
  - `copy_to_parquet` writes exactly the expected rows and leaves no `.part` file.
  - A failing query raises and leaves the previous file byte-identical.
  - `params` are bound.
- `scripts/smoke.sh`: about 25 lines of `set -euo pipefail` bash. Its only argument is a timeout in seconds, default 600. It does four things:
  1. Fails if `curl -fsS http://localhost:8080/api/v2/monitor/health` fails.
  2. Runs `astro dev run dags unpause tx_retiring_owners`.
  3. Triggers a run with run id `smoke__<UTC timestamp>`.
  4. Polls `astro dev run dags list-runs tx_retiring_owners -o json` every 15 seconds with `jq`. It exits 0 when that run reaches `success`, and 1 when it reaches `failed` or the timeout passes.

  The Airflow CLI prints structured warnings. Confirm whether they go to stderr; if not, strip non-JSON lines before `jq`. Note which.
- `CLAUDE.md`:
  - Replace the placeholder first line with one sentence about the repo.
  - Fill in Commands:
    - Install: the bootstrap line.
    - Run: `astro dev start`, then http://localhost:8080.
    - Test: `uv run pytest tests/unit/<file>::<test>`, or `mise run check` for the full set.
    - Lint and format: `mise run check`.
    - Migrate: none; Airflow migrates its own database on start.
  - Add three lines under Working here:
    - Data lives in `include/data/`, which is gitignored; query it with DuckDB from the host.
    - Read a task log with `docker exec $(docker ps -qf label=io.astronomer.docker.component=airflow-scheduler) cat /usr/local/airflow/logs/dag_id=tx_retiring_owners/run_id=<run>/task_id=<task>/attempt=1.log`, after confirming the path layout once.
    - `include/` never imports Airflow.
  - Add the fail-loud rules from item 10 under Mistakes.

## End-to-end verification

1. From a clean checkout, the bootstrap line succeeds, and `astro version` prints 1.46.0 from the mise shim.
2. `astro dev start` comes up. `astro dev ps` shows postgres, scheduler, dag-processor, api-server and triggerer running.
3. `docker exec $(docker ps -qf label=io.astronomer.docker.component=airflow-scheduler) id` prints `uid=1000 gid=0(root)`.
4. `scripts/smoke.sh` prints success and exits 0. Paste its output into the commit body.
5. `ls -ln include/data/stage/` shows `_smoke.parquet` owned by uid 1000, and the DuckDB query prints today's date and `v1.5.6`. `rm include/data/stage/_smoke.parquet` succeeds as the host user, and a second `scripts/smoke.sh` recreates the file.
6. Each gate is proven to fail once and then reverted, with both results recorded:
   - Adding `import airflow` to `include/pipeline/db.py` makes `uv run ruff check` fail with `TID251`.
   - Adding `@pytest.mark.skip` to a unit test makes `uv run pre-commit run --all-files` fail.
7. `mise run check` passes. Paste the pytest counts and the `astro dev parse` result.
8. `git check-ignore include/data/stage/_smoke.parquet` and `grep -x 'include/data/' .dockerignore` both succeed.
