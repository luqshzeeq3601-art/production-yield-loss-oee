# Power BI Desktop Assembly & Deployment Guide

This guide provides the exact sequence of steps to assemble and connect the Power BI report using the semantic layer and theme artifacts in this repository.

---

## 1. Prerequisites & Environment Setup

- **Software:** Microsoft Power BI Desktop (May 2024 or later recommended).
- **Database:** Local PostgreSQL 16 server (`localhost:5432/production_yield_oee`) or Docker container running warehouse database.
- **Theme:** `powerbi/theme.json` located in the repository.
- **Measures Library:** `powerbi/measures.dax`.

---

## 2. Step-by-Step Power BI Desktop Connection

1. **Open Power BI Desktop** $\rightarrow$ Click **Get Data** $\rightarrow$ Select **PostgreSQL database**.
2. **Connection Parameters:**
   - **Server:** `localhost:5432` (or configured host/port).
   - **Database:** `production_yield_oee`.
   - **Data Connectivity Mode:** Select **Import** (or **DirectQuery** for live warehouse view).
3. **Select Analytics Schema Objects:**
   Select the 8 dimensions and 8 facts as specified in `powerbi/model_mapping.csv`:
   - `analytics.dim_date`
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
   - `analytics.fact_sensor_reading`
4. Click **Load**.

---

## 3. Configure Model Relationships

Navigate to **Model View** $\rightarrow$ Confirm the Star Schema relationships:
- All relationships must be **Single Direction (`1:*`)** from dimension tables to fact tables.
- Right-click `dim_date` $\rightarrow$ Select **Mark as Date Table** $\rightarrow$ Choose `full_date` column.

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
