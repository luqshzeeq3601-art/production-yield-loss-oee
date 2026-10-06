# Changelog

## 2026-10-06 — Remaining-project assessment and tracking

- Added [PROJECT_TRACK_LOG.md](PROJECT_TRACK_LOG.md) with task evidence, remaining gates, and the user-directed Power BI stopping point; linked it from the implementation plan.
- Reran the existing suite: 275 passed; processed-file verification: 9/9 passed; isolated pipeline CLI: 14 dry-run stages. Current live PostgreSQL validation was unavailable.
- Identified P5-004 integration/run-proof gaps and deferred actual Power BI validation and final portfolio acceptance.
- Read-only PBIX archive inspection confirmed seven pages and 36 visual containers. Preserved the pre-existing PBIX edit and restored test-generated analytical/reporting changes from exact pre-test copies.

## 2026-09-29 — Power BI assembly preparation (POWERBI-PREP)

- Persistent PostgreSQL 16.15 startup, local environment credentials, and live serving validation.
- 25 import relations, 83 DAX measures, Work Order coverage, frozen SPC precision/prevalence separation, continuous calendar, and seven-page readiness.
- Current verification: 275 tests, live full-warehouse DQ 65/65, artifact reconciliation 75/75; current evidence in `reports/powerbi_preparation_validation.json`.
- Explicit serving profile excludes MetroPT reading-level data; analytical defaults unchanged.
- Primary Codex only under the task-specific user exception; no Sol Advisor or independent review. Desktop remained closed; no PBIX created.
- Historical validation reports and analytical values preserved.

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
