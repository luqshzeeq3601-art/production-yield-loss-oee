-- 05_views_kpi.sql — rerunnable OEE KPI and diagnostic loss views.
--
-- Time convention:
-- * fact_production_hourly planned_time_min and run_time_min are minutes.
-- * ideal_cycle_time_s and actual_cycle_time_s are seconds per unit.
-- The weighted ideal production basis converts cycle seconds to minutes before
-- calculating Performance. OEE is always derived from additive components;
-- consumers aggregating this view must sum components and recompute, not AVG(oee).

CREATE OR REPLACE VIEW analytics.vw_oee_line_shift AS
WITH production_components AS (
    SELECT
        p.date_key,
        d.full_date,
        p.line_key,
        l.line_code,
        p.shift_key,
        s.shift_code,
        SUM(p.planned_time_min) AS planned_production_time,
        SUM(p.run_time_min) AS run_time,
        SUM(p.ideal_cycle_time_s * p.total_count) / 60.0
            AS ideal_cycle_time_weighted_basis_minutes,
        SUM(p.total_count) AS total_count,
        SUM(p.good_count) AS good_count,
        SUM(p.scrap_count) AS scrap_count,
        SUM(p.ideal_cycle_time_s * p.scrap_count) / 3600.0
            AS quality_equivalent_loss_hours
    FROM analytics.fact_production_hourly AS p
    JOIN analytics.dim_date AS d ON d.date_key = p.date_key
    JOIN analytics.dim_line AS l ON l.line_key = p.line_key
    JOIN analytics.dim_time_shift AS s ON s.shift_key = p.shift_key
    GROUP BY
        p.date_key,
        d.full_date,
        p.line_key,
        l.line_code,
        p.shift_key,
        s.shift_code
)
SELECT
    date_key,
    full_date,
    line_key,
    line_code,
    shift_key,
    shift_code,
    planned_production_time,
    run_time,
    planned_production_time - run_time AS downtime_minutes,
    ideal_cycle_time_weighted_basis_minutes,
    total_count,
    good_count,
    scrap_count,
    run_time / NULLIF(planned_production_time, 0.0) AS availability,
    ideal_cycle_time_weighted_basis_minutes / NULLIF(run_time, 0.0) AS performance,
    good_count::DOUBLE PRECISION / NULLIF(total_count, 0) AS quality,
    (run_time / NULLIF(planned_production_time, 0.0))
        * (ideal_cycle_time_weighted_basis_minutes / NULLIF(run_time, 0.0))
        * (good_count::DOUBLE PRECISION / NULLIF(total_count, 0)) AS oee,
    (planned_production_time - run_time) / 60.0 AS availability_loss_hours,
    (run_time - ideal_cycle_time_weighted_basis_minutes) / 60.0
        AS performance_loss_hours,
    quality_equivalent_loss_hours
FROM production_components;

COMMENT ON VIEW analytics.vw_oee_line_shift IS
    'GRAIN: date x line x shift. planned/run are source minutes; ideal cycle is '
    'weighted seconds per unit converted to minutes. OEE is derived from additive '
    'components without clamping, so genuine invalid upstream inputs remain visible. '
    'Booked downtime and the three OEE bridge losses are authoritative here; raw '
    'downtime-event durations in vw_oee_loss_decomposition are diagnostics and are '
    'not an additive allocation of this bridge.';

COMMENT ON COLUMN analytics.vw_oee_line_shift.downtime_minutes IS
    'Booked downtime: planned_production_time - run_time, in minutes.';
COMMENT ON COLUMN analytics.vw_oee_line_shift.ideal_cycle_time_weighted_basis_minutes IS
    'SUM(ideal_cycle_time_s * total_count) / 60.0; weighted ideal production basis in minutes.';
COMMENT ON COLUMN analytics.vw_oee_line_shift.quality_equivalent_loss_hours IS
    'SUM(ideal_cycle_time_s * scrap_count) / 3600.0. When total_count equals good_count plus scrap_count, Availability plus Performance plus this per-product scrap equivalent telescopes to the physical planned-minus-ideal-good-time bridge. Under product mix, that physical bridge can differ from planned_time * (1 - count-weighted aggregate OEE).';

