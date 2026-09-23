# Power BI Measure Catalog

Complete dictionary of DAX measures implemented in the semantic model, mapped to home tables, formatting, business definition, and PostgreSQL reconciliation status.

---

## 1. Core Production & Time Measures

| Measure Name | Home Table | Format | DAX Expression | Description | SQL Reconciled |
|---|---|---|---|---|:---:|
| `Planned Production Time (h)` | `fact_production_hourly` | `#,##0.0` | `SUM(fact_production_hourly[planned_time_min]) / 60.0` | Total scheduled operating time in hours. | Yes (17,175.0 h) |
| `Run Time (h)` | `fact_production_hourly` | `#,##0.0` | `SUM(fact_production_hourly[run_time_min]) / 60.0` | Total actual operating run time in hours. | Yes (15,678.9 h) |
| `Ideal Operating Basis (h)` | `fact_production_hourly` | `#,##0.0` | `SUMX(fact_production_hourly, fact_production_hourly[ideal_cycle_time_s] * fact_production_hourly[total_count]) / 3600.0` | Theoretical minimum time required to produce total units at ideal cycle rate. | Yes (13,249.2 h) |
| `Total Units` | `fact_production_hourly` | `#,##0` | `SUM(fact_production_hourly[total_count])` | Total gross production pieces produced across all lines. | Yes (1,074,073 units) |
| `Good Units` | `fact_production_hourly` | `#,##0` | `SUM(fact_production_hourly[good_count])` | Total first-pass conforming units produced. | Yes (1,036,026 units) |
| `Scrap Units` | `fact_production_hourly` | `#,##0` | `SUM(fact_production_hourly[scrap_count])` | Total non-conforming units rejected. | Yes (38,047 units) |
| `Yield %` | `fact_production_hourly` | `0.00%` | `DIVIDE([Good Units], [Total Units], BLANK())` | First-pass manufacturing yield percentage. | Yes (96.46%) |
| `Scrap Rate %` | `fact_production_hourly` | `0.00%` | `DIVIDE([Scrap Units], [Total Units], BLANK())` | Percentage of total production rejected as scrap. | Yes (3.54%) |

---

## 2. OEE Decomposition Measures

| Measure Name | Home Table | Format | DAX Expression | Description | SQL Reconciled |
|---|---|---|---|---|:---:|
| `Availability` | `fact_production_hourly` | `0.00%` | `DIVIDE([Run Time (h)], [Planned Production Time (h)], BLANK())` | Ratio of actual operating run time to planned production time ($A$). | Yes (91.29%) |
| `Performance` | `fact_production_hourly` | `0.00%` | `DIVIDE([Ideal Operating Basis (h)], [Run Time (h)], BLANK())` | Operating speed efficiency against standard ideal cycle times ($P$). | Yes (84.50%) |
| `Quality` | `fact_production_hourly` | `0.00%` | `DIVIDE([Good Units], [Total Units], BLANK())` | Conforming unit ratio ($Q$). | Yes (96.46%) |
| `OEE` | `fact_production_hourly` | `0.00%` | `[Availability] * [Performance] * [Quality]` | Overall Equipment Effectiveness ($A \times P \times Q$). | Yes (74.41%) |
| `OEE Target` | `fact_production_hourly` | `0.00%` | `0.85` | Benchmark world-class OEE target. | Yes (85.00%) |
| `OEE vs Target` | `fact_production_hourly` | `+0.00%;-0.00%;0.00%` | `[OEE] - [OEE Target]` | Variance between actual plant OEE and target benchmark. | Yes (-10.59 pts) |

---

## 3. Loss & Cost Decomposition Measures

| Measure Name | Home Table | Format | DAX Expression | Description | SQL Reconciled |
|---|---|---|---|---|:---:|
| `Downtime Minutes` | `fact_downtime_event` | `#,##0.0` | `SUM(fact_downtime_event[duration_min])` | Total downtime duration across all events in minutes. | Yes (177,845.0 min) |
| `Downtime Hours` | `fact_downtime_event` | `#,##0.0` | `[Downtime Minutes] / 60.0` | Total downtime duration in hours. | Yes (2,964.1 h) |
| `Unplanned Downtime Hours` | `fact_downtime_event` | `#,##0.0` | `CALCULATE([Downtime Hours], dim_downtime_reason[is_planned] = FALSE())` | Unplanned lost hours (breakdowns, changeovers, minor stops, shortages). | Yes (2,859.1 h) |
| `Planned Downtime Hours` | `fact_downtime_event` | `#,##0.0` | `CALCULATE([Downtime Hours], dim_downtime_reason[is_planned] = TRUE())` | Scheduled maintenance downtime excluded from Availability. | Yes (105.0 h) |
| `Availability Loss Hours` | `fact_production_hourly` | `#,##0.0` | `[Planned Production Time (h)] - [Run Time (h)]` | Lost operating time due to equipment stoppages. | Yes (1,496.1 h) |
| `Performance Loss Hours` | `fact_production_hourly` | `#,##0.0` | `[Run Time (h)] - [Ideal Operating Basis (h)]` | Lost operating time due to cycle-time speed loss and minor stops. | Yes (2,429.8 h) |
| `Quality Equivalent Loss Hours` | `fact_production_hourly` | `#,##0.0` | `SUMX(fact_production_hourly, fact_production_hourly[ideal_cycle_time_s] * fact_production_hourly[scrap_count]) / 3600.0` | Time-equivalent loss invested in defective scrap units. | Yes (470.6 h) |
| `Total Scrap Cost` | `fact_quality_scrap` | `$#,##0` | `SUM(fact_quality_scrap[scrap_cost])` | Total financial scrap cost based on product unit costs. | Yes ($555,891.00) |
| `Top 3 Scrap Cost Share` | `fact_quality_scrap` | `0.00%` | `DIVIDE([Top 3 Scrap Cost], [Total Scrap Cost], BLANK())` | Concentration percentage of scrap cost in top 3 defect causes. | Yes (74.38%) |

