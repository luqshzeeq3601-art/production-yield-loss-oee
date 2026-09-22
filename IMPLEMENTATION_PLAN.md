# Production Yield Loss & OEE Early-Warning System — Implementation Plan

## Context
The project brief (`Production Yield Loss and OEE Early.md`) describes a problem common in semiconductor, E&E, and medical-device plants. Yield drops and line bottlenecks show up days late in manual Excel reports, so scrap and missed deliveries build up before anyone acts. The folder is misnamed ("Procure-to-Pay…"). The user confirmed this project is the OEE / Yield system.

The goal is a portfolio-grade, end-to-end analytics product: PostgreSQL star schema → Python SPC/RCA engine → Power BI dashboard. It must show measured, defensible impact numbers for a resume. Constraints: a laptop and 4–6 weeks, so the full SECOM dataset is used, MetroPT-3 is ingested in full via chunks, and MES data is simulated.

---

## Step 0 — Housekeeping (first action after approval)
- Rename the folder to `Production Yield Loss and OEE Early-Warning System`. Close this session first, because the working directory itself is being renamed. Do it from Explorer or with:
  `Rename-Item "...\Procure-to-Pay Three-Way Match Reconciliation and Data Quality Control Tower" "Production Yield Loss and OEE Early-Warning System"`
- Tip: OneDrive syncing large CSVs is slow (MetroPT-3 zip ~218 MB, processed readings ~235 MB). Keep `data/raw/` out of OneDrive, or mark it "free up space".
- Run `git init` and add a `.gitignore` for `data/raw`, `data/interim`, `*.pbix` backups, and `.env`.

---

## Problem Statements (3)
| # | Problem statement |
|---|---|
| **PS1 – Late detection** | Yield excursions and process drift are found 1–3 days after they start. Quality is reviewed in end-of-shift or next-morning Excel reports, so bad lots keep running and scrap builds up. |
| **PS2 – Invisible losses** | Management sees one blended "output" number. They can't tell whether lost capacity comes from Availability (downtime), Performance (slow cycles), or Quality (scrap), or which line, shift, or cause drives it. Improvement effort is therefore spread thin. |
| **PS3 – Manual reporting** | Engineers spend hours each week copy-pasting MES exports into Excel. The reports are slow, error-prone, and not comparable across lines. |

## Objectives (3, each mapped to a problem statement)
| # | Objective (SMART) | Answers | Headline KPI |
|---|---|---|---|
| **O1** | Build an SPC + multivariate early-warning engine (Western Electric rules + Hotelling T² / EWMA) on SECOM that cuts **defect-to-alert time by ≥70 %** against the manual daily-report baseline, with alert precision ≥ 60 %. | PS1 | Median hours from excursion to alert; % of failing lots flagged before the next manual report |
| **O2** | Build a star-schema OEE model (A × P × Q by line / shift / machine) and a Pareto RCA that isolates the **top 3 causes explaining ≥ 60 % of scrap cost** and quantifies the **$ recoverable** from fixing them. | PS2 | OEE %, loss by bucket in hours and $, cumulative % scrap cost from the top 3 causes |
| **O3** | Replace the manual Excel report with an automated Python → PostgreSQL → Power BI pipeline. The target is to cut **reporting time from about 6 h/week to under 10 min/week** (≥ 95 %), with automated data-quality checks. | PS3 | Pipeline runtime, analyst hours saved per year, DQ checks passed |

---

## How impact will be quantified (defensible, not invented)
Every number is computed by the project and logged to `reports/impact_metrics.csv`. The README then quotes the measured values.

| Metric | Method |
|---|---|
| **Detection latency** (O1) | Replay SECOM in timestamp order. *Baseline* = a manual review at 08:00 the next day, so each failing lot is "detected" at the next 08:00 after it occurs. *New* = the timestamp of the first SPC/T² alert in the excursion window. Report median and P90 hours saved, plus lots caught early. |
| **Alert quality** (O1) | Confusion matrix of alerts against the SECOM pass/fail label: precision, recall, and false-alarm rate per 100 lots. Western Electric rules alone are compared with rules + T² + EWMA. |
| **Scrap avoided $** (O1→O2) | (Failing units produced between the new alert and the baseline detection) × unit scrap cost (an assumption table: e.g. wafer $1,200, PCBA $45, parametrised in `config.yaml`). |
| **Pareto concentration** (O2) | Cumulative % of scrap cost and downtime minutes from the top 3 causes (simulated MES; MetroPT-3 failure-window analysis). |
| **OEE gain potential** (O2) | What-if: remove X % of the top 3 losses, recompute OEE, then convert to extra units per year and $ contribution margin. |
| **Reporting time** (O3) | Time a scripted replica of the manual Excel workflow (documented step list × realistic minutes) against the logged pipeline runtime plus refresh. Annualise hours saved × analyst rate. |
| **Scale** | Lots, units, sensor readings, and events processed (e.g. "1,567 lots / 590 sensors, 1.52M MetroPT-3 readings, 180 days of MES"). |

---

