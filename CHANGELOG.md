# Changelog

## v1.0.0 — Portfolio release candidate

- Complete ingestion pipeline (SECOM, MetroPT-3 chunked load, deterministic MES simulation)
- PostgreSQL 16 warehouse (staging, 9 dimensions, 9 facts) with row-for-row reconciliation
- DQ framework: 65 automated checks, zero violations
- SPC backtesting (Western Electric, EWMA, Hotelling T²) on 1,097 Phase II lots
- OEE / Pareto / statistical RCA / 30% combined what-if modeling
- Power BI semantic specification (36 DAX measures, 7 dashboard pages specified)
- Reporting automation baseline (6 h/week → <10 min/week target)
- Cross-system reconciliation (75/75) and impact-metrics evidence
- Portfolio documentation (README, case study, resume bullets, project facts)

Known limitation: final `.pbix` assembly remains a manual Power BI Desktop step.
