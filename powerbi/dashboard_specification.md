# Power BI Dashboard Specification & Visual Design Standards

Comprehensive UI/UX design and technical visual specification for the 7-page Power BI Dashboard connected to the PostgreSQL analytics warehouse.

---

## 1. Design Principles & Layout Standards

- **Grid Canvas:** Standard 16:9 widescreen canvas ($1280 \times 720 \text{ px}$) with 10 px margins and 10 px gutters.
- **Typography:** Segoe UI Semibold (Titles: 12 pt bold, Headers: 11 pt bold, KPI Card Values: 24 pt bold, Card Labels: 10 pt regular).
- **Color Palette (from `powerbi/theme.json`):**
  - Primary Accent: Navy `#1B365D`
  - Secondary Accent: Steel Blue `#2C5282`
  - Teal Highlight: `#319795`
  - Warning Gold: `#D69E2E`
  - Critical Alert / Deficit Red: `#E53E3E`
  - Background: Neutral White / Soft Slate `#F7FAFC`
- **Visual Hygiene Rules:**
  - Strict zero-gradient flat manufacturing theme.
  - Zero glassmorphism, 3D effects, or misleading dual-axes.
  - All percentages display exactly two decimal places (`0.00%`).
  - No row-level arithmetic averages for OEE.

---

## 2. Page-by-Page Technical Specifications

### Page 1: Executive Summary
- **Purpose:** High-level manufacturing health, OEE vs 85% world-class target, line/shift variance, and loss categorization.
- **Visual Components:**
  1. `v_exec_slicer_line`: Dropdown slicer binding to `dim_line[line_code]`.
  2. `v_exec_slicer_shift`: Dropdown slicer binding to `dim_time_shift[shift_code]`.
  3. `v_exec_card_oee`: KPI Card displaying `[OEE]` (74.41%), colored green if $\ge 85\%$, red if $< 85\%$.
  4. `v_exec_card_avail`: KPI Card displaying `[Availability]` (91.29%, target 90.0%).
  5. `v_exec_card_perf`: KPI Card displaying `[Performance]` (84.50%, target 95.0%).
  6. `v_exec_card_qual`: KPI Card displaying `[Quality]` (96.46%, target 98.0%).
  7. `v_exec_card_units`: KPI Card displaying `[Total Units]` (1,074,073).
  8. `v_exec_card_scrap`: KPI Card displaying `[Total Scrap Cost]` ($555,891).
  9. `v_exec_card_value`: KPI Card displaying `[Annual Recoverable Value ($)]` ($1.69M).
  10. `v_exec_trend_oee`: Line chart tracking `[OEE]` daily trend with horizontal reference line at $85\%$.
  11. `v_exec_bar_line_shift`: Clustered column chart comparing OEE across Lines 1–4 by Shifts A, B, C.
  12. `v_exec_loss_bridge`: Stacked horizontal bar chart of downtime hours by OEE category (Availability: 1,513.8h, Performance: 1,345.3h, Planned: 105.0h).
  13. `v_exec_excursion_callout`: Table highlighting active excursions and defect spikes.

---

### Page 2: OEE Decomposition
- **Purpose:** Multi-level diagnostic breakdown of Availability, Performance, and Quality losses.
- **Visual Components:**
  1. `v_oee_waterfall`: Operating time bridge: Planned Time (17,175.0h) $\rightarrow$ Availability Loss (-1,496.1h) $\rightarrow$ Performance Loss (-2,429.8h) $\rightarrow$ Quality Equivalent Loss (-470.6h) $\rightarrow$ Good Output Basis (12,778.5h).
  2. `v_oee_apq_by_line`: Grouped column chart of A, P, Q across lines (L1: 76.6%, L2: 70.9%, L3: 73.2%, L4: 76.9%).
  3. `v_oee_matrix_line_shift`: Matrix grid displaying the complete $4 \times 3$ Line $\times$ Shift matrix with conditional heatmap formatting on Performance (exposing Line 2 Shift C at 80.17%).

---

### Page 3: SPC / Early Warning Monitor
- **Purpose:** Statistical process control excursion detection, early warning latency, and detection method benchmarking.
- **Visual Components:**
  1. `v_spc_disclaimer_banner`: "High recall was achieved at the cost of a very high false-positive burden. The 60% precision target was not achieved." WE precision is 4.23%; WE+EWMA and combined precision are 4.21% (4.2% when rounded to one decimal). Combined false alerts are 95.35/100 lots. Historical backtest; zero compute/response delay assumed.
  2. `v_spc_card_latency`: `[Median Early Detection Advantage (h)]` = modeled 17.98 h versus next-day 08:00. `[Median Detection Latency (h)]` is separately 0 h; saved hours are not latency.
  3. `v_spc_card_precision`: `[Alert Precision %]` = combined 4.21%, from `pb_spc_methods`, never the 4.19% failure prevalence (46/1,097).
  4. `v_spc_card_recall`: KPI Card: `[Alert Recall %]` = 100.0% (46/46 failing lots detected).
  5. `v_spc_card_early_flag`: KPI Card: `[Excursions Caught Before Manual Report %]` = 100.0%.
  6. `v_spc_card_hours_saved`: `[Phase II Lots]` = 1,097, with 46 failures. `[Phase II Failure Prevalence %]` = 4.19% is available and labeled separately.
  7. `v_spc_control_chart`: `fact_sensor_reading` aliases `analytics.vw_spc_readings`, selected Phase II SECOM only. Plot chronological source row, one selected sensor, raw value, frozen centerline/UCL/LCL, and WE markers. Default sensor comes from frozen selection (`sensor_021`). No MetroPT reading dependency.
  8. `v_spc_methods_compare`: `pb_spc_methods.method` vs `[Failures Detected]`, filtered to WE, WE+EWMA, WE+EWMA+T2. Counts derive from the frozen report (46 per method).
  9. `v_spc_latency_dist`: `pb_spc_failures.hours_saved_bucket` vs `[Failure Lead-Time Count]`, filtered to WE+EWMA+T2 so the 46 failures are not counted once per method.

