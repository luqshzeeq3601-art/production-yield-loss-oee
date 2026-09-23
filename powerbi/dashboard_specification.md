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
  1. `v_spc_disclaimer_banner`: Text box stating honest portfolio trade-off: *"Excursion detection latency reduced by 70.4% (-18.0h earlier detection). Alert precision is 4.2% (95.8 false alarms per 100 lots trade-off; 60% precision target not achieved with broad univariate rules)."*
  2. `v_spc_card_latency`: KPI Card: `[Median Detection Latency (h)]` = 18.0 h.
  3. `v_spc_card_precision`: KPI Card: `[Alert Precision %]` = 4.2%.
  4. `v_spc_card_recall`: KPI Card: `[Alert Recall %]` = 100.0% (46/46 failing lots detected).
  5. `v_spc_card_early_flag`: KPI Card: `[Excursions Caught Before Manual Report %]` = 100.0%.
  6. `v_spc_card_hours_saved`: KPI Card: `[Annual Analyst Hours Saved]` = 303.3 h/yr.
  7. `v_spc_control_chart`: Time-series line chart with Phase I control limits (UCL / LCL) and out-of-control rule violation markers.
  8. `v_spc_methods_compare`: Bar chart comparing failing lots caught: Western Electric (46) vs WE+EWMA (46) vs WE+EWMA+T² (46).
  9. `v_spc_latency_dist`: Histogram of early warning lead-time distribution (median 18.0h, max 32.5h).

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
  1. KPI Cards: Total Work Orders (720), Completion Rate (100.0%), Total Scheduled Hours (5,760h), Ordered Units (1,074,073).
  2. `v_wo_throughput_by_prod`: Bar chart of throughput units vs standard cycle time across products P1–P4.
  3. `v_wo_schedule_table`: Tabular drill-down of all 720 work orders with planned vs actual output and OEE performance.

---

### Page 6: Capacity & Manpower
- **Purpose:** Workstation cycle-time balance, buffer wait times, and operator absenteeism gap analysis.
- **Visual Components:**
  1. KPI Cards: Planned Headcount (12,240), Actual Headcount (11,432), Manpower Gap (808 shifts, 6.6% absence rate), Capacity Utilization (91.29%).
  2. `v_cap_gap_by_shift`: Absence gap distribution (Shift A: 247, Shift B: 243, Shift C: 318 shifts missed).
  3. `v_cap_bottleneck_stations`: Bar chart of workstation cycle times clearly highlighting Station S3 (`Processing`) at 65.01s (vs 20s–50s on other stations).
  4. `v_cap_wait_time_trend`: Line chart of buffer queue wait time before Processing station S3.

---

### Page 7: Alerts & Data Quality Control Tower
- **Purpose:** Warehouse data integrity verification, constraint audits, and active anomaly queue.
- **Visual Components:**
  1. KPI Cards: SQL DQ Checks (65), Passed Checks (65), Violations (0), DQ Status ("100% PASS").
  2. `v_dq_assertion_matrix`: Comprehensive table of all 65 automated warehouse assertions across PK uniqueness, FK integrity, non-negative bounds, and OEE component invariants.
  3. `v_dq_active_alerts_table`: Live queue of SPC rule violations and acknowledgement statuses.
