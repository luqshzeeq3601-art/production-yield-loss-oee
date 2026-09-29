# Power BI Measure Catalog

DAX definitions are in `measures.dax`. Import names exactly as `model_mapping.csv`.
Values below are source/evidence checks and Python emulation; actual Power BI engine execution remains for Desktop assembly.

| Measure | Home table | Format | Definition / evidence |
|---|---|---|---|
| `Planned Production Time (h)` | `fact_production_hourly` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Run Time (h)` | `fact_production_hourly` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Ideal Operating Basis (h)` | `fact_production_hourly` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Total Units` | `fact_production_hourly` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Good Units` | `fact_production_hourly` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Scrap Units` | `fact_production_hourly` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Yield %` | `fact_production_hourly` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Scrap Rate %` | `fact_production_hourly` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Availability` | `fact_production_hourly` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Performance` | `fact_production_hourly` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Quality` | `fact_production_hourly` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `OEE` | `fact_production_hourly` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `OEE Target` | `fact_production_hourly` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `OEE vs Target` | `fact_production_hourly` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `OEE Target Status` | `fact_production_hourly` | `@` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Downtime Minutes` | `fact_downtime_event` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Downtime Hours` | `fact_downtime_event` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Downtime Events` | `fact_downtime_event` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Unplanned Downtime Hours` | `fact_downtime_event` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Planned Downtime Hours` | `fact_downtime_event` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Availability Loss Hours` | `fact_production_hourly` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Performance Loss Hours` | `fact_production_hourly` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Quality Equivalent Loss Hours` | `fact_production_hourly` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Total Scrap Cost` | `fact_quality_scrap` | `$#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Top 3 Scrap Cost` | `fact_quality_scrap` | `$#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Top 3 Scrap Cost Share` | `fact_quality_scrap` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Scrap Cost All Causes` | `fact_quality_scrap` | `$#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Cum Scrap Cost` | `fact_quality_scrap` | `$#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Cum % Scrap Cost` | `fact_quality_scrap` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Downtime All Reasons` | `fact_downtime_event` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Cum Downtime Hours` | `fact_downtime_event` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Cum % Downtime` | `fact_downtime_event` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Planned Headcount` | `fact_manpower_shift` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Actual Headcount` | `fact_manpower_shift` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Manpower Gap` | `fact_manpower_shift` | `#,##0.00` | Planned minus actual operator-shifts: 12240 - 11432 = 808; not unique workers. |
| `Capacity Utilization %` | `fact_production_hourly` | `0.00%` | Existing definition preserved: run/planned, equal to Availability (91.29%). |
| `Average Processing Time (s)` | `fact_station_operation` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Average Wait Time (s)` | `fact_station_operation` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Bottleneck Processing Time (s)` | `fact_station_operation` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Alerts Total` | `fact_spc_alert` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Alerts Open` | `fact_spc_alert` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Alerts Critical` | `fact_spc_alert` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Median Detection Latency (h)` | `pb_spc_methods` | `#,##0.00` | Modeled same-lot detection latency: 0 h. Zero compute/response delay assumed. |
| `Median Early Detection Advantage (h)` | `pb_spc_methods` | `#,##0.00` | Modeled lead vs next-day 08:00: 17.9833 h; not detection latency. |
| `WE Precision %` | `pb_spc_methods` | `0.00%` | TP/(TP+FP), WE only: 46/(46+1041) = 4.23%. |
| `WE EWMA Precision %` | `pb_spc_methods` | `0.00%` | WE+EWMA only: 46/(46+1046) = 4.21%. |
| `Combined Precision %` | `pb_spc_methods` | `0.00%` | WE+EWMA+T2: 4.21%; benchmark table, disconnected from MES filters. |
| `Alert Precision %` | `pb_spc_methods` | `0.00%` | Alias of Combined Precision %, never failure prevalence. |
| `Alert Recall %` | `pb_spc_methods` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Excursions Caught Before Manual Report %` | `pb_spc_methods` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Phase II Lots` | `pb_spc_lots` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Phase II Failures` | `pb_spc_lots` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Phase II Failure Prevalence %` | `pb_spc_lots` | `0.00%` | 46/1097 = 4.19%; class prevalence, not precision. |
| `Combined False Alerts / 100 Lots` | `pb_spc_methods` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Failures Detected` | `pb_spc_methods` | `#,##0` | TP in single-method context; blank grand total prevents double counting methods. |
| `Failure Lead-Time Count` | `pb_spc_failures` | `#,##0` | Filter method to WE+EWMA+T2 for the 46-failure histogram. |
| `SPC Reading Value` | `fact_sensor_reading` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `SPC Centerline` | `fact_sensor_reading` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `SPC UCL` | `fact_sensor_reading` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `SPC LCL` | `fact_sensor_reading` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `SPC Violation Value` | `fact_sensor_reading` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Manual Baseline Hours / Week` | `pb_impact_metrics` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Automated Pipeline Hours / Week` | `pb_impact_metrics` | `#,##0.00` | RA-003/60: ten-minute target, not measured full production runtime. |
| `Annual Analyst Hours Saved` | `pb_impact_metrics` | `#,##0.00` | RA-006: 303.3 h/year, configured automation target, not observed runtime. |
| `Annual Recoverable Value ($)` | `pb_impact_metrics` | `$#,##0.00` | WIF-006: $1,688,452.14 MODELED scenario, not realized savings. |
| `Work Orders Total` | `vw_work_orders` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Completed Work Orders` | `vw_work_orders` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Partial Work Orders` | `vw_work_orders` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `WO Completion %` | `vw_work_orders` | `0.00%` | 266 complete / 720 = 36.94%; status is produced_qty >= planned_qty. |
| `WO On-Time %` | `vw_work_orders` | `0.00%` | 391 source on_time flags / 720 = 54.31%; simulated flag, no observed completion date. |
| `WO Planned Units` | `vw_work_orders` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `WO Produced Units` | `vw_work_orders` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `WO Good Units` | `vw_work_orders` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `WO Scrap Units` | `vw_work_orders` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Throughput Units / Run Hour` | `fact_production_hourly` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `DQ Checks Total` | `pb_dq_checks` | `#,##0` | Live DQ snapshot: 65 full-profile checks or 59 serving checks; six reading-dependent checks explicitly excluded in serving. |
| `DQ Checks Passed` | `pb_dq_checks` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `DQ Violations` | `pb_dq_checks` | `#,##0` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `DQ Pass %` | `pb_dq_checks` | `0.00%` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `DQ Status` | `pb_dq_checks` | `@` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `Reconciliation Pass %` | `pb_reconciliation` | `0.00%` | 75/75 artifact comparisons; supplemental live aggregate probe is separate. |
| `Ideal Good Output Basis (h)` | `fact_production_hourly` | `#,##0.00` | From additive source components or the linked evidence snapshot; see exact DAX definition. |
| `OEE Bridge Hours` | `pb_oee_bridge` | `#,##0.00` | Physical five-step time bridge; mark Planned and Good Output as waterfall totals. |

## Model boundaries

- Work orders relate to Date (order date), Line, Product only. No shift, station, completion-date, or hourly-order attribution is observed.
- SPC benchmark/lot/failure tables are disconnected from the MES calendar. Frozen limits relate to Sensor; the reading view imports only selected Phase II SECOM sensors.
- Impact, DQ, reconciliation, and bridge tables are disconnected snapshots. Show their evidence labels and profile; do not synchronize MES slicers onto SPC benchmark cards.
- Alert event counts differ from alerted-lot precision denominators. Open/warning are initial diagnostic workflow labels, not measured operational severity or acknowledgment.
- High recall was achieved at the cost of a very high false-positive burden. The 60% precision target was not achieved.
