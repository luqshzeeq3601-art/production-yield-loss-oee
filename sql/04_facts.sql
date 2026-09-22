-- 04_facts.sql — analytics fact tables.
--
-- Every fact carries a GRAIN comment. Components are stored, KPIs derived:
-- OEE and its A/P/Q factors are recomputed from components, never treated
-- as authoritative stored values. Idempotent objects throughout.

-- GRAIN: one line x shift x date x hour_in_shift (the MES simulator grain).
-- OEE (A x P x Q) derives from planned/run time, ideal cycle x count, good/total.
CREATE TABLE IF NOT EXISTS analytics.fact_production_hourly (
    line_key INTEGER NOT NULL REFERENCES analytics.dim_line (line_key),
    shift_key INTEGER NOT NULL REFERENCES analytics.dim_time_shift (shift_key),
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
    product_key INTEGER NOT NULL REFERENCES analytics.dim_product (product_key),
    hour_in_shift SMALLINT NOT NULL CHECK (hour_in_shift BETWEEN 0 AND 7),
    hour_start TIMESTAMP NOT NULL,
    planned_time_min DOUBLE PRECISION NOT NULL CHECK (planned_time_min > 0),
    run_time_min DOUBLE PRECISION NOT NULL CHECK (run_time_min >= 0),
    ideal_cycle_time_s DOUBLE PRECISION NOT NULL CHECK (ideal_cycle_time_s > 0),
    actual_cycle_time_s DOUBLE PRECISION NOT NULL CHECK (actual_cycle_time_s > 0),
    total_count INTEGER NOT NULL CHECK (total_count >= 0),
    good_count INTEGER NOT NULL CHECK (good_count >= 0),
    scrap_count INTEGER NOT NULL CHECK (scrap_count >= 0),
    PRIMARY KEY (line_key, shift_key, date_key, hour_in_shift),
    CONSTRAINT fact_production_good_le_total CHECK (good_count <= total_count),
    CONSTRAINT fact_production_scrap_le_total CHECK (scrap_count <= total_count),
    CONSTRAINT fact_production_parts_le_total CHECK (good_count + scrap_count <= total_count),
    CONSTRAINT fact_production_run_le_planned CHECK (run_time_min <= planned_time_min)
);
COMMENT ON TABLE analytics.fact_production_hourly IS
    'GRAIN: one line x shift x date x hour_in_shift. Components only; OEE derives.';
CREATE INDEX IF NOT EXISTS ix_production_line_date
    ON analytics.fact_production_hourly (line_key, date_key);
CREATE INDEX IF NOT EXISTS ix_production_hour_start
    ON analytics.fact_production_hourly (hour_start);
CREATE INDEX IF NOT EXISTS ix_production_shift
    ON analytics.fact_production_hourly (shift_key);

-- GRAIN: one downtime event (natural id event_id, e.g. EV-000001).
-- station_machine_key is NULL for line-level reasons (anything but breakdown).
CREATE TABLE IF NOT EXISTS analytics.fact_downtime_event (
    downtime_event_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    line_key INTEGER NOT NULL REFERENCES analytics.dim_line (line_key),
    station_machine_key INTEGER REFERENCES analytics.dim_station_machine (station_machine_key),
    downtime_reason_key INTEGER NOT NULL REFERENCES analytics.dim_downtime_reason (downtime_reason_key),
    shift_key INTEGER NOT NULL REFERENCES analytics.dim_time_shift (shift_key),
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
    start_timestamp TIMESTAMP NOT NULL,
    end_timestamp TIMESTAMP NOT NULL,
    duration_min DOUBLE PRECISION NOT NULL CHECK (duration_min >= 0),
    supplier_tag BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fact_downtime_end_ge_start CHECK (end_timestamp >= start_timestamp)
);
COMMENT ON TABLE analytics.fact_downtime_event IS
    'GRAIN: one downtime event. Planned/unplanned and bucket come from the reason dimension.';
CREATE INDEX IF NOT EXISTS ix_downtime_line_date
    ON analytics.fact_downtime_event (line_key, date_key);
