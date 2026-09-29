# Case Study: Production Yield Loss & OEE Early-Warning System

## 1. Problem

Yield drops and line bottlenecks surfaced 1-3 days late in manual Excel reports. Management saw one blended output number with no split across Availability, Performance, and Quality, so improvement effort spread thin while scrap accumulated. Engineers spent about 6 hours a week copy-pasting MES exports into workbooks.

## 2. Goal

Build an end-to-end, reproducible analytics product — raw data to Python SPC/RCA analytics to a PostgreSQL star schema to Power BI — with three measurable objectives: (O1) cut defect-to-alert latency >=70% with >=60% alert precision; (O2) decompose OEE and isolate the top loss causes; (O3) automate weekly reporting from ~6 h to under 10 min.

## 3. Data

Real UCI SECOM semiconductor data (1,567 lots, 446 sensors after cleaning, 104 fails), real UCI MetroPT-3 compressor telemetry (1,516,948 observations x 15 signals, 4 documented failure windows), and a deterministic simulated MES (seed 42: 17,280 production rows, 24,147 downtime events, 4,096 quality events across 4 lines x 3 shifts x 180 days). The simulation openly injects three scenarios — L2 night-shift minor stops, L3 tool wear, a supplier-material excursion — so the RCA "discovery" is transparent, not circular.

## 4. Approach

Ingestion with chunked processing and timestamp validation; a PostgreSQL star schema with staging-to-fact reconciliation; 65 automated DQ checks; statistical feature screening (FDR-controlled); I-MR + Western Electric rules + EWMA + Hotelling T² with Phase I limits frozen before Phase II; a chronological backtest against a next-day 08:00 manual baseline; OEE/Pareto/statistical RCA; a 30% combined what-if model; and a Power BI semantic layer reconciled to SQL within 0.1%.

## 5. Key analysis

OEE decomposed to 91.29% x 84.50% x 96.46% = 74.41%, with L2 Performance and L3 Quality as the weak legs. Pareto concentrated 74.38% of scrap cost and 87.75% of unplanned downtime in three causes each. The backtest caught all 46 Phase II failures a median ~18 h before manual review — at 4.21% precision.

## 6. Results

O2 and O3 fully achieved; O1 split (see below). Automation arithmetic: 312.0 h/year manual vs 8.7 h/year target = ~303.3 h/year saved (97.2%). The modeled 30% combined scenario projects 74.41% -> 78.96% OEE (+4.55 pts) and $1.69M annual recoverable value. Validation: 275 tests, 65/65 DQ, 75/75 cross-system reconciliation, SQL-DAX diff ~1e-14%.

## 7. What failed / what I learned

The 60% precision target failed badly (4.21%) with the selected rule alerts flagging nearly every lot at 4.19% failure prevalence. Lesson: recall without precision is not an operational win — the honest result redirected the recommendation toward rule refinement (multivariate-first alerting, cost-aware thresholds) instead of a false success story. I kept the failed metric visible in every artifact rather than tuning thresholds post hoc.

## 8. Business interpretation

Measured value today: honest loss decomposition plus ~300 h/year of reporting capacity freed. The $1.69M is a modeled sizing of the prize for a 30% loss reduction, useful for prioritizing L2 minor stops and L3 tool wear — not money saved.

## 9. Technical architecture

`SECOM/MetroPT-3/MES -> Python ingestion -> PostgreSQL staging -> dims/facts -> DQ -> SPC -> OEE/Pareto/RCA/what-if -> Power BI DAX layer -> pipeline automation`, orchestrated by a 14-stage `run_pipeline.py` with dry-run, stage selection, and failure propagation.

## 10. Validation

Full suite (275 PASS, `-W error`), ephemeral PostgreSQL 16 schema/view/DQ execution, deterministic reruns (impact outputs byte-identical), and a 75-check source-to-report reconciliation across all nine domains — all green.

## 11. Limitations

Simulated MES; historical imbalanced SECOM; precision target missed; modeled economics; manual `.pbix` assembly still required; latency modeled from same-lot timestamps, not observed response time.
