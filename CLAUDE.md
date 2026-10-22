# RetiringBusinessOwners

A local Astro (Airflow 3) pipeline that builds a daily dataset of every US business found in national and state public records (SBA PPP, DOL Form 5500 and free state registries), with industry, years in business, lookup details and open status.

## Commands

- Install: `mise trust && mise install && uv sync && uv run pre-commit install`
- Run: `astro dev start`, then http://localhost:8080.
- Test: `uv run pytest tests/unit/<file>::<test>`, or `mise run check` for the full set.
- Lint and format: `mise run check`.
- Migrate: none; Airflow migrates its own database on start.

## Working here

- Specs live in `docs/specs/<nn>-<feature>/spec.md`, written with `/interview-me-engineering`. Implementation happens in a fresh session with `/implement`, which keeps `implementation-notes.md` beside the spec.
- Nothing is done until the app has been run. Verify against the running app, not tests alone.
- Every commit body carries the evidence: a `Verified` list with the exact commands and results, and a `Not verified` list. The human reviews commits, not chat.
- Never open a pull request or push unless the human runs `/commit-push-pr`.
- When compacting, always preserve the spec path, the implementation notes path, and the list of modified files.
- Data lives in `include/data/`, which is gitignored; query it with DuckDB from the host.
- Read a task log from the repo root with `docker exec $(docker ps -q --filter label=io.astronomer.docker.component=airflow-scheduler --filter label=com.docker.compose.project.working_dir=$PWD) cat /usr/local/airflow/logs/dag_id=retiring_owners/run_id=<run>/task_id=<task>/attempt=1.log`. The working-directory filter matters because other Astro projects on this machine also run a scheduler. Mapped tasks have a `map_index=<n>/` directory before `attempt=1.log`.
- `include/` never imports Airflow.
- Everything about one state lives in `include/pipeline/states/<state>.py`; no other file names a state. Adding a state is one new module, one line in `STATES`, a fixture under `tests/fixtures/states/<state>/` and a test in `tests/unit/states/`.

## Mistakes

<!-- Every time Claude does something wrong, have it write the fix here or into a skill, instead of correcting it in chat. Prefer a lint rule, a CI step, or a hook over a sentence here whenever one is possible. -->

- No fallback defaults that hide a failure.
- No swallowed exceptions.
- No `ignore_errors` in CSV reads.
- No `sleep` to fix a race.
- Every assertion message names the file and the numbers.