CREATE INDEX IF NOT EXISTS ix_downtime_reason
    ON analytics.fact_downtime_event (downtime_reason_key);
CREATE INDEX IF NOT EXISTS ix_downtime_start
    ON analytics.fact_downtime_event (start_timestamp);
CREATE INDEX IF NOT EXISTS ix_downtime_station
    ON analytics.fact_downtime_event (station_machine_key);

-- GRAIN: one SECOM lot (source_row = positional CSV order, the lot identity).
-- No cost columns: none are observed for SECOM.
CREATE TABLE IF NOT EXISTS analytics.fact_quality_lot (
    quality_lot_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_system TEXT NOT NULL DEFAULT 'SECOM' CHECK (source_system = 'SECOM'),
    source_row BIGINT NOT NULL,
    lot_timestamp TIMESTAMP NOT NULL,
    target SMALLINT NOT NULL CHECK (target IN (0, 1)),
    target_label TEXT NOT NULL CHECK (target_label IN ('pass', 'fail')),
    UNIQUE (source_system, source_row)
);
COMMENT ON TABLE analytics.fact_quality_lot IS
    'GRAIN: one SECOM lot. Pass/fail evidence for yield/SPC; no fabricated costs.';

-- GRAIN: one sensor observation for one entity/timestamp (long form for both
-- SECOM screened sensors and MetroPT-3 signals; never 446 fixed columns).
CREATE TABLE IF NOT EXISTS analytics.fact_sensor_reading (
    sensor_reading_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_key INTEGER NOT NULL REFERENCES analytics.dim_sensor (sensor_key),
    source_system TEXT NOT NULL CHECK (source_system IN ('SECOM', 'METROPT3')),
    source_row BIGINT NOT NULL,
    reading_ts TIMESTAMP NOT NULL,
    reading_value DOUBLE PRECISION NOT NULL,
    UNIQUE (sensor_key, source_system, source_row)
);
COMMENT ON TABLE analytics.fact_sensor_reading IS
    'GRAIN: one sensor observation for one entity/timestamp (long form).';
CREATE INDEX IF NOT EXISTS ix_reading_sensor_ts
    ON analytics.fact_sensor_reading (sensor_key, reading_ts);
CREATE INDEX IF NOT EXISTS ix_reading_entity
    ON analytics.fact_sensor_reading (source_system, source_row);

-- GRAIN: one SPC alert (schema only; P3 generates the rows).
CREATE TABLE IF NOT EXISTS analytics.fact_spc_alert (
    spc_alert_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_ts TIMESTAMP NOT NULL,
    sensor_key INTEGER REFERENCES analytics.dim_sensor (sensor_key),
    source_system TEXT NOT NULL CHECK (source_system IN ('SECOM', 'METROPT3')),
    source_row BIGINT,
    rule_code TEXT NOT NULL,
    method TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'closed')),
    statistic_value DOUBLE PRECISION,
    control_limit_ucl DOUBLE PRECISION,
    control_limit_lcl DOUBLE PRECISION,
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMP
);
COMMENT ON TABLE analytics.fact_spc_alert IS
    'GRAIN: one SPC alert. Populated by the P3 engine; DDL only for now.';
CREATE INDEX IF NOT EXISTS ix_alert_ts
    ON analytics.fact_spc_alert (alert_ts);
CREATE INDEX IF NOT EXISTS ix_alert_sensor
    ON analytics.fact_spc_alert (sensor_key);

-- GRAIN: one line x shift x date (matches MES manpower source).
-- gap derives as planned - actual and is not stored.
CREATE TABLE IF NOT EXISTS analytics.fact_manpower_shift (
    line_key INTEGER NOT NULL REFERENCES analytics.dim_line (line_key),
    shift_key INTEGER NOT NULL REFERENCES analytics.dim_time_shift (shift_key),
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
    planned_headcount INTEGER NOT NULL CHECK (planned_headcount >= 0),
    actual_headcount INTEGER NOT NULL CHECK (actual_headcount >= 0),
    PRIMARY KEY (line_key, shift_key, date_key),
    CONSTRAINT fact_manpower_actual_le_planned CHECK (actual_headcount <= planned_headcount)
);
COMMENT ON TABLE analytics.fact_manpower_shift IS
    'GRAIN: one line x shift x date. Headcount gap derives; not stored.';

