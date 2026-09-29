# Power BI Desktop Assembly & Deployment Guide

This guide provides the exact sequence of steps to assemble and connect the Power BI report using the semantic layer and theme artifacts in this repository.

---

## 1. Prerequisites & Environment Setup

- **Software:** Microsoft Power BI Desktop; assembly begins in the next task.
- **Database:** Persistent PostgreSQL 16.15 at `127.0.0.1:5432/production_yield_oee`, user `powerbi_local`.
- **Theme:** `powerbi/theme.json` located in the repository.
- **Measures Library:** `powerbi/measures.dax`.

From the repository root, start the existing cluster and run the live gate:

```powershell
py -3.11 -m scripts.bootstrap_powerbi_db start
py -3.11 -m scripts.bootstrap_powerbi_db check --full-analytics
```

The vendor binaries are in `.local/postgresql16/pgsql/`; the persistent data
directory is `.local/pgdata/`. `pg_ctl` starts a background server independently
of Python and the test servers. It stays running after the helper exits. After
a reboot, run `start` again; data persists. This is a manually started instance,
not an automatically installed Windows service.

Database authentication uses SCRAM-SHA-256. The helper explicitly reads the
ignored local `.env`; process environment takes priority. The current setup
uses `POSTGRES_HOST/PORT/DB/USER/PASSWORD`, with no `DATABASE_URL` override.
Never copy passwords into committed files or chat. Full installation steps,
the complete relation inventory, and troubleshooting are in
`powerbi_connection_checklist.md`.

The serving path is `py -3.11 -m scripts.bootstrap_powerbi_db prepare`.
It omits MetroPT reading-level data and runs 59 scoped DQ checks, explicitly
excluding six reading-dependent checks. MES, cleaned SECOM, compact MetroPT
interval/state evidence for DQ, and frozen reports are required. No dashboard
imports MetroPT readings. The optional `--full-analytics` profile additionally
requires the real processed file and runs all 65 DQ checks. This machine was
prepared with that full profile because the file was available. The default
analytical loader/pipeline still require all sources, unchanged.

Repeated serving loads support the same source snapshot. The original loader
uses `ON CONFLICT DO NOTHING` for fact natural keys; changed source data needs
a deliberate analytical refresh. Evidence snapshots are replaced transactionally,
and historical diagnostic alerts reset to initial open status on serving refresh.

---

## 2. Step-by-Step Power BI Desktop Connection

1. **Open Power BI Desktop** $\rightarrow$ Click **Get Data** $\rightarrow$ Select **PostgreSQL database**.
2. **Connection Parameters:**
   - **Server:** `127.0.0.1:5432`.
   - **Database:** `production_yield_oee`.
   - **Data Connectivity Mode:** Select **Import** for this reproducible snapshot and offline report use. DirectQuery requires the local server to remain running and adds query latency.
   - **Authentication:** Database username/password; user `powerbi_local`, password from the local `.env`, entered directly in Desktop.
3. **Select Analytics Schema Objects:**
   Select all 25 `schema_source` relations in `powerbi/model_mapping.csv`, including:
   - `analytics.vw_powerbi_date` (rename query to `dim_date`)
   - `analytics.dim_line`
   - `analytics.dim_time_shift`
   - `analytics.dim_station_machine`
   - `analytics.dim_product`
   - `analytics.dim_downtime_reason`
   - `analytics.dim_defect_cause`
   - `analytics.dim_sensor`
   - `analytics.fact_production_hourly`
   - `analytics.fact_downtime_event`
   - `analytics.fact_quality_scrap`
   - `analytics.fact_manpower_shift`
   - `analytics.fact_station_operation`
   - `analytics.fact_spc_alert`
   - `analytics.vw_spc_readings` (rename query to `fact_sensor_reading`)
   - `analytics.fact_quality_lot`
   - `analytics.vw_work_orders`
   - `analytics.pb_spc_methods`, `analytics.pb_spc_lots`, `analytics.pb_spc_failures`, `analytics.pb_spc_limits`
   - `analytics.pb_impact_metrics`, `analytics.pb_dq_checks`, `analytics.pb_reconciliation`, `analytics.pb_oee_bridge`
4. **Transform Data**: use exact `table_name` aliases, integer keys, decimal components, Date-only `full_date`, Boolean flags, and DateTime timestamps; then **Close & Apply**.

