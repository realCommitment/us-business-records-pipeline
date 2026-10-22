# C4 Component Level: System Overview

Components of the `tx_retiring_owners` pipeline. Tests and `scripts/smoke.sh` are verification, noted under each component, not components.

## System Components

### Pipeline Orchestration
- **Description**: Airflow DAG, task graph, dynamic mapping, retries and timeouts.
- **Documentation**: [c4-component-pipeline-orchestration.md](./c4-component-pipeline-orchestration.md)

### Source Ingestion
- **Description**: Conditional download and validated Parquet staging for SBA PPP, Texas Comptroller and DOL Form 5500 (`http.py`, `ppp.py`, `texas.py`, `dol.py`).
- **Documentation**: [c4-component-source-ingestion.md](./c4-component-source-ingestion.md)

### Matching and Shortlist
- **Description**: Name normalisation, PPP-to-registration matching, QC and CSV export (`names.py`, `sql/shortlist.sql`, `shortlist.py`, `naics_2017.csv`).
- **Documentation**: [c4-component-matching-and-shortlist.md](./c4-component-matching-and-shortlist.md)

### Storage Foundation
- **Description**: DuckDB connection, atomic Parquet/CSV writes and the data root (`db.py`, `paths.py`).
- **Documentation**: [c4-component-storage-foundation.md](./c4-component-storage-foundation.md)

## Component Relationships

```mermaid
C4Component
    title Component Diagram for RetiringBusinessOwners

    Container_Boundary(app, "Astro / Airflow 3 project") {
        Component(orch, "Pipeline Orchestration", "Airflow DAG", "tx_retiring_owners")
        Component(ing, "Source Ingestion", "Python", "http, ppp, texas, dol")
        Component(ms, "Matching and Shortlist", "Python, DuckDB SQL", "names, shortlist.sql, shortlist")
        Component(store, "Storage Foundation", "Python, DuckDB", "db, paths")
    }
    ComponentDb_Ext(fs, "include/data", "Parquet, CSV", "raw, stage, marts")
    System_Ext(sba, "SBA PPP site", "data.sba.gov")
    System_Ext(txg, "data.texas.gov", "Comptroller exports")
    System_Ext(dolx, "DOL EFAST/askebsa", "Form 5500 zips")

    Rel(orch, ing, "Calls download and stage", "Python call")
    Rel(orch, ms, "Calls build, qc, export", "Python call")
    Rel(ing, store, "Uses connect, copy_to_parquet", "Python call")
    Rel(ms, store, "Uses connect, copy_to_parquet", "Python call")
    Rel(store, ms, "Registers NAME_MACROS", "Python import")
    Rel(ing, sba, "Scrapes and downloads", "HTTPS")
    Rel(ing, txg, "Downloads", "HTTPS")
    Rel(ing, dolx, "Downloads", "HTTPS")
    Rel(store, fs, "Atomic writes", "files")
    Rel(ms, fs, "Reads stage, writes marts", "files")
```