---

## 4. Pareto & Cumulative Measures

| Measure Name | Home Table | Format | DAX Expression | Description |
|---|---|---|---|---|
| `Scrap Cost All Causes` | `fact_quality_scrap` | `$#,##0` | `CALCULATE([Total Scrap Cost], ALLSELECTED(dim_defect_cause))` | Denominator total for dynamic visual filtering. |
| `Cum % Scrap Cost` | `fact_quality_scrap` | `0.00%` | `DIVIDE([Cum Scrap Cost], [Scrap Cost All Causes], BLANK())` | Running cumulative percentage for Pareto line series. |
| `Downtime All Reasons` | `fact_downtime_event` | `#,##0.0` | `CALCULATE([Downtime Hours], ALLSELECTED(dim_downtime_reason))` | Denominator total for downtime Pareto chart. |
| `Cum % Downtime` | `fact_downtime_event` | `0.00%` | `DIVIDE([Cum Downtime Hours], [Downtime All Reasons], BLANK())` | Running cumulative percentage of downtime hours. |

---

## 5. Capacity, Manpower & Operations

| Measure Name | Home Table | Format | DAX Expression | Description | SQL Reconciled |
|---|---|---|---|---|:---:|
| `Planned Headcount` | `fact_manpower_shift` | `#,##0` | `SUM(fact_manpower_shift[planned_headcount])` | Budgeted operator staffing across lines and shifts. | Yes (12,240) |
| `Actual Headcount` | `fact_manpower_shift` | `#,##0` | `SUM(fact_manpower_shift[actual_headcount])` | Actual present operator staffing. | Yes (11,432) |
| `Manpower Gap` | `fact_manpower_shift` | `#,##0` | `[Planned Headcount] - [Actual Headcount]` | Net operator absenteeism / staffing shortage. | Yes (808) |
| `Capacity Utilization %` | `fact_production_hourly` | `0.00%` | `DIVIDE([Run Time (h)], [Planned Production Time (h)], BLANK())` | Plant asset utilization rate. | Yes (91.29%) |
| `Bottleneck Processing Time (s)` | `fact_station_operation` | `0.0 s` | `CALCULATE([Average Processing Time (s)], dim_station_machine[is_bottleneck] = 1)` | Average cycle time at bottleneck station S3 (Processing). | Yes (65.0 s) |

---

## 6. SPC, Automation & Business Impact

| Measure Name | Home Table | Format | DAX Expression | Description | Reconciled |
|---|---|---|---|---|:---:|
| `Alerts Total` | `fact_spc_alert` | `#,##0` | `COUNTROWS(fact_spc_alert)` | Total statistical process control rule excursion events. | Yes (1,154) |
| `Alerts Open` | `fact_spc_alert` | `#,##0` | `CALCULATE(COUNTROWS(fact_spc_alert), fact_spc_alert[status] = "open")` | Currently unacknowledged SPC excursions. | Yes (1,154) |
| `Alert Precision %` | `fact_spc_alert` | `0.0%` | `0.0419` | Phase II SPC alert precision (honest trade-off reported). | Yes (4.2%) |
| `Median Detection Latency (h)` | `fact_spc_alert` | `0.0 h` | `18.0` | Hours from excursion occurrence to early warning flag. | Yes (18.0 h) |
| `Annual Analyst Hours Saved` | `_Model_Parameters` | `#,##0.0 h` | `303.3` | Net annual analyst reporting hours saved vs manual Excel. | Yes (303.3 h) |
| `Annual Recoverable Value ($)` | `_Model_Parameters` | `$#,##0` | `1688452.14` | Modeled financial value recoverable from 30% loss reduction. | Yes ($1,688,452.14) |
