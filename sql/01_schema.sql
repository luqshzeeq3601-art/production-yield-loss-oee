-- 01_schema.sql — schemas for the Production Yield Loss & OEE system.
--
-- Run inside the target database (e.g. production_yield_oee) as a role with
-- CREATE privileges. Idempotent: safe to re-run.
-- Order: 01_schema.sql -> 02_staging.sql -> 03_dims.sql -> 04_facts.sql.
-- Time convention: all TIMESTAMP columns are naive local timestamps exactly
-- as observed in the source CSVs. No timezone conversion is performed.

CREATE SCHEMA IF NOT EXISTS staging;
COMMENT ON SCHEMA staging IS
    'Load heap mirroring source CSV structure. No keys, no calculations.';

CREATE SCHEMA IF NOT EXISTS analytics;
COMMENT ON SCHEMA analytics IS
    'Star schema: dimensions plus fact tables with documented grains.';
