-- 03_dims.sql — analytics dimensions with surrogate keys.
--
-- Idempotent objects (IF NOT EXISTS / ON CONFLICT DO NOTHING).
-- Static reference rows (shifts, downtime reasons, defect causes) are seeded
-- here from the configured vocabularies. Data-driven dimensions (date, line,
-- station, product, sensor, work order) are populated by the P2-003 loader.

-- Calendar date. date_key is YYYYMMDD for readability and sortability.
CREATE TABLE IF NOT EXISTS analytics.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    year SMALLINT NOT NULL,
    quarter SMALLINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name TEXT NOT NULL,
    week SMALLINT NOT NULL CHECK (week BETWEEN 1 AND 53),
    day SMALLINT NOT NULL CHECK (day BETWEEN 1 AND 31),
    day_of_week SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
    is_weekend BOOLEAN NOT NULL,
    CONSTRAINT dim_date_key_matches_date CHECK (
        date_key = year * 10000 + month * 100 + day
    )
);
COMMENT ON TABLE analytics.dim_date IS 'One row per calendar date.';

-- Work shifts. Crew is nullable: the simulator does not model crews.
CREATE TABLE IF NOT EXISTS analytics.dim_time_shift (
    shift_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_code TEXT NOT NULL UNIQUE,
    shift_name TEXT NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    crew TEXT
);
COMMENT ON TABLE analytics.dim_time_shift IS 'Shift definitions; hours match src/config.yaml.';

-- Production lines.
CREATE TABLE IF NOT EXISTS analytics.dim_line (
    line_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    line_code TEXT NOT NULL UNIQUE,
    line_name TEXT NOT NULL
);
COMMENT ON TABLE analytics.dim_line IS 'One row per production line.';

-- Stations/machines. line_key is nullable: equipment such as the MetroPT-3
-- air-production unit belongs to no simulated line. is_bottleneck records the
-- simulation designation for MES stations; it is an input attribute, not a
-- measured result.
CREATE TABLE IF NOT EXISTS analytics.dim_station_machine (
    station_machine_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    line_key INTEGER REFERENCES analytics.dim_line (line_key),
    station_code TEXT NOT NULL UNIQUE,
    station_name TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    station_sequence INTEGER,
    is_bottleneck BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE analytics.dim_station_machine IS
    'Stations and equipment; MetroPT-3 APU rows carry a NULL line_key.';
CREATE INDEX IF NOT EXISTS ix_station_machine_line
    ON analytics.dim_station_machine (line_key);

-- Products. Economic and cycle assumptions come from src/config.yaml and are
-- documented inputs for recovery math, not measurements.
CREATE TABLE IF NOT EXISTS analytics.dim_product (
    product_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_code TEXT NOT NULL UNIQUE,
    product_name TEXT,
    ideal_cycle_time_s DOUBLE PRECISION CHECK (ideal_cycle_time_s IS NULL OR ideal_cycle_time_s > 0),
    unit_scrap_cost DOUBLE PRECISION CHECK (unit_scrap_cost IS NULL OR unit_scrap_cost >= 0),
    cost_source TEXT
);
COMMENT ON TABLE analytics.dim_product IS
    'MES products P1-P4; unit_scrap_cost is a documented config assumption.';

-- Sensors across source systems. No USL/LSL is stored: none was observed.
CREATE TABLE IF NOT EXISTS analytics.dim_sensor (
    sensor_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_system TEXT NOT NULL CHECK (source_system IN ('SECOM', 'METROPT3')),
    sensor_code TEXT NOT NULL,
    unit TEXT,
    sensor_type TEXT NOT NULL CHECK (sensor_type IN ('analog', 'digital')),
    is_critical BOOLEAN,
    UNIQUE (source_system, sensor_code)
);
COMMENT ON TABLE analytics.dim_sensor IS
    'SECOM retained sensors plus the 15 MetroPT-3 signals; criticality is set by later screening.';

-- Downtime reasons with the OEE loss bucket and planned classification.
CREATE TABLE IF NOT EXISTS analytics.dim_downtime_reason (
    downtime_reason_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reason_code TEXT NOT NULL UNIQUE,
    reason_name TEXT NOT NULL,
    is_planned BOOLEAN NOT NULL,
    oee_bucket TEXT NOT NULL CHECK (oee_bucket IN ('Availability', 'Performance', 'Quality', 'Planned'))
);
COMMENT ON TABLE analytics.dim_downtime_reason IS
    'Reason vocabulary from src/config.yaml; bucket drives loss decomposition.';

-- Defect causes.
CREATE TABLE IF NOT EXISTS analytics.dim_defect_cause (
    defect_cause_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cause_code TEXT NOT NULL UNIQUE,
    cause_name TEXT NOT NULL,
    category TEXT,
    source_system TEXT NOT NULL CHECK (source_system IN ('MES_SIM', 'SECOM', 'METROPT3'))
);
COMMENT ON TABLE analytics.dim_defect_cause IS 'MES defect-cause vocabulary.';

-- Work orders (header; quantities live in MES source / planned fields here).
CREATE TABLE IF NOT EXISTS analytics.dim_work_order (
    work_order_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    work_order_id TEXT NOT NULL UNIQUE,
    line_key INTEGER NOT NULL REFERENCES analytics.dim_line (line_key),
    product_key INTEGER NOT NULL REFERENCES analytics.dim_product (product_key),
    order_date DATE NOT NULL,
    due_date DATE NOT NULL,
    planned_qty INTEGER NOT NULL CHECK (planned_qty > 0),
    CONSTRAINT dim_work_order_dates CHECK (due_date >= order_date)
);
COMMENT ON TABLE analytics.dim_work_order IS 'One row per MES work order.';
CREATE INDEX IF NOT EXISTS ix_work_order_line_date
    ON analytics.dim_work_order (line_key, order_date);

-- Reference seeds (idempotent).
INSERT INTO analytics.dim_time_shift (shift_code, shift_name, start_time, end_time, crew)
VALUES
    ('A', 'Day shift', TIME '06:00', TIME '14:00', NULL),
    ('B', 'Evening shift', TIME '14:00', TIME '22:00', NULL),
    ('C', 'Night shift', TIME '22:00', TIME '06:00', NULL)
ON CONFLICT (shift_code) DO NOTHING;

INSERT INTO analytics.dim_downtime_reason (reason_code, reason_name, is_planned, oee_bucket)
VALUES
    ('breakdown', 'Breakdown', FALSE, 'Availability'),
    ('changeover', 'Changeover', FALSE, 'Availability'),
    ('material_shortage', 'Material shortage', FALSE, 'Availability'),
    ('quality_hold', 'Quality hold', FALSE, 'Availability'),
    ('minor_stop', 'Minor stop', FALSE, 'Performance'),
    ('planned_maintenance', 'Planned maintenance', TRUE, 'Planned')
ON CONFLICT (reason_code) DO NOTHING;

INSERT INTO analytics.dim_defect_cause (cause_code, cause_name, category, source_system)
VALUES
    ('dimensional', 'Dimensional', 'process', 'MES_SIM'),
    ('surface defect', 'Surface defect', 'process', 'MES_SIM'),
    ('contamination', 'Contamination', 'material', 'MES_SIM'),
    ('tool wear', 'Tool wear', 'tooling', 'MES_SIM'),
    ('supplier material', 'Supplier material', 'material', 'MES_SIM'),
    ('other', 'Other', 'other', 'MES_SIM')
ON CONFLICT (cause_code) DO NOTHING;