-- GRAIN: one line x station x shift x date.
-- Bottleneck designation lives in dim_station_machine; station downtime
-- aggregates derive from fact_downtime_event and are not stored here.
CREATE TABLE IF NOT EXISTS analytics.fact_station_operation (
    line_key INTEGER NOT NULL REFERENCES analytics.dim_line (line_key),
    station_machine_key INTEGER NOT NULL REFERENCES analytics.dim_station_machine (station_machine_key),
    shift_key INTEGER NOT NULL REFERENCES analytics.dim_time_shift (shift_key),
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
    processing_time_s DOUBLE PRECISION NOT NULL CHECK (processing_time_s > 0),
    wait_time_s DOUBLE PRECISION NOT NULL CHECK (wait_time_s >= 0),
    throughput_units INTEGER NOT NULL CHECK (throughput_units >= 0),
    PRIMARY KEY (line_key, station_machine_key, shift_key, date_key)
);
COMMENT ON TABLE analytics.fact_station_operation IS
    'GRAIN: one line x station x shift x date. Bottleneck analysis input.';
CREATE INDEX IF NOT EXISTS ix_station_op_station_date
    ON analytics.fact_station_operation (station_machine_key, date_key);

-- GRAIN: one line x date x product x defect cause (MES scrap evidence).
-- scrap_cost uses the documented config unit-cost assumptions (see dim_product).
CREATE TABLE IF NOT EXISTS analytics.fact_quality_scrap (
    quality_scrap_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date_key INTEGER NOT NULL REFERENCES analytics.dim_date (date_key),
    line_key INTEGER NOT NULL REFERENCES analytics.dim_line (line_key),
    product_key INTEGER NOT NULL REFERENCES analytics.dim_product (product_key),
    defect_cause_key INTEGER NOT NULL REFERENCES analytics.dim_defect_cause (defect_cause_key),
    units_affected INTEGER NOT NULL CHECK (units_affected > 0),
    scrap_cost DOUBLE PRECISION NOT NULL CHECK (scrap_cost >= 0),
    UNIQUE (date_key, line_key, product_key, defect_cause_key)
);
COMMENT ON TABLE analytics.fact_quality_scrap IS
    'GRAIN: one line x date x product x defect cause. Scrap-cost basis for Pareto RCA.';
CREATE INDEX IF NOT EXISTS ix_scrap_cause
    ON analytics.fact_quality_scrap (defect_cause_key);
CREATE INDEX IF NOT EXISTS ix_scrap_line_date
    ON analytics.fact_quality_scrap (line_key, date_key);

-- GRAIN: one equipment state/failure period for one equipment reference.
-- Single generic table retaining MetroPT-3 operating-state periods, documented
-- failure windows, and pre-failure windows. operating_state values are the
-- project-assumption rule; failure windows are transcribed documentation.
CREATE TABLE IF NOT EXISTS analytics.fact_equipment_state_period (
    equipment_period_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_system TEXT NOT NULL CHECK (source_system IN ('METROPT3', 'MES_SIM')),
    equipment_ref TEXT NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('operating_state', 'failure_window', 'prefailure_window')),
    state_label TEXT NOT NULL,
    start_ts TIMESTAMP NOT NULL,
    end_ts TIMESTAMP NOT NULL,
    reading_count INTEGER NOT NULL CHECK (reading_count >= 0),
    duration_seconds DOUBLE PRECISION NOT NULL CHECK (duration_seconds >= 0),
    UNIQUE (source_system, equipment_ref, period_type, start_ts),
    CONSTRAINT fact_equipment_end_ge_start CHECK (end_ts >= start_ts)
);
COMMENT ON TABLE analytics.fact_equipment_state_period IS
    'GRAIN: one equipment state/failure period. Retains MetroPT-3 state and failure evidence.';
CREATE INDEX IF NOT EXISTS ix_equipment_ref_start
    ON analytics.fact_equipment_state_period (equipment_ref, start_ts);