---

### Page 4: Pareto & Root Cause Analysis
- **Purpose:** 80/20 loss concentration analysis and statistical RCA evidence for injected scenarios.
- **Visual Components:**
  1. `v_pareto_scrap`: Combo bar & line Pareto chart of scrap costs by defect cause. Top 3 causes (Dimensional $173.1k, Surface Defect $137.9k, Contamination $102.4k) account for 74.38% of total scrap.
  2. `v_pareto_downtime`: Combo bar & line Pareto chart of downtime hours by stoppage reason. Top 3 reasons (Minor Stop 1,345.3h, Changeover 879.7h, Breakdown 284.0h) account for 87.75% of unplanned downtime.
  3. `v_rca_l2_night_evidence`: Clustered column chart showing Line 2 minor stop spike on Shift C (4,257 events, $2.92\times$ rate vs day shifts).
  4. `v_rca_l3_toolwear_evidence`: Defect rate line trend across 180 days on Line 3 showing progressive tool wear drift from 4.3% in H1 to 8.1% in H2 ($\chi^2 = 1,770.8, p < 10^{-16}$).
  5. `v_rca_p2_supplier_evidence`: Column chart showing Product P2 supplier material excursion (620 scrap units / $11,160 cost during mid-horizon hold).

---

### Page 5: Work Orders & Execution
- **Purpose:** Production order schedule tracking, completion rates, and throughput compliance.
- **Visual Components:**
  1. KPI cards: `[Work Orders Total]` = 720; `[WO Completion %]` = 266/720 = 36.94%; `[WO On-Time %]` = 391/720 = 54.31% (simulator flag); `[WO Planned Units]` = 1,100,094. Status: 266 complete + 454 partial. Produced quantity is 1,074,073.
  2. `v_wo_throughput_by_prod`: Product vs `[WO Planned Units]` and `[WO Produced Units]`, using the work-order grain.
  3. `v_wo_schedule_table`: `analytics.vw_work_orders` joins `dim_work_order` to `staging.mes_work_orders` by observed order ID. Show ID, order/due dates, line, product, status, planned/produced/good/scrap quantities, and source on-time flag. No completion timestamp or shift/station attribution is observed; do not join orders directly to hourly production or display order-level OEE.

Relationships: Date through order `date_key`, Line, Product; single direction.
Completion is the simulator status (produced quantity meets plan). Partial orders
can carry an on-time flag; that flag is simulated, not actual delivery evidence.

---

### Page 6: Capacity & Manpower
- **Purpose:** Workstation cycle-time balance, buffer wait times, and operator absenteeism gap analysis.
- **Visual Components:**
  1. KPI Cards: Planned Headcount (12,240), Actual Headcount (11,432), Manpower Gap (808 operator-shifts, 6.6% absence rate), Capacity Utilization (91.29%). Preserve the existing run-time/planned-time definition; it equals Availability. `[Throughput Units / Run Hour]` uses production units/run hours. These headcount sums are operator-shifts, not unique workers.
  2. `v_cap_gap_by_shift`: Absence gap by Shift with Line series (Shift A: 247, Shift B: 243, Shift C: 318 operator-shifts missed).
  3. `v_cap_bottleneck_stations`: Workstation cycle times with Line series, highlighting S3 (`Processing`) at 65.01s (vs 20s–50s on other stations).
  4. `v_cap_wait_time_trend`: Line chart of buffer queue wait time before Processing station S3.

---

### Page 7: Alerts & Data Quality Control Tower
- **Purpose:** Warehouse data integrity verification, constraint audits, and active anomaly queue.
- **Visual Components:**
  1. KPI Cards: SQL DQ Checks (65), Passed Checks (65), Violations (0), DQ Status ("100% PASS").
  2. `v_dq_assertion_matrix`: `pb_dq_checks` is a snapshot of live executed SQL/source checks. Use data-backed DQ cards. The current full warehouse has 65 checks; a serving-only warehouse has 59, with six MetroPT reading checks explicitly out of scope.
  3. `v_dq_active_alerts_table`: `fact_spc_alert` holds historical WE/EWMA/T2 diagnostic events. Open/warning are initial workflow labels, not observed factory acknowledgment or operational severity. Event counts are not alerted-lot precision denominators.

`pb_reconciliation` holds 75 artifact comparisons; the live aggregate probe and
SQL/source reconciliation are separate evidence in `reports/powerbi_readiness.json`.
Actual Power BI engine totals remain to be verified after Desktop assembly.