## Data Plan
| Source | Use | Handling |
|---|---|---|
| **UCI SECOM** (1,567 lots × 591 sensors, pass/fail, timestamps Jul–Oct 2008) | SPC, early warning, yield trend, feature RCA | Load fully. Drop sensors with > 50 % nulls or zero variance. Median-impute for T² only. |
| **UCI MetroPT-3** (1,516,948 timestamped readings, Feb–Sep 2020, 7 analog + 8 digital signals, 4 documented air-leak failure windows) | Real industrial sensor/failure-window analysis at scale | Direct ZIP download (CC BY 4.0, DOI 10.24432/C5VW3R). Read in chunks, validate ranges (analog numeric, digital binary, no nulls), enforce non-decreasing timestamps, map documented failure intervals + 24 h pre-failure windows. Dataset itself is unlabeled; windows are transcribed documentation, not observed labels. |
| **Simulated MES** (Python, fixed seed) | Work orders, plan vs actual, downtime events, shift logs, manpower, scrap cost | 4 lines × 3 shifts × 180 days. Ideal cycle time per product. Downtime by exponential/Weibull with reasons (breakdown, changeover, material shortage, minor stop, quality hold). **Injected scenarios** (e.g. Line 2 night-shift minor stops, tool-wear drift on Line 3, one supplier-lot quality hold) are documented openly in the README so the RCA "discovery" is transparent. |

---

## Architecture & Repo Layout
```
data/raw | interim | processed         (raw/interim gitignored)
sql/  01_schema.sql  02_staging.sql  03_dims.sql  04_facts.sql  05_views_kpi.sql  06_dq_checks.sql
src/
  config.yaml            # paths, DB conn, cost assumptions, SPC params
  ingest_secom.py        # download + clean + load
  ingest_metropt3.py     # chunked time-series ingestion + failure/state windows
  simulate_mes.py        # work orders, downtime, shifts, manpower, scrap
  load_db.py             # COPY into Postgres staging → dims/facts
  spc_engine.py          # I-MR / p-chart limits, WE rules 1–4, EWMA, Hotelling T²
  feature_screening.py   # scipy: point-biserial, KS test, Mann-Whitney → top sensors
  rca_pareto.py          # Pareto, correlation, shift/line contrasts (chi-square)
  impact_metrics.py      # latency back-test, $ avoided, hours saved
  run_pipeline.py        # orchestrates everything, logs runtime → pipeline_log
notebooks/ 01_eda_secom  02_eda_metropt3  03_spc_backtest  04_rca
powerbi/ OEE_EarlyWarning.pbix  theme.json  measures.dax (exported)
excel/ manual_report_baseline.xlsx (the "before" state)  alert_export_template.xlsx
reports/ impact_metrics.csv  case_study.md  screenshots/
tests/ test_oee_math.py  test_spc_rules.py  test_dq.py
README.md
```

### Star Schema (PostgreSQL)
- **Dimensions:** `dim_date`, `dim_time_shift` (shift A/B/C, crew), `dim_line`, `dim_station_machine`, `dim_product`, `dim_sensor` (parameter, USL/LSL, criticality), `dim_downtime_reason` (planned/unplanned, A/P/Q bucket), `dim_defect_cause`, `dim_work_order`.
- **Facts:**
  - `fact_production_hourly` (line × shift × hour: planned time, run time, ideal CT, total count, good count) → OEE grain.
  - `fact_downtime_event` (start, end, minutes, reason).
  - `fact_quality_lot` (SECOM lot: pass/fail, scrap cost).
  - `fact_sensor_reading` (long format, screened sensors only).
  - `fact_spc_alert` (sensor, rule violated, timestamp, severity, ack status).
  - `fact_manpower_shift` (headcount planned vs actual).
- **KPI views:** `vw_oee_line_shift`, `vw_pareto_scrap`, `vw_pareto_downtime`, `vw_wo_status`, `vw_capacity`, `vw_alert_latency`.

---

## Phased Execution (6 weeks)

**Week 1 – Setup & ingestion**
- Install PostgreSQL 16, Python 3.11 (pandas, numpy, scipy, sqlalchemy, psycopg2, pyyaml, pytest, matplotlib), and Power BI Desktop.
- Download SECOM and MetroPT-3 (both are direct UCI downloads; no API credentials needed).
- Write `ingest_secom.py` and `ingest_metropt3.py` with chunked processing. Profile the data (nulls, distributions, class imbalance, timestamps, failure windows) in notebooks 01–02.
- Build the Excel **manual baseline report** (pivot of daily yield, downtime, scrap). Time each step: this is the "before" state for O3.

**Week 2 – Simulation & modeling**
- Write `simulate_mes.py` with injected scenarios and a seed. Validate that simulated OEE lands in a realistic range (about 55–75 %, against a world-class benchmark of 85 %).
- Write the SQL schema, staging, dims, facts, and `load_db.py`.
- Add data-quality checks in `06_dq_checks.sql`: PK uniqueness, FK orphans, `good ≤ total`, `run_time ≤ planned`, 0 ≤ A, P, Q ≤ 1, no negative durations.