Modern Desktop includes its PostgreSQL provider; consult
[Microsoft's connector documentation](https://learn.microsoft.com/en-us/power-query/connectors/postgresql)
for older versions. The loopback instance has no provisioned TLS; accept an
unencrypted connection if prompted. `staging` is an internal load schema and
is not imported.

---

## 3. Configure Model Relationships

Navigate to **Model View** $\rightarrow$ Confirm the Star Schema relationships:
- All relationships must be **Single Direction (`1:*`)** from dimension tables to fact tables.
- Right-click `dim_date` $\rightarrow$ Select **Mark as Date Table** $\rightarrow$ Choose `full_date` column.

- The date view is continuous across historical source dates and order due dates.
- `vw_work_orders` relates to Date via `date_key` (order date), Line via `line_key`,
  Product via `product_key`. Due date remains a detail field. No completion
  timestamp, shift/station assignment, or order-to-hour linkage is observed.
- Keep SPC method/lot/failure benchmarks disconnected from the MES calendar:
  SECOM is from 2008; MES is from 2024. Do not synchronize MES slicers onto SPC cards.
- `pb_spc_limits` and the reading view relate to `dim_sensor` via `sensor_key`.
  The view imports selected Phase II SECOM sensors and frozen limits only.
- SPC report `source_row` is zero-based; raw warehouse identities are one-based.
  The reading view translates explicitly; do not infer a relationship to the
  original `fact_quality_lot[source_row]`.
- Impact, DQ, reconciliation, and OEE bridge helpers stay disconnected. Sort
  bridge steps by `step_order`; mark Planned and Good Output as waterfall totals.
  Raw downtime event durations are diagnostics, not an additive OEE bridge.

---

## 4. Import Theme & Create DAX Measures

1. In the **View** ribbon $\rightarrow$ Click **Themes** dropdown $\rightarrow$ Click **Browse for themes** $\rightarrow$ Select `powerbi/theme.json`.
2. Open `powerbi/measures.dax` $\rightarrow$ Copy each measure and create it under its corresponding Home Table as cataloged in `powerbi/measure_catalog.md`.

---

## 5. Build Dashboard Pages (Pages 1 to 7)

Follow `powerbi/dashboard_specification.md` and `powerbi/visual_mapping.json` for visual placement, coordinates, formatting, and data bindings across:
- **Page 1:** Executive Summary
- **Page 2:** OEE Decomposition
- **Page 3:** SPC / Early Warning
- **Page 4:** Pareto + RCA
- **Page 5:** Work Orders
- **Page 6:** Capacity + Manpower
- **Page 7:** Alerts + Data Quality

Save the completed report as `powerbi/OEE_EarlyWarning.pbix`.

This save/build step belongs to the next assembly task. The preparation helper
does not open Desktop or create a PBIX.

## 6. Evidence and post-import validation

Clear slicers and compare actual Desktop cards to the live SQL warehouse within
0.1%. Preparation validates live SQL/source totals and Python emulation of DAX;
actual Power BI engine execution remains unverified until assembly.

| KPI | Expected |
|---|---:|
| Total / Good / Scrap Units | 1,074,073 / 1,036,026 / 38,047 |
| Planned / Run Time (min) | 1,030,502.584 / 940,735.318 |
| Availability / Performance / Quality / OEE | 91.29% / 84.50% / 96.46% / 74.41% |
| Scrap Cost | $555,891.00 |
| Unplanned Downtime | 171,547.551 min / 2,859.13 h |
| Work Orders / Complete / Partial | 720 / 266 / 454 |
| WO Completion / Simulated On-Time Flag Rate | 36.94% / 54.31% (391 flagged) |
| Planned / Actual Manpower / Gap | 12,240 / 11,432 / 808 operator-shifts |
| Current full-warehouse DQ | 65/65 PASS, zero violations |
| Artifact reconciliation | 75/75 PASS; live aggregate probe is supplemental |

SPC has 1,097 Phase II lots, 46 failures, 4.19% **failure prevalence**, WE
precision 4.23%, WE+EWMA/combined precision 4.21%, and recall 100%. Combined
false alerts are 95.35 per 100 lots. The 17.98 h value is a **modeled median
early-detection advantage**, while modeled same-lot detection latency is 0 h
(zero compute/response delay assumed). High recall was achieved at the cost of
a very high false-positive burden. The 60% precision target was not achieved.

Apply every visual filter from `visual_mapping.json`. Plot one sensor at a time,
using chronological source-row index, raw value, frozen control limits, and WE
markers. Filter the lead-time histogram to one method to avoid counting failures
repeatedly. The alert log is historical diagnostics: open/warning are initial
workflow labels, not observed factory acknowledgment or operational severity.
Show MODELED/CONFIGURED_BASELINE caveats for recovery and reporting targets.
Capacity Utilization retains run/planned; headcount sums count operator-shifts.

Current live evidence and the seven-page readiness matrix are generated in
`reports/powerbi_readiness.json`. Stop the owned cluster with the helper's `stop` action.
