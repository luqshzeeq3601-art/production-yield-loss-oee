# Seven-Page Data Readiness

The live gate resolves all mapped relations, model keys, DAX columns, measures,
and visual fields. Current execution evidence is `reports/powerbi_readiness.json`.
READY means data/model prerequisites for assembly; actual Desktop rendering and
Power BI-engine reconciliation remain for the next task.

| Page | Status | Source data | Warehouse/model relations | Dimensions | Main measures |
|---|---|---|---|---|---|
| 1. Executive Summary | READY | MES production, downtime, scrap; impact report | `fact_production_hourly`, `fact_downtime_event`, `fact_quality_scrap`, `pb_impact_metrics` | Date, Line, Shift, Product, Reason, Cause | A/P/Q/OEE, Units, Scrap Cost, MODELED Recovery Value |
| 2. OEE Decomposition | READY | MES production components | `fact_production_hourly`, `pb_oee_bridge`; SQL `vw_oee_plant` | Date, Line, Shift, Product | A/P/Q/OEE, OEE Bridge Hours |
| 3. SPC Monitor | READY | Cleaned SECOM; frozen limits, violations, methods, lots, failure timings | `vw_spc_readings` → `fact_sensor_reading`, `pb_spc_limits`, `pb_spc_methods`, `pb_spc_lots`, `pb_spc_failures` | Sensor; benchmark tables disconnected from MES | WE/WE+EWMA/combined precision, recall, Phase II counts/prevalence, limits, modeled lead time |
| 4. Pareto & RCA | READY | MES downtime, production, scrap; documented RCA filters | `fact_downtime_event`, `fact_production_hourly`, `fact_quality_scrap`; existing Pareto SQL views | Date, Line, Shift, Product, Reason, Cause | Scrap Cost, Cum % Scrap, Downtime, Cum % Downtime, Scrap Rate |
| 5. Work Orders | READY | `mes_work_orders.csv` | `staging.mes_work_orders` + `dim_work_order` → `vw_work_orders` | Date (order date), Line, Product | Total, Complete, Partial, Completion %, On-Time %, Planned/Produced/Good/Scrap Units |
| 6. Capacity & Manpower | READY | MES production, manpower, station operations | `fact_production_hourly`, `fact_manpower_shift`, `fact_station_operation` | Date, Line, Shift, Station | Run/Planned Capacity %, Throughput, Planned/Actual Headcount, Gap, Processing/Wait Time |
| 7. Alerts & Data Quality | READY | Frozen diagnostic violations; live DQ snapshot; reconciliation artifacts | `fact_spc_alert`, `pb_dq_checks`, `pb_reconciliation` | Sensor; check tables disconnected | Alerts, DQ Count/Passed/Violations/Status, Artifact Reconciliation Pass % |

## Assembly boundaries

- All 25 import relations are listed in `model_mapping.csv`. `dim_date` aliases
  the continuous calendar view. SPC reading import is restricted to selected
  Phase II SECOM sensors; no page requires MetroPT reading-level data.
- Compact MetroPT intervals/state periods support warehouse DQ. Serving-only
  DQ has 59 checks with six reading-dependent exclusions; the current full
  warehouse has 65/65 PASS. The analytical pipeline still requires all sources.
- SPC: prevalence 4.19%; WE precision 4.23%; WE+EWMA/combined precision 4.21%;
  recall 100%; 95.35 false alerts/100 lots; modeled median advantage 17.98 h.
  High recall was achieved at the cost of a very high false-positive burden.
  The 60% precision target was not achieved.
- Work Orders: 720 = 266 complete + 454 partial; completion 36.94%.
  The source on-time flag is simulated (391/720 = 54.31%). No actual completion
  date, station/shift allocation, or order-level OEE is available.
- Capacity is the existing run/planned definition. Staffing totals are summed
  operator-shifts. Line and shift comparisons use the conformed dimensions.
- Diagnostic alert workflow labels are initial states. Reconciliation has 75
  artifact comparisons plus a separate live SQL probe. Economic recovery and
  reporting savings retain their modeled/configured labels.