CREATE OR REPLACE VIEW analytics.vw_oee_loss_decomposition AS
WITH downtime_losses AS (
    SELECT
        e.date_key,
        d.full_date,
        e.line_key,
        l.line_code,
        e.shift_key,
        s.shift_code,
        r.oee_bucket AS loss_category,
        r.reason_code AS loss_reason,
        r.is_planned,
        SUM(e.duration_min) AS loss_minutes,
        COUNT(*)::BIGINT AS affected_count,
        0::BIGINT AS scrap_count,
        SUM(CASE WHEN e.supplier_tag THEN 1 ELSE 0 END)::BIGINT
            AS supplier_tagged_event_count,
        'raw_downtime_event_duration_diagnostic_non_additive'::TEXT
            AS measurement_basis
    FROM analytics.fact_downtime_event AS e
    JOIN analytics.dim_date AS d ON d.date_key = e.date_key
    JOIN analytics.dim_line AS l ON l.line_key = e.line_key
    JOIN analytics.dim_time_shift AS s ON s.shift_key = e.shift_key
    JOIN analytics.dim_downtime_reason AS r
        ON r.downtime_reason_key = e.downtime_reason_key
    GROUP BY
        e.date_key,
        d.full_date,
        e.line_key,
        l.line_code,
        e.shift_key,
        s.shift_code,
        r.oee_bucket,
        r.reason_code,
        r.is_planned
),
reduced_speed_losses AS (
    SELECT
        p.date_key,
        d.full_date,
        p.line_key,
        l.line_code,
        p.shift_key,
        s.shift_code,
        'Performance'::TEXT AS loss_category,
        'reduced_speed'::TEXT AS loss_reason,
        FALSE AS is_planned,
        SUM((p.actual_cycle_time_s - p.ideal_cycle_time_s) * p.total_count) / 60.0
            AS loss_minutes,
        SUM(p.total_count)::BIGINT AS affected_count,
        0::BIGINT AS scrap_count,
        0::BIGINT AS supplier_tagged_event_count,
        'cycle_time_seconds_above_ideal_weighted_by_total_count'::TEXT
            AS measurement_basis
    FROM analytics.fact_production_hourly AS p
    JOIN analytics.dim_date AS d ON d.date_key = p.date_key
    JOIN analytics.dim_line AS l ON l.line_key = p.line_key
    JOIN analytics.dim_time_shift AS s ON s.shift_key = p.shift_key
    WHERE p.actual_cycle_time_s > p.ideal_cycle_time_s
        AND p.total_count > 0
    GROUP BY
        p.date_key,
        d.full_date,
        p.line_key,
        l.line_code,
        p.shift_key,
        s.shift_code
),
scrap_losses AS (
    SELECT
        p.date_key,
        d.full_date,
        p.line_key,
        l.line_code,
        p.shift_key,
        s.shift_code,
        'Quality'::TEXT AS loss_category,
        'scrap'::TEXT AS loss_reason,
        FALSE AS is_planned,
        SUM(p.ideal_cycle_time_s * p.scrap_count) / 60.0 AS loss_minutes,
        SUM(p.scrap_count)::BIGINT AS affected_count,
        SUM(p.scrap_count)::BIGINT AS scrap_count,
        0::BIGINT AS supplier_tagged_event_count,
        'ideal_cycle_seconds_weighted_by_scrap_count'::TEXT AS measurement_basis
    FROM analytics.fact_production_hourly AS p
    JOIN analytics.dim_date AS d ON d.date_key = p.date_key
    JOIN analytics.dim_line AS l ON l.line_key = p.line_key
    JOIN analytics.dim_time_shift AS s ON s.shift_key = p.shift_key
    WHERE p.scrap_count > 0
    GROUP BY
        p.date_key,
        d.full_date,
        p.line_key,
        l.line_code,
        p.shift_key,
        s.shift_code
)
SELECT
    date_key,
    full_date,
    line_key,
    line_code,
    shift_key,
    shift_code,
    loss_category,
    loss_reason,
    loss_minutes,
    loss_minutes / 60.0 AS loss_hours,
    affected_count,
    scrap_count,
    supplier_tagged_event_count,
    measurement_basis,
    is_planned
FROM downtime_losses
UNION ALL
SELECT
    date_key,
    full_date,
    line_key,
    line_code,
    shift_key,
    shift_code,
    loss_category,
    loss_reason,
    loss_minutes,
    loss_minutes / 60.0 AS loss_hours,
    affected_count,
    scrap_count,
    supplier_tagged_event_count,
    measurement_basis,
    is_planned
FROM reduced_speed_losses
UNION ALL
SELECT
    date_key,
    full_date,
    line_key,
    line_code,
    shift_key,
    shift_code,
    loss_category,
    loss_reason,
    loss_minutes,
    loss_minutes / 60.0 AS loss_hours,
    affected_count,
    scrap_count,
    supplier_tagged_event_count,
    measurement_basis,
    is_planned
FROM scrap_losses;

