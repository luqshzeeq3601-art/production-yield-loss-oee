# Architecture

End-to-end data flow and analytical lineage for the Production Yield Loss & OEE Early-Warning System. Both diagrams render on GitHub (Mermaid) and match the repository as committed.

## Diagram 1 — System pipeline

```mermaid
flowchart TB
    SECOM["SECOM<br/>1,567 lots, 446 sensors"]
    METRO["MetroPT-3<br/>1,516,948 obs x 15 signals"]
    MES["Simulated MES (seed 42)<br/>17,280 production rows"]
    SECOM --> ING
    METRO --> ING
    MES --> ING
    ING["Python ingestion / validation<br/>src/ingest_*.py, simulate_mes.py"]
    ING --> PG["PostgreSQL 16<br/>staging -> dims/facts"]
    PG --> DQ["DQ layer<br/>65 checks, 0 violations"]
    PG --> SPC["SPC engine<br/>WE / EWMA / Hotelling T2"]
    PG --> OEE["OEE / Pareto / RCA / What-if<br/>SQL views + Python"]
    SPC --> OEE
    DQ --> PBI
    OEE --> PBI["Power BI semantic layer<br/>83 DAX measures"]
    PBI --> REP["Reporting / portfolio outputs<br/>pipeline + Excel baseline"]
```

Stage order is enforced by `src/run_pipeline.py` (14 stages): `ingest_secom`, `ingest_metropt3`, `simulate_mes`, `load_db`, `run_dq_checks`, `feature_screening`, `spc_engine`, `spc_backtest`, `rca_pareto`, `rca_statistical`, `oee_whatif`, `manual_baseline`, `powerbi_model`, `dashboard_spec`.

## Diagram 2 — Analytical lineage

```mermaid
flowchart LR
    SRC["source CSVs"] --> STG["staging tables"]
    STG --> FACT["facts / dimensions"]
    FACT --> AN["SQL + Python analytics"]
    AN --> REC["reconciliation<br/>75/75 checks"]
    REC --> IMP["impact metrics<br/>57 rows"]
    IMP --> REP2["reporting"]
```

Traceability rule: every headline number traces source → processed data → PostgreSQL → analytical module → report → Power BI/documentation. `reports/cross_system_reconciliation.csv` is the audit trail; `reports/impact_metrics.csv` is the single source for portfolio claims.
