# Power BI Semantic Model & Star Schema Architecture

## 1. Overview & Architecture

The Power BI analytical layer connects to the persistent PostgreSQL 16.15 warehouse at `127.0.0.1:5432/production_yield_oee`. `powerbi/model_mapping.csv` is the exact 25-relation import contract; all facts retain their original grain and single-direction dimension filters. `dim_date` imports the continuous `vw_powerbi_date`; `fact_sensor_reading` imports selected Phase II SECOM data from `vw_spc_readings`, excluding MetroPT readings. See the connection checklist for startup/authentication.

Work Orders use `analytics.vw_work_orders`, linked to Date (order date), Line,
Product. Source status is 266 complete and 454 partial of 720; completion 36.94%.
The simulated on-time flag is 391/720 (54.31%), with no observed completion
timestamp or station/shift assignment. SPC benchmarks, impact, DQ, reconciliation,
and bridge helpers are disconnected evidence tables; preserve their caveats and
do not apply 2024 MES filters to 2008 SPC benchmarks. Model column/measure/page
dependencies are checked live by `src/powerbi_serving.py`; actual Power BI engine
reconciliation remains for Desktop assembly.

```
                  +----------------------+
                  |       dim_date       |
                  | (date_key, full_date)|
                  +----------+-----------+
                             | 1
                             |
                             | *
+-------------------+        |        +---------------------+
|     dim_line      +--------+--------+  dim_time_shift     |
| (line_key)        |                 | (shift_key)         |
+---------+---------+                 +----------+----------+
          | 1                                    | 1
          |                                      |
          | *                                  * |
+---------+--------------------------------------+----------+
|                     fact_production_hourly                |
| (planned_min, run_min, ideal_s, actual_s, total, good, sc)|
+-----------------------------+-----------------------------+
                              | *
                              |
                              | 1
                  +-----------+----------+
                  |     dim_product      |
                  | (product_key, cost)  |
                  +----------------------+
```

---

## 2. Dimension Tables (Conformance & Grain)

1. **`dim_date`**: Calendar date dimension marked as the official date table in Power BI.
   - Grain: One record per calendar day across all source date ranges and work-order due dates; the serving view fills calendar gaps for Power BI's marked date table.
   - Surrogate Key: `date_key` (Format: `YYYYMMDD` integer).
   - Attributes: `full_date`, `year`, `quarter`, `month`, `month_name`, `week`, `day`, `day_of_week`, `is_weekend`.

2. **`dim_line`**: Manufacturing production line dimension.
   - Grain: One record per production line (`L1`, `L2`, `L3`, `L4`).
   - Surrogate Key: `line_key`.

3. **`dim_time_shift`**: 8-hour shift dimension.
   - Grain: One record per shift (`Shift A`: 06:00–14:00, `Shift B`: 14:00–22:00, `Shift C`: 22:00–06:00).
   - Surrogate Key: `shift_key`.

4. **`dim_station_machine`**: Station and equipment dimension.
   - Grain: Station per line (`L1-S1` Loading through `L4-S5` Packing).
   - Key Attributes: `is_bottleneck` flag identifying Station S3 (Processing).

5. **`dim_product`**: Product catalog dimension.
   - Grain: Manufactured part number (`P1`, `P2`, `P3`, `P4`).
   - Attributes: `ideal_cycle_time_s` (40s, 55s, 75s, 30s), `unit_scrap_cost` ($12, $18, $25, $8).

6. **`dim_downtime_reason`**: Downtime categorization hierarchy.
   - Grain: Stoppage reason (`breakdown`, `changeover`, `minor_stop`, `material_shortage`, `quality_hold`, `planned_maintenance`).
   - Attributes: `oee_bucket` (`Availability`, `Performance`, `Planned`), `is_planned` boolean.

7. **`dim_defect_cause`**: Scrap defect cause dimension.
   - Grain: Defect taxonomy (`dimensional`, `surface defect`, `contamination`, `tool wear`, `supplier material`, `other`).

8. **`dim_sensor`**: Physical sensor dimension across SECOM and MetroPT-3.
   - Grain: Observed sensor identifier: 446 retained SECOM codes (`sensor_000` through the source's `sensor_589`) plus 15 lowercase MetroPT signal codes (`tp2`, `oil_temperature`, etc.). No USL/LSL or measured criticality is fabricated.

---

## 3. Fact Tables & Grain Specification

| Fact Table | Natural Grain | Primary Metrics | Row Count |
|---|---|---|:---:|
| `fact_production_hourly` | `line x shift x date x hour` | `planned_time_min`, `run_time_min`, `total_count`, `good_count`, `scrap_count` | 17,280 |
| `fact_downtime_event` | `event_id` | `duration_min`, `supplier_tag` | 24,147 |
| `fact_quality_scrap` | `line x date x product x cause` | `units_affected`, `scrap_cost` | 4,096 |
| `fact_quality_lot` | `SECOM lot (source_row)` | `target` (0/1), `target_label` (pass/fail) | 1,567 |
| `fact_manpower_shift` | `line x shift x date` | `planned_headcount`, `actual_headcount` | 2,160 |
| `fact_station_operation` | `line x station x shift x date` | `processing_time_s`, `wait_time_s`, `throughput_units` | 10,800 |
| `fact_spc_alert` | `spc_alert_key` | `statistic_value`, `control_limit_ucl`, `control_limit_lcl`, `severity`, `status` | 7,081 historical diagnostic events |
| `fact_sensor_reading` (alias of `vw_spc_readings`) | `sensor x Phase II SECOM row` | `reading_value`, `reading_ts`, frozen `centerline`, `ucl`, `lcl`, WE marker | 10,756 imported readings; full warehouse remains 23,442,234 |

---

## 4. Relationship Cardinality & Filter Direction

All model relationships are strictly **Single Direction (`1:*`)** from dimension primary keys to fact foreign keys. This prevents circular dependency paths and unintended cross-filtering ambiguity.

- `dim_date[date_key] (1) ---> (*) fact_production_hourly[date_key]`
- `dim_line[line_key] (1) ---> (*) fact_production_hourly[line_key]`
- `dim_time_shift[shift_key] (1) ---> (*) fact_production_hourly[shift_key]`
- `dim_product[product_key] (1) ---> (*) fact_production_hourly[product_key]`
- `dim_downtime_reason[downtime_reason_key] (1) ---> (*) fact_downtime_event[downtime_reason_key]`
- `dim_station_machine[station_machine_key] (1) ---> (*) fact_downtime_event[station_machine_key]`
- `dim_defect_cause[defect_cause_key] (1) ---> (*) fact_quality_scrap[defect_cause_key]`
- `dim_sensor[sensor_key] (1) ---> (*) fact_spc_alert[sensor_key]`

---

## 5. SQL vs DAX Reconciliation Protocol

All DAX aggregations are mathematically identical to their SQL view counterparts:
- **Availability**: $\sum \text{run\_time} / \sum \text{planned\_time}$
- **Performance**: $\sum(\text{ideal\_s} \times \text{total}) / (60 \times \sum \text{run\_min})$
- **Quality**: $\sum \text{good\_count} / \sum \text{total\_count}$
- **OEE**: $A \times P \times Q$

Source/component formula emulation reconciles within 0.1%; the committed
artifact records a maximum relative difference of approximately 1.49e-14%.
The preparation gate also queries live SQL aggregates. Actual Power BI-engine
execution and Desktop headline reconciliation remain for the assembly task.
