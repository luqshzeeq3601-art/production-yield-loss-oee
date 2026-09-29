-- Serving views only: existing fact grains and KPI formulas are unchanged.
CREATE OR REPLACE VIEW analytics.vw_work_orders AS
SELECT w.work_order_key, w.work_order_id, d.date_key,
       w.line_key, w.product_key, w.order_date, w.due_date,
       s.status, s.planned_qty, s.produced_qty, s.good_qty, s.scrap_qty,
       s.on_time
FROM analytics.dim_work_order AS w
JOIN staging.mes_work_orders AS s ON s.wo_id = w.work_order_id
JOIN analytics.dim_date AS d ON d.full_date = s.date;
COMMENT ON VIEW analytics.vw_work_orders IS
    'One observed MES order. on_time is the simulator flag, not measured delivery. '
    'No completion timestamp, station assignment, or order-to-hour attribution exists.';

-- Power BI requires a continuous calendar when marking its date table.
CREATE OR REPLACE VIEW analytics.vw_powerbi_date AS
SELECT TO_CHAR(d, 'YYYYMMDD')::INTEGER AS date_key, d::DATE AS full_date,
       EXTRACT(YEAR FROM d)::INTEGER AS year,
       EXTRACT(QUARTER FROM d)::INTEGER AS quarter,
       EXTRACT(MONTH FROM d)::INTEGER AS month,
       RTRIM(TO_CHAR(d, 'Month')) AS month_name,
       EXTRACT(WEEK FROM d)::INTEGER AS week,
       EXTRACT(DAY FROM d)::INTEGER AS day,
       EXTRACT(ISODOW FROM d)::INTEGER AS day_of_week,
       EXTRACT(ISODOW FROM d)::INTEGER IN (6, 7) AS is_weekend
FROM GENERATE_SERIES(
    (SELECT MIN(full_date) FROM analytics.dim_date)::TIMESTAMP,
    (SELECT MAX(d) FROM (
        SELECT full_date AS d FROM analytics.dim_date
        UNION ALL SELECT due_date FROM analytics.dim_work_order
    ) AS calendar_end)::TIMESTAMP,
    INTERVAL '1 day'
) AS dates(d);

-- Filter to selected SECOM sensors and Phase II; MetroPT readings never import.
-- SPC report source_row is zero-based; the warehouse CSV identity is one-based.
CREATE OR REPLACE VIEW analytics.vw_spc_readings AS
SELECT r.sensor_reading_key, r.sensor_key, r.source_system,
       r.source_row - 1 AS source_row, r.reading_ts, r.reading_value,
       l.phase1_mean AS centerline, l.i_lcl AS lcl, l.i_ucl AS ucl,
       EXISTS (
           SELECT 1 FROM analytics.fact_spc_alert a
           WHERE a.sensor_key = r.sensor_key AND a.source_row = r.source_row - 1
             AND a.method = 'WE'
       ) AS we_violation
FROM analytics.fact_sensor_reading r
JOIN analytics.pb_spc_limits l ON l.sensor_key = r.sensor_key
JOIN analytics.pb_spc_lots p ON p.source_row = r.source_row - 1
    AND p.timestamp = r.reading_ts
WHERE r.source_system = 'SECOM';

CREATE OR REPLACE VIEW analytics.vw_oee_plant AS
WITH c AS (
    SELECT SUM(planned_time_min) AS planned_time_min,
           SUM(run_time_min) AS run_time_min,
           SUM(ideal_cycle_time_s * total_count) / 60.0 AS ideal_time_min,
           SUM(total_count) AS total_count, SUM(good_count) AS good_count,
           SUM(scrap_count) AS scrap_count
    FROM analytics.fact_production_hourly
)
SELECT c.*, run_time_min / NULLIF(planned_time_min, 0) AS availability,
       ideal_time_min / NULLIF(run_time_min, 0) AS performance,
       good_count::DOUBLE PRECISION / NULLIF(total_count, 0) AS quality,
       (run_time_min / NULLIF(planned_time_min, 0))
       * (ideal_time_min / NULLIF(run_time_min, 0))
       * (good_count::DOUBLE PRECISION / NULLIF(total_count, 0)) AS oee
FROM c;