COMMENT ON VIEW analytics.vw_oee_loss_decomposition IS
    'GRAIN: date x line x shift x reason. Raw downtime events retain configured '
    'reason bucket and planned status via Planned category; planned maintenance does '
    'not reclassify into Availability. Raw event durations are diagnostic and can '
    'overlap the fact-derived OEE bridge. Reduced-speed and scrap rows are cycle-time '
    'equivalent losses; no rework row is emitted because rework is absent from the model.';

COMMENT ON COLUMN analytics.vw_oee_loss_decomposition.affected_count IS
    'Event count for raw downtime rows; affected production units for reduced-speed and scrap rows.';

CREATE OR REPLACE VIEW analytics.vw_pareto_scrap AS
WITH cause_aggregates AS (
    SELECT
        c.defect_cause_key,
        c.cause_code,
        c.cause_name,
        SUM(q.units_affected) AS total_units_affected,
        SUM(q.scrap_cost) AS total_scrap_cost,
        COUNT(*)::BIGINT AS scrap_record_count
    FROM analytics.fact_quality_scrap AS q
    JOIN analytics.dim_defect_cause AS c ON c.defect_cause_key = q.defect_cause_key
    GROUP BY
        c.defect_cause_key,
        c.cause_code,
        c.cause_name
),
totals AS (
    SELECT
        SUM(total_scrap_cost) AS grand_total_scrap_cost,
        SUM(total_units_affected) AS grand_total_units_affected
    FROM cause_aggregates
)
SELECT
    a.defect_cause_key,
    a.cause_code,
    a.cause_name,
    a.total_units_affected,
    a.total_scrap_cost,
    a.scrap_record_count,
    a.total_scrap_cost / NULLIF(t.grand_total_scrap_cost, 0.0) AS scrap_cost_share,
    SUM(a.total_scrap_cost) OVER (
        ORDER BY a.total_scrap_cost DESC, a.cause_code
    ) AS cumulative_scrap_cost,
    SUM(a.total_scrap_cost) OVER (
        ORDER BY a.total_scrap_cost DESC, a.cause_code
    ) / NULLIF(t.grand_total_scrap_cost, 0.0) AS cumulative_scrap_cost_share,
    ROW_NUMBER() OVER (
        ORDER BY a.total_scrap_cost DESC, a.cause_code
    ) AS pareto_rank
FROM cause_aggregates AS a
CROSS JOIN totals AS t;

COMMENT ON VIEW analytics.vw_pareto_scrap IS
    'GRAIN: defect_cause. Ranked cumulative scrap-cost Pareto analysis for root cause analysis.';

CREATE OR REPLACE VIEW analytics.vw_pareto_downtime AS
WITH reason_aggregates AS (
    SELECT
        r.downtime_reason_key,
        r.reason_code,
        r.reason_name,
        r.oee_bucket,
        r.is_planned,
        SUM(e.duration_min) AS total_duration_min,
        SUM(e.duration_min) / 60.0 AS total_duration_hours,
        COUNT(*)::BIGINT AS event_count
    FROM analytics.fact_downtime_event AS e
    JOIN analytics.dim_downtime_reason AS r ON r.downtime_reason_key = e.downtime_reason_key
    GROUP BY
        r.downtime_reason_key,
        r.reason_code,
        r.reason_name,
        r.oee_bucket,
        r.is_planned
),
totals AS (
    SELECT
        SUM(total_duration_min) AS grand_total_duration_min,
        SUM(event_count) AS grand_total_events
    FROM reason_aggregates
)
SELECT
    a.downtime_reason_key,
    a.reason_code,
    a.reason_name,
    a.oee_bucket,
    a.is_planned,
    a.total_duration_min,
    a.total_duration_hours,
    a.event_count,
    a.total_duration_min / NULLIF(t.grand_total_duration_min, 0.0) AS downtime_share,
    SUM(a.total_duration_min) OVER (
        ORDER BY a.total_duration_min DESC, a.reason_code
    ) AS cumulative_duration_min,
    SUM(a.total_duration_min) OVER (
        ORDER BY a.total_duration_min DESC, a.reason_code
    ) / NULLIF(t.grand_total_duration_min, 0.0) AS cumulative_downtime_share,
    ROW_NUMBER() OVER (
        ORDER BY a.total_duration_min DESC, a.reason_code
    ) AS pareto_rank
FROM reason_aggregates AS a
CROSS JOIN totals AS t;

COMMENT ON VIEW analytics.vw_pareto_downtime IS
    'GRAIN: downtime_reason. Ranked cumulative downtime-duration Pareto analysis across all events.';
