# Project Facts — canonical reference

Use these exact figures in README, resume, LinkedIn, and interviews. Sources in brackets.

## DATA SCALE

- SECOM lots: 1,567 (1,463 pass / 104 fail) [secom_cleaning_summary]
- Retained sensors: 446 of 590 (28 high-null + 116 zero-variance removed) [secom_cleaning_summary]
- SECOM non-null readings: 688,014 [db_load_summary]
- MetroPT-3 observations: 1,516,948 x 15 signals = 22,754,220 readings [metropt3_ingestion_summary]
- MetroPT-3 windows: 4 failure + 4 derived 24 h pre-failure; 70,620 state periods [metropt3_ingestion_summary]
- MES rows: 17,280 production / 24,147 downtime events / 4,096 quality events / 720 work orders / 180 days / seed 42 [mes_simulation_summary, db_load_summary]

## ANALYTICS

- OEE: A 91.29% x P 84.50% x Q 96.46% = 74.41% [oee_whatif_summary, powerbi_reconciliation]
- Top-3 scrap: 74.38% ($413,447 of $555,891; dimensional, surface defect, contamination) [pareto_summary]
- Top-3 downtime (unplanned): 87.75% (2,508.99 of 2,859.13 h; minor_stop, changeover, breakdown) [pareto_summary]
- SPC backtest: 1,097 Phase II lots, 46 fails; WE recall 100%, WE precision 4.23%, combined 4.21%; median ~17.98 h / P90 ~28.44 h before next-day 08:00 baseline [spc_backtest_summary]
- RCA: L2 night-shift minor stops ~2.9x; L3 tool-wear progression; supplier-material excursion; MetroPT-3 TP2/oil-temperature contrasts [rca_statistical_summary]
- What-if 30% combined (MODELED): 74.41% -> 78.96% (+4.55 pts), +63,864 units/yr, $251,513.59 scrap/yr avoided, $1,688,452.14 total recoverable at $22.50/unit [oee_whatif_summary]

## VALIDATION

- Tests: 229 PASS, 0 skipped, `-W error` [full_validation_summary]
- DQ: 65/65 PASS, 0 violations, 0 rejected rows, 0 unresolved FKs [dq_check_summary, db_load_summary]
- Cross-system reconciliation: 75/75 PASS across 9 domains [cross_system_reconciliation_summary]
- SQL vs DAX: PASS within 0.1% (measured ~1.49e-14%) [powerbi_reconciliation_summary]
- Power BI: 36 DAX measures specified; 7 dashboard pages specified; final `.pbix` requires manual Desktop assembly (not committed) [measures.dax, dashboard_specification]

## BUSINESS OUTCOMES

Measured:
- OEE 74.41% decomposed; top-cause concentrations above; SPC 100% recall at 4.21% precision; latency reduction 100% in backtest.

Configured baseline:
- 6.0 h/week manual reporting -> <10 min/week automated target; 312.0 vs 8.7 h/year; ~303.3 h/year saved; 97.2% reduction (target, not measured production runtime).

Modeled:
- All what-if economics are projections, never realized savings.
