from pathlib import Path

# include/data on the host, /usr/local/airflow/include/data in the containers
DATA = Path(__file__).resolve().parents[1] / "data"
