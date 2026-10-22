from datetime import timedelta

import pendulum
from airflow.sdk import dag, task

from include.pipeline import businesses, states
from include.pipeline.national import dol, fmcsa, ppp, sam, sba


@dag(
    schedule="@daily",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    # a triggered run of a paused DAG stays queued forever
    is_paused_upon_creation=False,
    tags=["retiring-owners"],
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
)
def retiring_owners() -> None:
    @task
    def ppp_discover() -> list[str]:
        return ppp.discover()

    @task(max_active_tis_per_dag=3, execution_timeout=timedelta(hours=2))
    def ppp_download(url: str) -> bool:
        return ppp.download(url)

    @task(execution_timeout=timedelta(minutes=30))
    def ppp_stage(urls: list[str]) -> int:
        return ppp.stage(urls)

    @task(
        max_active_tis_per_dag=3,
        execution_timeout=timedelta(hours=2),
        map_index_template="{{ task.op_kwargs['file_name'] }}",
    )
    def state_download(file_name: str) -> bool:
        return states.download(file_name)

    @task(
        max_active_tis_per_dag=3,
        execution_timeout=timedelta(hours=1),
        map_index_template="{{ task.op_kwargs['name'] }}",
    )
    def state_stage(name: str) -> int:
        return states.stage(name)

    @task(max_active_tis_per_dag=2, execution_timeout=timedelta(hours=1))
    def dol_download(url: str) -> bool:
        return dol.download(url)

    @task(execution_timeout=timedelta(hours=1))
    def dol_stage() -> int:
        return dol.stage()

    @task
    def sba_discover() -> list[str]:
        return sba.discover()

    @task(max_active_tis_per_dag=3, execution_timeout=timedelta(hours=2))
    def sba_download(url: str) -> bool:
        return sba.download(url)

    @task(execution_timeout=timedelta(hours=1))
    def sba_stage(urls: list[str]) -> int:
        return sba.stage(urls)

    @task
    def sam_discover() -> str:
        return sam.discover()

    @task(execution_timeout=timedelta(hours=1))
    def sam_download(name: str) -> bool:
        return sam.download(name)

    @task(execution_timeout=timedelta(hours=1))
    def sam_stage(name: str) -> int:
        return sam.stage(name)

    # the census is streamed with no length, about 1.7 GB in 34 min (spec 13)
    @task(execution_timeout=timedelta(hours=2))
    def fmcsa_download() -> bool:
        return fmcsa.download()

    @task(execution_timeout=timedelta(hours=1))
    def fmcsa_stage() -> int:
        return fmcsa.stage()

    @task(execution_timeout=timedelta(hours=2))
    def build() -> dict[str, object]:
        return businesses.build()

    @task(execution_timeout=timedelta(minutes=30))
    def qc() -> None:
        businesses.qc()

    urls = ppp_discover()
    ppp_staged = ppp_stage(urls)
    ppp_download.expand(url=urls) >> ppp_staged
    state_staged = state_stage.expand(name=list(states.SOURCES))
    state_download.expand(file_name=list(states.FILES)) >> state_staged
    dol_urls = [dol.url(form, year) for year in dol.YEARS for form in dol.FORMS]
    dol_staged = dol_stage()
    dol_download.expand(url=dol_urls) >> dol_staged
    sba_urls = sba_discover()
    sba_staged = sba_stage(sba_urls)
    sba_download.expand(url=sba_urls) >> sba_staged
    sam_name = sam_discover()
    sam_staged = sam_stage(sam_name)
    sam_download(sam_name) >> sam_staged
    fmcsa_staged = fmcsa_stage()
    fmcsa_download() >> fmcsa_staged
    staged = [ppp_staged, state_staged, dol_staged, sba_staged, sam_staged]
    [*staged, fmcsa_staged] >> build() >> qc()


retiring_owners()