**Week 3 – SPC & early warning (O1)**
- `feature_screening.py`: rank sensors with scipy tests (point-biserial r, KS statistic, Mann-Whitney p-value, Benjamini-Hochberg FDR). Keep the top 10–15 critical parameters.
- `spc_engine.py`:
  - Phase I limits from the first 30 % of lots (pass lots only).
  - I-MR charts plus WE rules 1–4: 1 point beyond 3σ; 2 of 3 beyond 2σ; 4 of 5 beyond 1σ; 8 on one side.
  - EWMA (λ = 0.2) for small shifts.
  - Hotelling T² across the screened sensors with an F-distribution UCL.
  - p-chart on daily yield.
- `03_spc_backtest` notebook: replay the Phase II period and compute latency against the baseline, precision/recall, and alerts per 100 lots. Tune rules to balance catches against false alarms. Write the results to `fact_spc_alert` and `impact_metrics.csv`.

**Week 4 – OEE, RCA, work orders, capacity (O2)**
- SQL KPI views: OEE = A × P × Q, with loss decomposition into hours (six big losses mapped to A/P/Q).
- `rca_pareto.py`:
  - Pareto of scrap $ and downtime minutes.
  - Chi-square test of shift × line against defect rate.
  - MES station failure-rate ranking and dwell-time bottleneck detection, plus MetroPT-3 failure-window contrasts.
  - SECOM top-sensor correlation with fail.
- What-if OEE uplift and $ recoverable.
- Work order plan vs actual (on-time %, backlog). Capacity view: required hours against available hours, and headcount against plan.

**Week 5 – Power BI dashboard + automation (O3)**
- Import mode from Postgres views. Build the model on the star schema with single-direction relationships and a marked date table.
- **DAX measures:** `Availability`, `Performance`, `Quality`, `OEE`, `OEE vs Target`, `Scrap Cost`, `Cum % Pareto`, `Yield %`, `Alerts Open`, `Median Alert Latency (h)`, `Hours Saved vs Baseline`, `WO On-Time %`, `Capacity Utilization %`, `Manpower Gap`.
- **Pages:**
  1. Executive summary: KPI cards and impact tiles.
  2. OEE decomposition by line / shift, with a waterfall of losses.
  3. SPC monitor: control chart with UCL/LCL bands and rule-violation markers, drill to sensor.
  4. Pareto and RCA.
  5. Work-order tracking against plan.
  6. Capacity and manpower.
  7. Alert log and data-quality status.
- Add conditional formatting, tooltips, a bookmark for "before vs after", and mobile layout for page 1.
- `run_pipeline.py` runs all steps end to end, with runtime logged to `pipeline_log`. Schedule it with Windows Task Scheduler. Export the alert list to the Excel template for supervisors.

**Week 6 – Validation, packaging, storytelling**
- Tests with pytest: OEE math on hand-computed fixtures, SPC rule detection on synthetic series with known violations, and DQ assertions.
- Reconcile DAX results with SQL view totals (must match within 0.1 %).
- README: problem → approach → architecture diagram → impact table (measured numbers) → screenshots → assumptions and limitations → how to run.
- `case_study.md` (a one-page STAR write-up), a 2–3 min Loom demo, and a LinkedIn post. Publish to GitHub; the `.pbix` goes in the repo, with a PDF export for viewers without Power BI.

---

## Resume Bullets (fill with measured values from `impact_metrics.csv`)
- "Built an end-to-end OEE and yield early-warning system (PostgreSQL star schema, Python/SciPy, Power BI/DAX) over **1,567 wafer lots × 590 sensors, 1.52M MetroPT-3 readings, and 180 days of MES data**."
- "Designed SPC (Western Electric + EWMA + Hotelling T²) alerts that flagged yield excursions a **median Y hours earlier** (−Z % detection latency) than daily manual reports, with **P % precision**, avoiding an estimated **$S scrap**."
- "Pareto and statistical RCA isolated **3 causes driving Z % of scrap cost**, sizing a **+N pt OEE / $M annual** recovery opportunity."
- "Automated weekly Excel reporting into a scheduled pipeline, cutting reporting time **from ~6 h to <10 min (−97 %)** and saving **~300 analyst-hours per year**."

## Skills Evidence Map
SQL and star schema (`sql/`), statistics and SPC (`spc_engine.py`, `feature_screening.py`), anomaly detection (T², EWMA), KPI design (DAX measures), RCA (`rca_pareto.py`), and Excel-to-dashboard migration (`excel/` baseline → Power BI).

---

## Verification
1. `pytest tests/` all pass. This includes OEE fixtures (e.g. A = 0.9, P = 0.95, Q = 0.98 → OEE = 0.8379) and SPC rule unit tests.
2. `python src/run_pipeline.py` runs clean from an empty DB. Row counts match the sources, and `06_dq_checks.sql` returns 0 violations.
3. The back-test notebook reproduces `impact_metrics.csv` deterministically (fixed seeds).
4. Power BI totals (OEE, scrap $, yield) reconcile with the SQL views, and the refresh succeeds against Postgres.
5. Peer sanity check: every resume number traces to a row in `impact_metrics.csv` and an assumption in `config.yaml`.
