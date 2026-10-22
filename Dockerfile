FROM astrocrpublic.azurecr.io/runtime:3.3-9
# DuckDB's excel extension for the registries published as XLSX (spec 12),
# installed at build: the container's HOME is not writable, and a run needs no
# network for it
RUN python -c "import duckdb; duckdb.connect(config={'extension_directory': '/usr/local/airflow/duckdb_extensions'}).install_extension('excel')"
# The build's disk traffic delays Airflow's own database writes by 30 s and
# more (this disk's I/O scheduler is "none", so I/O priority does not help).
# With the defaults the scheduler then judged itself dead after 30 s and reset
# the running build, and a task's result, sent again after 5 s, failed as a
# duplicate (spec 13 notes). One scheduler on one machine can wait longer.
ENV AIRFLOW__SCHEDULER__SCHEDULER_HEALTH_CHECK_THRESHOLD=300 \
    AIRFLOW__WORKERS__EXECUTION_API_TIMEOUT=60
