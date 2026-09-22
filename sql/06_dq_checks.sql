-- 06_dq_checks.sql — automated data-quality checks for the loaded database.
--
-- Executable: psql -d production_yield_oee -f sql/06_dq_checks.sql
-- Returns one row per check: check_id, check_name, category, severity,
-- violation_count, status (PASS when 0, FAIL otherwise), details.
-- Expectations derive from staging/source tables wherever possible; fixed
-- numbers cite their evidence inline and never silently stand in for data.

SELECT 'DQ-A01' AS check_id, 'duplicate dimension natural keys' AS check_name,
    'keys' AS category, 'ERROR' AS severity,
    (SELECT COUNT(*) FROM (SELECT line_code FROM analytics.dim_line GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT station_code FROM analytics.dim_station_machine GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT product_code FROM analytics.dim_product GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT source_system, sensor_code FROM analytics.dim_sensor GROUP BY 1, 2 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT work_order_id FROM analytics.dim_work_order GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT reason_code FROM analytics.dim_downtime_reason GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT cause_code FROM analytics.dim_defect_cause GROUP BY 1 HAVING COUNT(*) > 1) t)
    AS violation_count,
    CASE WHEN (
    (SELECT COUNT(*) FROM (SELECT line_code FROM analytics.dim_line GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT station_code FROM analytics.dim_station_machine GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT product_code FROM analytics.dim_product GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT source_system, sensor_code FROM analytics.dim_sensor GROUP BY 1, 2 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT work_order_id FROM analytics.dim_work_order GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT reason_code FROM analytics.dim_downtime_reason GROUP BY 1 HAVING COUNT(*) > 1) t)
    + (SELECT COUNT(*) FROM (SELECT cause_code FROM analytics.dim_defect_cause GROUP BY 1 HAVING COUNT(*) > 1) t)
    ) = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    'duplicate natural-key groups across all dimensions' AS details

UNION ALL SELECT 'DQ-A02', 'duplicate downtime event ids', 'keys', 'ERROR',
    (SELECT COUNT(*) FROM (SELECT event_id FROM analytics.fact_downtime_event GROUP BY 1 HAVING COUNT(*) > 1) t),
    CASE WHEN (SELECT COUNT(*) FROM (SELECT event_id FROM analytics.fact_downtime_event GROUP BY 1 HAVING COUNT(*) > 1) t) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'event_id must be unique'

UNION ALL SELECT 'DQ-A03', 'duplicate SECOM lot identities', 'keys', 'ERROR',
    (SELECT COUNT(*) FROM (SELECT source_system, source_row FROM analytics.fact_quality_lot GROUP BY 1, 2 HAVING COUNT(*) > 1) t),
    CASE WHEN (SELECT COUNT(*) FROM (SELECT source_system, source_row FROM analytics.fact_quality_lot GROUP BY 1, 2 HAVING COUNT(*) > 1) t) = 0 THEN 'PASS' ELSE 'FAIL' END,
    '(source_system, source_row) must be unique'

UNION ALL SELECT 'DQ-A04', 'duplicate station-operation grain', 'keys', 'ERROR',
    (SELECT COUNT(*) FROM (SELECT line_key, station_machine_key, shift_key, date_key FROM analytics.fact_station_operation GROUP BY 1, 2, 3, 4 HAVING COUNT(*) > 1) t),
    CASE WHEN (SELECT COUNT(*) FROM (SELECT line_key, station_machine_key, shift_key, date_key FROM analytics.fact_station_operation GROUP BY 1, 2, 3, 4 HAVING COUNT(*) > 1) t) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'line x station x shift x date must be unique'

UNION ALL SELECT 'DQ-A05', 'duplicate manpower grain', 'keys', 'ERROR',
    (SELECT COUNT(*) FROM (SELECT line_key, shift_key, date_key FROM analytics.fact_manpower_shift GROUP BY 1, 2, 3 HAVING COUNT(*) > 1) t),
    CASE WHEN (SELECT COUNT(*) FROM (SELECT line_key, shift_key, date_key FROM analytics.fact_manpower_shift GROUP BY 1, 2, 3 HAVING COUNT(*) > 1) t) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'line x shift x date must be unique'

UNION ALL SELECT 'DQ-A06', 'duplicate production grain', 'keys', 'ERROR',
    (SELECT COUNT(*) FROM (SELECT line_key, shift_key, date_key, hour_in_shift FROM analytics.fact_production_hourly GROUP BY 1, 2, 3, 4 HAVING COUNT(*) > 1) t),
    CASE WHEN (SELECT COUNT(*) FROM (SELECT line_key, shift_key, date_key, hour_in_shift FROM analytics.fact_production_hourly GROUP BY 1, 2, 3, 4 HAVING COUNT(*) > 1) t) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'line x shift x date x hour must be unique'

UNION ALL SELECT 'DQ-B01', 'production orphan dimension keys', 'foreign_keys', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'production rows with unknown line/shift/date/product'
FROM analytics.fact_production_hourly AS f
LEFT JOIN analytics.dim_line AS l ON l.line_key = f.line_key
LEFT JOIN analytics.dim_time_shift AS s ON s.shift_key = f.shift_key
LEFT JOIN analytics.dim_date AS d ON d.date_key = f.date_key
LEFT JOIN analytics.dim_product AS p ON p.product_key = f.product_key
WHERE l.line_key IS NULL OR s.shift_key IS NULL OR d.date_key IS NULL OR p.product_key IS NULL

UNION ALL SELECT 'DQ-B02', 'downtime orphan dimension keys', 'foreign_keys', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'downtime rows with unknown line/station/reason/shift/date'
FROM analytics.fact_downtime_event AS f
LEFT JOIN analytics.dim_line AS l ON l.line_key = f.line_key
LEFT JOIN analytics.dim_station_machine AS m ON m.station_machine_key = f.station_machine_key
LEFT JOIN analytics.dim_downtime_reason AS r ON r.downtime_reason_key = f.downtime_reason_key
LEFT JOIN analytics.dim_time_shift AS s ON s.shift_key = f.shift_key
LEFT JOIN analytics.dim_date AS d ON d.date_key = f.date_key
WHERE l.line_key IS NULL
    OR (f.station_machine_key IS NOT NULL AND m.station_machine_key IS NULL)
    OR r.downtime_reason_key IS NULL OR s.shift_key IS NULL OR d.date_key IS NULL

UNION ALL SELECT 'DQ-B03', 'sensor reading orphan sensor keys', 'foreign_keys', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'readings with unknown sensor_key'
FROM analytics.fact_sensor_reading AS f
LEFT JOIN analytics.dim_sensor AS s ON s.sensor_key = f.sensor_key
WHERE s.sensor_key IS NULL

UNION ALL SELECT 'DQ-B04', 'scrap orphan dimension keys', 'foreign_keys', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'scrap rows with unknown date/line/product/cause'
FROM analytics.fact_quality_scrap AS f
LEFT JOIN analytics.dim_date AS d ON d.date_key = f.date_key
LEFT JOIN analytics.dim_line AS l ON l.line_key = f.line_key
LEFT JOIN analytics.dim_product AS p ON p.product_key = f.product_key
LEFT JOIN analytics.dim_defect_cause AS c ON c.defect_cause_key = f.defect_cause_key
WHERE d.date_key IS NULL OR l.line_key IS NULL OR p.product_key IS NULL OR c.defect_cause_key IS NULL

UNION ALL SELECT 'DQ-B05', 'manpower orphan dimension keys', 'foreign_keys', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'manpower rows with unknown line/shift/date'
FROM analytics.fact_manpower_shift AS f
LEFT JOIN analytics.dim_line AS l ON l.line_key = f.line_key
LEFT JOIN analytics.dim_time_shift AS s ON s.shift_key = f.shift_key
LEFT JOIN analytics.dim_date AS d ON d.date_key = f.date_key
WHERE l.line_key IS NULL OR s.shift_key IS NULL OR d.date_key IS NULL

UNION ALL SELECT 'DQ-B06', 'station operation orphan dimension keys', 'foreign_keys', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'station rows with unknown line/station/shift/date'
FROM analytics.fact_station_operation AS f
LEFT JOIN analytics.dim_line AS l ON l.line_key = f.line_key
LEFT JOIN analytics.dim_station_machine AS m ON m.station_machine_key = f.station_machine_key
LEFT JOIN analytics.dim_time_shift AS s ON s.shift_key = f.shift_key
LEFT JOIN analytics.dim_date AS d ON d.date_key = f.date_key
WHERE l.line_key IS NULL OR m.station_machine_key IS NULL OR s.shift_key IS NULL OR d.date_key IS NULL

UNION ALL SELECT 'DQ-B07', 'work order orphan dimension keys', 'foreign_keys', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'work orders with unknown line/product'
FROM analytics.dim_work_order AS w
LEFT JOIN analytics.dim_line AS l ON l.line_key = w.line_key
LEFT JOIN analytics.dim_product AS p ON p.product_key = w.product_key
WHERE l.line_key IS NULL OR p.product_key IS NULL

UNION ALL SELECT 'DQ-C01', 'production negative counts or durations', 'production', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows with any negative count or duration'
FROM analytics.fact_production_hourly
WHERE total_count < 0 OR good_count < 0 OR scrap_count < 0
    OR planned_time_min < 0 OR run_time_min < 0

UNION ALL SELECT 'DQ-C02', 'good_count <= total_count', 'production', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows violating good<=total'
FROM analytics.fact_production_hourly
WHERE good_count > total_count

UNION ALL SELECT 'DQ-C03', 'scrap_count <= total_count', 'production', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows violating scrap<=total'
FROM analytics.fact_production_hourly
WHERE scrap_count > total_count

UNION ALL SELECT 'DQ-C04', 'good_count + scrap_count <= total_count', 'production', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows violating parts<=total (simulator semantics)'
FROM analytics.fact_production_hourly
WHERE good_count + scrap_count > total_count

UNION ALL SELECT 'DQ-C05', 'run_time <= planned_time', 'production', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows violating run<=planned'
FROM analytics.fact_production_hourly
WHERE run_time_min > planned_time_min

UNION ALL SELECT 'DQ-C06', 'ideal cycle time positive where produced', 'production', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'producing rows with non-positive ideal cycle time'
FROM analytics.fact_production_hourly
WHERE total_count > 0 AND ideal_cycle_time_s <= 0

UNION ALL SELECT 'DQ-C07', 'derived performance within [0,1]', 'production', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows with run>0 breaching P = ideal*total/(run*60)'
FROM analytics.fact_production_hourly
WHERE run_time_min > 0
    AND (ideal_cycle_time_s * total_count / (run_time_min * 60.0) < 0
        OR ideal_cycle_time_s * total_count / (run_time_min * 60.0) > 1)

UNION ALL SELECT 'DQ-C08', 'derived availability and quality within [0,1]', 'production', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows breaching A = run/planned or Q = good/total on valid denominators'
FROM analytics.fact_production_hourly
WHERE (planned_time_min > 0 AND (run_time_min / planned_time_min < 0 OR run_time_min / planned_time_min > 1))
    OR (total_count > 0 AND (good_count::double precision / total_count < 0 OR good_count::double precision / total_count > 1))

UNION ALL SELECT 'DQ-D01', 'downtime duration >= 0', 'downtime', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'events with negative duration'
FROM analytics.fact_downtime_event
WHERE duration_min < 0

UNION ALL SELECT 'DQ-D02', 'downtime end >= start', 'downtime', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'events ending before they start'
FROM analytics.fact_downtime_event
WHERE end_timestamp < start_timestamp

UNION ALL SELECT 'DQ-D03', 'event station belongs to event line', 'downtime', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'station events whose station belongs to another line'
FROM analytics.fact_downtime_event AS f
JOIN analytics.dim_station_machine AS m ON m.station_machine_key = f.station_machine_key
WHERE m.line_key IS NOT NULL AND m.line_key <> f.line_key

UNION ALL SELECT 'DQ-D04', 'no overlapping same-machine breakdowns', 'downtime', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'overlapping breakdown pairs on one machine (simulator contract)'
FROM analytics.fact_downtime_event AS a
JOIN analytics.fact_downtime_event AS b
    ON b.station_machine_key = a.station_machine_key
    AND b.downtime_event_key > a.downtime_event_key
    AND b.start_timestamp < a.end_timestamp
    AND b.end_timestamp > a.start_timestamp
    AND b.downtime_reason_key = a.downtime_reason_key
JOIN analytics.dim_downtime_reason AS r ON r.downtime_reason_key = a.downtime_reason_key
WHERE a.station_machine_key IS NOT NULL AND r.reason_code = 'breakdown'

UNION ALL SELECT 'DQ-D05', 'event duration matches timestamps', 'downtime', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'events where duration_min disagrees with end-start beyond 0.01 min'
FROM analytics.fact_downtime_event
WHERE ABS(EXTRACT(EPOCH FROM (end_timestamp - start_timestamp)) / 60.0 - duration_min) > 0.01

UNION ALL SELECT 'DQ-E01', 'manpower headcounts non-negative', 'manpower', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows with negative headcount'
FROM analytics.fact_manpower_shift
WHERE planned_headcount < 0 OR actual_headcount < 0

UNION ALL SELECT 'DQ-E02', 'actual headcount <= planned', 'manpower', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows violating actual<=planned (simulator contract)'
FROM analytics.fact_manpower_shift
WHERE actual_headcount > planned_headcount

UNION ALL SELECT 'DQ-F01', 'station times and throughput non-negative', 'station', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'rows with non-positive processing or negative wait/throughput'
FROM analytics.fact_station_operation
WHERE processing_time_s <= 0 OR wait_time_s < 0 OR throughput_units < 0

UNION ALL SELECT 'DQ-F02', 'station belongs to operation line', 'station', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'operations whose station belongs to another line'
FROM analytics.fact_station_operation AS f
JOIN analytics.dim_station_machine AS m ON m.station_machine_key = f.station_machine_key
WHERE m.line_key IS NOT NULL AND m.line_key <> f.line_key

UNION ALL SELECT 'DQ-F03', 'station throughput matches shift-day production', 'station', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'operations whose throughput differs from summed hourly totals'
FROM analytics.fact_station_operation AS o
LEFT JOIN (
    SELECT line_key, shift_key, date_key, SUM(total_count) AS shift_total
    FROM analytics.fact_production_hourly
    GROUP BY 1, 2, 3
) AS h ON h.line_key = o.line_key AND h.shift_key = o.shift_key AND h.date_key = o.date_key
WHERE h.shift_total IS NULL OR h.shift_total <> o.throughput_units

UNION ALL SELECT 'DQ-F04', 'MES station sequence valid', 'station', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'MES stations without sequence 1-5'
FROM analytics.fact_station_operation AS f
JOIN analytics.dim_station_machine AS m ON m.station_machine_key = f.station_machine_key
WHERE m.line_key IS NOT NULL
    AND (m.station_sequence IS NULL OR m.station_sequence < 1 OR m.station_sequence > 5)

UNION ALL SELECT 'DQ-G01', 'scrap units and cost non-negative', 'scrap', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'scrap rows with non-positive units or negative cost'
FROM analytics.fact_quality_scrap
WHERE units_affected <= 0 OR scrap_cost < 0

UNION ALL SELECT 'DQ-G02', 'SECOM lot count matches staging', 'scrap', 'ERROR',
    ABS((SELECT COUNT(*) FROM analytics.fact_quality_lot) - (SELECT COUNT(*) FROM staging.secom_cleaned)),
    CASE WHEN ABS((SELECT COUNT(*) FROM analytics.fact_quality_lot) - (SELECT COUNT(*) FROM staging.secom_cleaned)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'fact lots vs staging rows (expect 1567 per P1-001 evidence)'

UNION ALL SELECT 'DQ-G03', 'SECOM target remains binary 0/1', 'scrap', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'lots with target outside {0,1}'
FROM analytics.fact_quality_lot
WHERE target NOT IN (0, 1)

UNION ALL SELECT 'DQ-G04', 'SECOM pass/fail counts match staging', 'scrap', 'ERROR',
    ABS((SELECT COUNT(*) FROM analytics.fact_quality_lot WHERE target = 1)
        - (SELECT COUNT(*) FROM staging.secom_cleaned WHERE target = 1)),
    CASE WHEN ABS((SELECT COUNT(*) FROM analytics.fact_quality_lot WHERE target = 1)
        - (SELECT COUNT(*) FROM staging.secom_cleaned WHERE target = 1)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'fail-lot counts fact vs staging (expect 104 per P1-001 evidence)'

UNION ALL SELECT 'DQ-H01', 'no NULL sensor readings stored', 'sensors', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'readings with NULL value'
FROM analytics.fact_sensor_reading
WHERE reading_value IS NULL

UNION ALL SELECT 'DQ-H02', 'SECOM readings match staging non-null cells', 'sensors', 'ERROR',
    ABS((SELECT COUNT(*) FROM analytics.fact_sensor_reading WHERE source_system = 'SECOM')
        - (SELECT
SUM((sensor_000 IS NOT NULL)::int + (sensor_001 IS NOT NULL)::int + (sensor_002 IS NOT NULL)::int + (sensor_003 IS NOT NULL)::int + (sensor_004 IS NOT NULL)::int + (sensor_006 IS NOT NULL)::int + (sensor_007 IS NOT NULL)::int + (sensor_008 IS NOT NULL)::int + (sensor_009 IS NOT NULL)::int + (sensor_010 IS NOT NULL)::int + (sensor_011 IS NOT NULL)::int + (sensor_012 IS NOT NULL)::int + (sensor_014 IS NOT NULL)::int + (sensor_015 IS NOT NULL)::int + (sensor_016 IS NOT NULL)::int + (sensor_017 IS NOT NULL)::int + (sensor_018 IS NOT NULL)::int + (sensor_019 IS NOT NULL)::int + (sensor_020 IS NOT NULL)::int + (sensor_021 IS NOT NULL)::int + (sensor_022 IS NOT NULL)::int + (sensor_023 IS NOT NULL)::int + (sensor_024 IS NOT NULL)::int + (sensor_025 IS NOT NULL)::int + (sensor_026 IS NOT NULL)::int + (sensor_027 IS NOT NULL)::int + (sensor_028 IS NOT NULL)::int + (sensor_029 IS NOT NULL)::int + (sensor_030 IS NOT NULL)::int + (sensor_031 IS NOT NULL)::int + (sensor_032 IS NOT NULL)::int + (sensor_033 IS NOT NULL)::int + (sensor_034 IS NOT NULL)::int + (sensor_035 IS NOT NULL)::int + (sensor_036 IS NOT NULL)::int + (sensor_037 IS NOT NULL)::int + (sensor_038 IS NOT NULL)::int + (sensor_039 IS NOT NULL)::int + (sensor_040 IS NOT NULL)::int + (sensor_041 IS NOT NULL)::int + (sensor_043 IS NOT NULL)::int + (sensor_044 IS NOT NULL)::int + (sensor_045 IS NOT NULL)::int + (sensor_046 IS NOT NULL)::int + (sensor_047 IS NOT NULL)::int + (sensor_048 IS NOT NULL)::int + (sensor_050 IS NOT NULL)::int + (sensor_051 IS NOT NULL)::int + (sensor_053 IS NOT NULL)::int + (sensor_054 IS NOT NULL)::int + (sensor_055 IS NOT NULL)::int + (sensor_056 IS NOT NULL)::int + (sensor_057 IS NOT NULL)::int + (sensor_058 IS NOT NULL)::int + (sensor_059 IS NOT NULL)::int + (sensor_060 IS NOT NULL)::int + (sensor_061 IS NOT NULL)::int + (sensor_062 IS NOT NULL)::int + (sensor_063 IS NOT NULL)::int + (sensor_064 IS NOT NULL)::int + (sensor_065 IS NOT NULL)::int + (sensor_066 IS NOT NULL)::int + (sensor_067 IS NOT NULL)::int + (sensor_068 IS NOT NULL)::int + (sensor_070 IS NOT NULL)::int + (sensor_071 IS NOT NULL)::int + (sensor_074 IS NOT NULL)::int + (sensor_075 IS NOT NULL)::int + (sensor_076 IS NOT NULL)::int + (sensor_077 IS NOT NULL)::int + (sensor_078 IS NOT NULL)::int + (sensor_079 IS NOT NULL)::int + (sensor_080 IS NOT NULL)::int + (sensor_081 IS NOT NULL)::int + (sensor_082 IS NOT NULL)::int + (sensor_083 IS NOT NULL)::int + (sensor_084 IS NOT NULL)::int + (sensor_086 IS NOT NULL)::int + (sensor_087 IS NOT NULL)::int + (sensor_088 IS NOT NULL)::int + (sensor_089 IS NOT NULL)::int + (sensor_090 IS NOT NULL)::int + (sensor_091 IS NOT NULL)::int + (sensor_092 IS NOT NULL)::int + (sensor_093 IS NOT NULL)::int + (sensor_094 IS NOT NULL)::int + (sensor_095 IS NOT NULL)::int + (sensor_096 IS NOT NULL)::int + (sensor_098 IS NOT NULL)::int + (sensor_099 IS NOT NULL)::int + (sensor_100 IS NOT NULL)::int + (sensor_101 IS NOT NULL)::int + (sensor_102 IS NOT NULL)::int + (sensor_103 IS NOT NULL)::int + (sensor_104 IS NOT NULL)::int + (sensor_105 IS NOT NULL)::int + (sensor_106 IS NOT NULL)::int + (sensor_107 IS NOT NULL)::int + (sensor_108 IS NOT NULL)::int + (sensor_112 IS NOT NULL)::int + (sensor_113 IS NOT NULL)::int + (sensor_114 IS NOT NULL)::int + (sensor_115 IS NOT NULL)::int + (sensor_116 IS NOT NULL)::int + (sensor_117 IS NOT NULL)::int + (sensor_118 IS NOT NULL)::int + (sensor_119 IS NOT NULL)::int + (sensor_120 IS NOT NULL)::int + (sensor_121 IS NOT NULL)::int + (sensor_122 IS NOT NULL)::int + (sensor_123 IS NOT NULL)::int + (sensor_124 IS NOT NULL)::int + (sensor_125 IS NOT NULL)::int + (sensor_126 IS NOT NULL)::int + (sensor_127 IS NOT NULL)::int + (sensor_128 IS NOT NULL)::int + (sensor_129 IS NOT NULL)::int + (sensor_130 IS NOT NULL)::int + (sensor_131 IS NOT NULL)::int + (sensor_132 IS NOT NULL)::int + (sensor_133 IS NOT NULL)::int + (sensor_134 IS NOT NULL)::int + (sensor_135 IS NOT NULL)::int + (sensor_136 IS NOT NULL)::int + (sensor_137 IS NOT NULL)::int + (sensor_138 IS NOT NULL)::int + (sensor_139 IS NOT NULL)::int + (sensor_140 IS NOT NULL)::int + (sensor_142 IS NOT NULL)::int + (sensor_143 IS NOT NULL)::int + (sensor_144 IS NOT NULL)::int + (sensor_145 IS NOT NULL)::int + (sensor_146 IS NOT NULL)::int + (sensor_147 IS NOT NULL)::int + (sensor_148 IS NOT NULL)::int + (sensor_150 IS NOT NULL)::int + (sensor_151 IS NOT NULL)::int + (sensor_152 IS NOT NULL)::int + (sensor_153 IS NOT NULL)::int + (sensor_154 IS NOT NULL)::int + (sensor_155 IS NOT NULL)::int + (sensor_156 IS NOT NULL)::int + (sensor_159 IS NOT NULL)::int + (sensor_160 IS NOT NULL)::int + (sensor_161 IS NOT NULL)::int + (sensor_162 IS NOT NULL)::int + (sensor_163 IS NOT NULL)::int + (sensor_164 IS NOT NULL)::int + (sensor_165 IS NOT NULL)::int + (sensor_166 IS NOT NULL)::int + (sensor_167 IS NOT NULL)::int + (sensor_168 IS NOT NULL)::int + (sensor_169 IS NOT NULL)::int + (sensor_170 IS NOT NULL)::int + (sensor_171 IS NOT NULL)::int + (sensor_172 IS NOT NULL)::int + (sensor_173 IS NOT NULL)::int + (sensor_174 IS NOT NULL)::int + (sensor_175 IS NOT NULL)::int + (sensor_176 IS NOT NULL)::int + (sensor_177 IS NOT NULL)::int + (sensor_180 IS NOT NULL)::int + (sensor_181 IS NOT NULL)::int + (sensor_182 IS NOT NULL)::int + (sensor_183 IS NOT NULL)::int + (sensor_184 IS NOT NULL)::int + (sensor_185 IS NOT NULL)::int + (sensor_187 IS NOT NULL)::int + (sensor_188 IS NOT NULL)::int + (sensor_195 IS NOT NULL)::int + (sensor_196 IS NOT NULL)::int + (sensor_197 IS NOT NULL)::int + (sensor_198 IS NOT NULL)::int + (sensor_199 IS NOT NULL)::int + (sensor_200 IS NOT NULL)::int + (sensor_201 IS NOT NULL)::int + (sensor_202 IS NOT NULL)::int + (sensor_203 IS NOT NULL)::int + (sensor_204 IS NOT NULL)::int + (sensor_205 IS NOT NULL)::int + (sensor_206 IS NOT NULL)::int + (sensor_207 IS NOT NULL)::int + (sensor_208 IS NOT NULL)::int + (sensor_209 IS NOT NULL)::int + (sensor_210 IS NOT NULL)::int + (sensor_211 IS NOT NULL)::int + (sensor_212 IS NOT NULL)::int + (sensor_213 IS NOT NULL)::int + (sensor_214 IS NOT NULL)::int + (sensor_215 IS NOT NULL)::int + (sensor_216 IS NOT NULL)::int + (sensor_217 IS NOT NULL)::int + (sensor_218 IS NOT NULL)::int + (sensor_219 IS NOT NULL)::int + (sensor_221 IS NOT NULL)::int + (sensor_222 IS NOT NULL)::int + (sensor_223 IS NOT NULL)::int + (sensor_224 IS NOT NULL)::int + (sensor_225 IS NOT NULL)::int + (sensor_227 IS NOT NULL)::int + (sensor_228 IS NOT NULL)::int + (sensor_238 IS NOT NULL)::int + (sensor_239 IS NOT NULL)::int + (sensor_247 IS NOT NULL)::int + (sensor_248 IS NOT NULL)::int + (sensor_249 IS NOT NULL)::int + (sensor_250 IS NOT NULL)::int + (sensor_251 IS NOT NULL)::int + (sensor_252 IS NOT NULL)::int + (sensor_253 IS NOT NULL)::int + (sensor_254 IS NOT NULL)::int + (sensor_255 IS NOT NULL)::int + (sensor_267 IS NOT NULL)::int + (sensor_268 IS NOT NULL)::int + (sensor_269 IS NOT NULL)::int + (sensor_270 IS NOT NULL)::int + (sensor_271 IS NOT NULL)::int + (sensor_272 IS NOT NULL)::int + (sensor_273 IS NOT NULL)::int + (sensor_274 IS NOT NULL)::int + (sensor_275 IS NOT NULL)::int + (sensor_277 IS NOT NULL)::int + (sensor_278 IS NOT NULL)::int + (sensor_279 IS NOT NULL)::int + (sensor_280 IS NOT NULL)::int + (sensor_281 IS NOT NULL)::int + (sensor_282 IS NOT NULL)::int + (sensor_283 IS NOT NULL)::int + (sensor_285 IS NOT NULL)::int + (sensor_286 IS NOT NULL)::int + (sensor_287 IS NOT NULL)::int + (sensor_288 IS NOT NULL)::int + (sensor_289 IS NOT NULL)::int + (sensor_290 IS NOT NULL)::int + (sensor_291 IS NOT NULL)::int + (sensor_294 IS NOT NULL)::int + (sensor_295 IS NOT NULL)::int + (sensor_296 IS NOT NULL)::int + (sensor_297 IS NOT NULL)::int + (sensor_298 IS NOT NULL)::int + (sensor_299 IS NOT NULL)::int + (sensor_300 IS NOT NULL)::int + (sensor_301 IS NOT NULL)::int + (sensor_302 IS NOT NULL)::int + (sensor_303 IS NOT NULL)::int + (sensor_304 IS NOT NULL)::int + (sensor_305 IS NOT NULL)::int + (sensor_306 IS NOT NULL)::int + (sensor_307 IS NOT NULL)::int + (sensor_308 IS NOT NULL)::int + (sensor_309 IS NOT NULL)::int + (sensor_310 IS NOT NULL)::int + (sensor_311 IS NOT NULL)::int + (sensor_312 IS NOT NULL)::int + (sensor_316 IS NOT NULL)::int + (sensor_317 IS NOT NULL)::int + (sensor_318 IS NOT NULL)::int + (sensor_319 IS NOT NULL)::int + (sensor_320 IS NOT NULL)::int + (sensor_321 IS NOT NULL)::int + (sensor_323 IS NOT NULL)::int + (sensor_324 IS NOT NULL)::int + (sensor_331 IS NOT NULL)::int + (sensor_332 IS NOT NULL)::int + (sensor_333 IS NOT NULL)::int + (sensor_334 IS NOT NULL)::int + (sensor_335 IS NOT NULL)::int + (sensor_336 IS NOT NULL)::int + (sensor_337 IS NOT NULL)::int + (sensor_338 IS NOT NULL)::int + (sensor_339 IS NOT NULL)::int + (sensor_340 IS NOT NULL)::int + (sensor_341 IS NOT NULL)::int + (sensor_342 IS NOT NULL)::int + (sensor_343 IS NOT NULL)::int + (sensor_344 IS NOT NULL)::int + (sensor_347 IS NOT NULL)::int + (sensor_348 IS NOT NULL)::int + (sensor_349 IS NOT NULL)::int + (sensor_350 IS NOT NULL)::int + (sensor_351 IS NOT NULL)::int + (sensor_352 IS NOT NULL)::int + (sensor_353 IS NOT NULL)::int + (sensor_354 IS NOT NULL)::int + (sensor_355 IS NOT NULL)::int + (sensor_356 IS NOT NULL)::int + (sensor_357 IS NOT NULL)::int + (sensor_359 IS NOT NULL)::int + (sensor_360 IS NOT NULL)::int + (sensor_361 IS NOT NULL)::int + (sensor_362 IS NOT NULL)::int + (sensor_363 IS NOT NULL)::int + (sensor_365 IS NOT NULL)::int + (sensor_366 IS NOT NULL)::int + (sensor_367 IS NOT NULL)::int + (sensor_368 IS NOT NULL)::int + (sensor_376 IS NOT NULL)::int + (sensor_377 IS NOT NULL)::int + (sensor_385 IS NOT NULL)::int + (sensor_386 IS NOT NULL)::int + (sensor_387 IS NOT NULL)::int + (sensor_388 IS NOT NULL)::int + (sensor_389 IS NOT NULL)::int + (sensor_390 IS NOT NULL)::int + (sensor_391 IS NOT NULL)::int + (sensor_392 IS NOT NULL)::int + (sensor_393 IS NOT NULL)::int + (sensor_405 IS NOT NULL)::int + (sensor_406 IS NOT NULL)::int + (sensor_407 IS NOT NULL)::int + (sensor_408 IS NOT NULL)::int + (sensor_409 IS NOT NULL)::int + (sensor_410 IS NOT NULL)::int + (sensor_411 IS NOT NULL)::int + (sensor_412 IS NOT NULL)::int + (sensor_413 IS NOT NULL)::int + (sensor_415 IS NOT NULL)::int + (sensor_416 IS NOT NULL)::int + (sensor_417 IS NOT NULL)::int + (sensor_418 IS NOT NULL)::int + (sensor_419 IS NOT NULL)::int + (sensor_420 IS NOT NULL)::int + (sensor_421 IS NOT NULL)::int + (sensor_423 IS NOT NULL)::int + (sensor_424 IS NOT NULL)::int + (sensor_425 IS NOT NULL)::int + (sensor_426 IS NOT NULL)::int + (sensor_427 IS NOT NULL)::int + (sensor_428 IS NOT NULL)::int + (sensor_429 IS NOT NULL)::int + (sensor_430 IS NOT NULL)::int + (sensor_431 IS NOT NULL)::int + (sensor_432 IS NOT NULL)::int + (sensor_433 IS NOT NULL)::int + (sensor_434 IS NOT NULL)::int + (sensor_435 IS NOT NULL)::int + (sensor_436 IS NOT NULL)::int + (sensor_437 IS NOT NULL)::int + (sensor_438 IS NOT NULL)::int + (sensor_439 IS NOT NULL)::int + (sensor_440 IS NOT NULL)::int + (sensor_441 IS NOT NULL)::int + (sensor_442 IS NOT NULL)::int + (sensor_443 IS NOT NULL)::int + (sensor_444 IS NOT NULL)::int + (sensor_445 IS NOT NULL)::int + (sensor_446 IS NOT NULL)::int + (sensor_447 IS NOT NULL)::int + (sensor_448 IS NOT NULL)::int + (sensor_452 IS NOT NULL)::int + (sensor_453 IS NOT NULL)::int + (sensor_454 IS NOT NULL)::int + (sensor_455 IS NOT NULL)::int + (sensor_456 IS NOT NULL)::int + (sensor_457 IS NOT NULL)::int + (sensor_459 IS NOT NULL)::int + (sensor_460 IS NOT NULL)::int + (sensor_467 IS NOT NULL)::int + (sensor_468 IS NOT NULL)::int + (sensor_469 IS NOT NULL)::int + (sensor_470 IS NOT NULL)::int + (sensor_471 IS NOT NULL)::int + (sensor_472 IS NOT NULL)::int + (sensor_473 IS NOT NULL)::int + (sensor_474 IS NOT NULL)::int + (sensor_475 IS NOT NULL)::int + (sensor_476 IS NOT NULL)::int + (sensor_477 IS NOT NULL)::int + (sensor_478 IS NOT NULL)::int + (sensor_479 IS NOT NULL)::int + (sensor_480 IS NOT NULL)::int + (sensor_482 IS NOT NULL)::int + (sensor_483 IS NOT NULL)::int + (sensor_484 IS NOT NULL)::int + (sensor_485 IS NOT NULL)::int + (sensor_486 IS NOT NULL)::int + (sensor_487 IS NOT NULL)::int + (sensor_488 IS NOT NULL)::int + (sensor_489 IS NOT NULL)::int + (sensor_490 IS NOT NULL)::int + (sensor_491 IS NOT NULL)::int + (sensor_493 IS NOT NULL)::int + (sensor_494 IS NOT NULL)::int + (sensor_495 IS NOT NULL)::int + (sensor_496 IS NOT NULL)::int + (sensor_497 IS NOT NULL)::int + (sensor_499 IS NOT NULL)::int + (sensor_500 IS NOT NULL)::int + (sensor_510 IS NOT NULL)::int + (sensor_511 IS NOT NULL)::int + (sensor_519 IS NOT NULL)::int + (sensor_520 IS NOT NULL)::int + (sensor_521 IS NOT NULL)::int + (sensor_522 IS NOT NULL)::int + (sensor_523 IS NOT NULL)::int + (sensor_524 IS NOT NULL)::int + (sensor_525 IS NOT NULL)::int + (sensor_526 IS NOT NULL)::int + (sensor_527 IS NOT NULL)::int + (sensor_539 IS NOT NULL)::int + (sensor_540 IS NOT NULL)::int + (sensor_541 IS NOT NULL)::int + (sensor_542 IS NOT NULL)::int + (sensor_543 IS NOT NULL)::int + (sensor_544 IS NOT NULL)::int + (sensor_545 IS NOT NULL)::int + (sensor_546 IS NOT NULL)::int + (sensor_547 IS NOT NULL)::int + (sensor_548 IS NOT NULL)::int + (sensor_549 IS NOT NULL)::int + (sensor_550 IS NOT NULL)::int + (sensor_551 IS NOT NULL)::int + (sensor_552 IS NOT NULL)::int + (sensor_553 IS NOT NULL)::int + (sensor_554 IS NOT NULL)::int + (sensor_555 IS NOT NULL)::int + (sensor_556 IS NOT NULL)::int + (sensor_557 IS NOT NULL)::int + (sensor_558 IS NOT NULL)::int + (sensor_559 IS NOT NULL)::int + (sensor_560 IS NOT NULL)::int + (sensor_561 IS NOT NULL)::int + (sensor_562 IS NOT NULL)::int + (sensor_563 IS NOT NULL)::int + (sensor_564 IS NOT NULL)::int + (sensor_565 IS NOT NULL)::int + (sensor_566 IS NOT NULL)::int + (sensor_567 IS NOT NULL)::int + (sensor_568 IS NOT NULL)::int + (sensor_569 IS NOT NULL)::int + (sensor_570 IS NOT NULL)::int + (sensor_571 IS NOT NULL)::int + (sensor_572 IS NOT NULL)::int + (sensor_573 IS NOT NULL)::int + (sensor_574 IS NOT NULL)::int + (sensor_575 IS NOT NULL)::int + (sensor_576 IS NOT NULL)::int + (sensor_577 IS NOT NULL)::int + (sensor_582 IS NOT NULL)::int + (sensor_583 IS NOT NULL)::int + (sensor_584 IS NOT NULL)::int + (sensor_585 IS NOT NULL)::int + (sensor_586 IS NOT NULL)::int + (sensor_587 IS NOT NULL)::int + (sensor_588 IS NOT NULL)::int + (sensor_589 IS NOT NULL)::int)
            FROM staging.secom_cleaned)),
    CASE WHEN ABS((SELECT COUNT(*) FROM analytics.fact_sensor_reading WHERE source_system = 'SECOM')
        - (SELECT
SUM((sensor_000 IS NOT NULL)::int + (sensor_001 IS NOT NULL)::int + (sensor_002 IS NOT NULL)::int + (sensor_003 IS NOT NULL)::int + (sensor_004 IS NOT NULL)::int + (sensor_006 IS NOT NULL)::int + (sensor_007 IS NOT NULL)::int + (sensor_008 IS NOT NULL)::int + (sensor_009 IS NOT NULL)::int + (sensor_010 IS NOT NULL)::int + (sensor_011 IS NOT NULL)::int + (sensor_012 IS NOT NULL)::int + (sensor_014 IS NOT NULL)::int + (sensor_015 IS NOT NULL)::int + (sensor_016 IS NOT NULL)::int + (sensor_017 IS NOT NULL)::int + (sensor_018 IS NOT NULL)::int + (sensor_019 IS NOT NULL)::int + (sensor_020 IS NOT NULL)::int + (sensor_021 IS NOT NULL)::int + (sensor_022 IS NOT NULL)::int + (sensor_023 IS NOT NULL)::int + (sensor_024 IS NOT NULL)::int + (sensor_025 IS NOT NULL)::int + (sensor_026 IS NOT NULL)::int + (sensor_027 IS NOT NULL)::int + (sensor_028 IS NOT NULL)::int + (sensor_029 IS NOT NULL)::int + (sensor_030 IS NOT NULL)::int + (sensor_031 IS NOT NULL)::int + (sensor_032 IS NOT NULL)::int + (sensor_033 IS NOT NULL)::int + (sensor_034 IS NOT NULL)::int + (sensor_035 IS NOT NULL)::int + (sensor_036 IS NOT NULL)::int + (sensor_037 IS NOT NULL)::int + (sensor_038 IS NOT NULL)::int + (sensor_039 IS NOT NULL)::int + (sensor_040 IS NOT NULL)::int + (sensor_041 IS NOT NULL)::int + (sensor_043 IS NOT NULL)::int + (sensor_044 IS NOT NULL)::int + (sensor_045 IS NOT NULL)::int + (sensor_046 IS NOT NULL)::int + (sensor_047 IS NOT NULL)::int + (sensor_048 IS NOT NULL)::int + (sensor_050 IS NOT NULL)::int + (sensor_051 IS NOT NULL)::int + (sensor_053 IS NOT NULL)::int + (sensor_054 IS NOT NULL)::int + (sensor_055 IS NOT NULL)::int + (sensor_056 IS NOT NULL)::int + (sensor_057 IS NOT NULL)::int + (sensor_058 IS NOT NULL)::int + (sensor_059 IS NOT NULL)::int + (sensor_060 IS NOT NULL)::int + (sensor_061 IS NOT NULL)::int + (sensor_062 IS NOT NULL)::int + (sensor_063 IS NOT NULL)::int + (sensor_064 IS NOT NULL)::int + (sensor_065 IS NOT NULL)::int + (sensor_066 IS NOT NULL)::int + (sensor_067 IS NOT NULL)::int + (sensor_068 IS NOT NULL)::int + (sensor_070 IS NOT NULL)::int + (sensor_071 IS NOT NULL)::int + (sensor_074 IS NOT NULL)::int + (sensor_075 IS NOT NULL)::int + (sensor_076 IS NOT NULL)::int + (sensor_077 IS NOT NULL)::int + (sensor_078 IS NOT NULL)::int + (sensor_079 IS NOT NULL)::int + (sensor_080 IS NOT NULL)::int + (sensor_081 IS NOT NULL)::int + (sensor_082 IS NOT NULL)::int + (sensor_083 IS NOT NULL)::int + (sensor_084 IS NOT NULL)::int + (sensor_086 IS NOT NULL)::int + (sensor_087 IS NOT NULL)::int + (sensor_088 IS NOT NULL)::int + (sensor_089 IS NOT NULL)::int + (sensor_090 IS NOT NULL)::int + (sensor_091 IS NOT NULL)::int + (sensor_092 IS NOT NULL)::int + (sensor_093 IS NOT NULL)::int + (sensor_094 IS NOT NULL)::int + (sensor_095 IS NOT NULL)::int + (sensor_096 IS NOT NULL)::int + (sensor_098 IS NOT NULL)::int + (sensor_099 IS NOT NULL)::int + (sensor_100 IS NOT NULL)::int + (sensor_101 IS NOT NULL)::int + (sensor_102 IS NOT NULL)::int + (sensor_103 IS NOT NULL)::int + (sensor_104 IS NOT NULL)::int + (sensor_105 IS NOT NULL)::int + (sensor_106 IS NOT NULL)::int + (sensor_107 IS NOT NULL)::int + (sensor_108 IS NOT NULL)::int + (sensor_112 IS NOT NULL)::int + (sensor_113 IS NOT NULL)::int + (sensor_114 IS NOT NULL)::int + (sensor_115 IS NOT NULL)::int + (sensor_116 IS NOT NULL)::int + (sensor_117 IS NOT NULL)::int + (sensor_118 IS NOT NULL)::int + (sensor_119 IS NOT NULL)::int + (sensor_120 IS NOT NULL)::int + (sensor_121 IS NOT NULL)::int + (sensor_122 IS NOT NULL)::int + (sensor_123 IS NOT NULL)::int + (sensor_124 IS NOT NULL)::int + (sensor_125 IS NOT NULL)::int + (sensor_126 IS NOT NULL)::int + (sensor_127 IS NOT NULL)::int + (sensor_128 IS NOT NULL)::int + (sensor_129 IS NOT NULL)::int + (sensor_130 IS NOT NULL)::int + (sensor_131 IS NOT NULL)::int + (sensor_132 IS NOT NULL)::int + (sensor_133 IS NOT NULL)::int + (sensor_134 IS NOT NULL)::int + (sensor_135 IS NOT NULL)::int + (sensor_136 IS NOT NULL)::int + (sensor_137 IS NOT NULL)::int + (sensor_138 IS NOT NULL)::int + (sensor_139 IS NOT NULL)::int + (sensor_140 IS NOT NULL)::int + (sensor_142 IS NOT NULL)::int + (sensor_143 IS NOT NULL)::int + (sensor_144 IS NOT NULL)::int + (sensor_145 IS NOT NULL)::int + (sensor_146 IS NOT NULL)::int + (sensor_147 IS NOT NULL)::int + (sensor_148 IS NOT NULL)::int + (sensor_150 IS NOT NULL)::int + (sensor_151 IS NOT NULL)::int + (sensor_152 IS NOT NULL)::int + (sensor_153 IS NOT NULL)::int + (sensor_154 IS NOT NULL)::int + (sensor_155 IS NOT NULL)::int + (sensor_156 IS NOT NULL)::int + (sensor_159 IS NOT NULL)::int + (sensor_160 IS NOT NULL)::int + (sensor_161 IS NOT NULL)::int + (sensor_162 IS NOT NULL)::int + (sensor_163 IS NOT NULL)::int + (sensor_164 IS NOT NULL)::int + (sensor_165 IS NOT NULL)::int + (sensor_166 IS NOT NULL)::int + (sensor_167 IS NOT NULL)::int + (sensor_168 IS NOT NULL)::int + (sensor_169 IS NOT NULL)::int + (sensor_170 IS NOT NULL)::int + (sensor_171 IS NOT NULL)::int + (sensor_172 IS NOT NULL)::int + (sensor_173 IS NOT NULL)::int + (sensor_174 IS NOT NULL)::int + (sensor_175 IS NOT NULL)::int + (sensor_176 IS NOT NULL)::int + (sensor_177 IS NOT NULL)::int + (sensor_180 IS NOT NULL)::int + (sensor_181 IS NOT NULL)::int + (sensor_182 IS NOT NULL)::int + (sensor_183 IS NOT NULL)::int + (sensor_184 IS NOT NULL)::int + (sensor_185 IS NOT NULL)::int + (sensor_187 IS NOT NULL)::int + (sensor_188 IS NOT NULL)::int + (sensor_195 IS NOT NULL)::int + (sensor_196 IS NOT NULL)::int + (sensor_197 IS NOT NULL)::int + (sensor_198 IS NOT NULL)::int + (sensor_199 IS NOT NULL)::int + (sensor_200 IS NOT NULL)::int + (sensor_201 IS NOT NULL)::int + (sensor_202 IS NOT NULL)::int + (sensor_203 IS NOT NULL)::int + (sensor_204 IS NOT NULL)::int + (sensor_205 IS NOT NULL)::int + (sensor_206 IS NOT NULL)::int + (sensor_207 IS NOT NULL)::int + (sensor_208 IS NOT NULL)::int + (sensor_209 IS NOT NULL)::int + (sensor_210 IS NOT NULL)::int + (sensor_211 IS NOT NULL)::int + (sensor_212 IS NOT NULL)::int + (sensor_213 IS NOT NULL)::int + (sensor_214 IS NOT NULL)::int + (sensor_215 IS NOT NULL)::int + (sensor_216 IS NOT NULL)::int + (sensor_217 IS NOT NULL)::int + (sensor_218 IS NOT NULL)::int + (sensor_219 IS NOT NULL)::int + (sensor_221 IS NOT NULL)::int + (sensor_222 IS NOT NULL)::int + (sensor_223 IS NOT NULL)::int + (sensor_224 IS NOT NULL)::int + (sensor_225 IS NOT NULL)::int + (sensor_227 IS NOT NULL)::int + (sensor_228 IS NOT NULL)::int + (sensor_238 IS NOT NULL)::int + (sensor_239 IS NOT NULL)::int + (sensor_247 IS NOT NULL)::int + (sensor_248 IS NOT NULL)::int + (sensor_249 IS NOT NULL)::int + (sensor_250 IS NOT NULL)::int + (sensor_251 IS NOT NULL)::int + (sensor_252 IS NOT NULL)::int + (sensor_253 IS NOT NULL)::int + (sensor_254 IS NOT NULL)::int + (sensor_255 IS NOT NULL)::int + (sensor_267 IS NOT NULL)::int + (sensor_268 IS NOT NULL)::int + (sensor_269 IS NOT NULL)::int + (sensor_270 IS NOT NULL)::int + (sensor_271 IS NOT NULL)::int + (sensor_272 IS NOT NULL)::int + (sensor_273 IS NOT NULL)::int + (sensor_274 IS NOT NULL)::int + (sensor_275 IS NOT NULL)::int + (sensor_277 IS NOT NULL)::int + (sensor_278 IS NOT NULL)::int + (sensor_279 IS NOT NULL)::int + (sensor_280 IS NOT NULL)::int + (sensor_281 IS NOT NULL)::int + (sensor_282 IS NOT NULL)::int + (sensor_283 IS NOT NULL)::int + (sensor_285 IS NOT NULL)::int + (sensor_286 IS NOT NULL)::int + (sensor_287 IS NOT NULL)::int + (sensor_288 IS NOT NULL)::int + (sensor_289 IS NOT NULL)::int + (sensor_290 IS NOT NULL)::int + (sensor_291 IS NOT NULL)::int + (sensor_294 IS NOT NULL)::int + (sensor_295 IS NOT NULL)::int + (sensor_296 IS NOT NULL)::int + (sensor_297 IS NOT NULL)::int + (sensor_298 IS NOT NULL)::int + (sensor_299 IS NOT NULL)::int + (sensor_300 IS NOT NULL)::int + (sensor_301 IS NOT NULL)::int + (sensor_302 IS NOT NULL)::int + (sensor_303 IS NOT NULL)::int + (sensor_304 IS NOT NULL)::int + (sensor_305 IS NOT NULL)::int + (sensor_306 IS NOT NULL)::int + (sensor_307 IS NOT NULL)::int + (sensor_308 IS NOT NULL)::int + (sensor_309 IS NOT NULL)::int + (sensor_310 IS NOT NULL)::int + (sensor_311 IS NOT NULL)::int + (sensor_312 IS NOT NULL)::int + (sensor_316 IS NOT NULL)::int + (sensor_317 IS NOT NULL)::int + (sensor_318 IS NOT NULL)::int + (sensor_319 IS NOT NULL)::int + (sensor_320 IS NOT NULL)::int + (sensor_321 IS NOT NULL)::int + (sensor_323 IS NOT NULL)::int + (sensor_324 IS NOT NULL)::int + (sensor_331 IS NOT NULL)::int + (sensor_332 IS NOT NULL)::int + (sensor_333 IS NOT NULL)::int + (sensor_334 IS NOT NULL)::int + (sensor_335 IS NOT NULL)::int + (sensor_336 IS NOT NULL)::int + (sensor_337 IS NOT NULL)::int + (sensor_338 IS NOT NULL)::int + (sensor_339 IS NOT NULL)::int + (sensor_340 IS NOT NULL)::int + (sensor_341 IS NOT NULL)::int + (sensor_342 IS NOT NULL)::int + (sensor_343 IS NOT NULL)::int + (sensor_344 IS NOT NULL)::int + (sensor_347 IS NOT NULL)::int + (sensor_348 IS NOT NULL)::int + (sensor_349 IS NOT NULL)::int + (sensor_350 IS NOT NULL)::int + (sensor_351 IS NOT NULL)::int + (sensor_352 IS NOT NULL)::int + (sensor_353 IS NOT NULL)::int + (sensor_354 IS NOT NULL)::int + (sensor_355 IS NOT NULL)::int + (sensor_356 IS NOT NULL)::int + (sensor_357 IS NOT NULL)::int + (sensor_359 IS NOT NULL)::int + (sensor_360 IS NOT NULL)::int + (sensor_361 IS NOT NULL)::int + (sensor_362 IS NOT NULL)::int + (sensor_363 IS NOT NULL)::int + (sensor_365 IS NOT NULL)::int + (sensor_366 IS NOT NULL)::int + (sensor_367 IS NOT NULL)::int + (sensor_368 IS NOT NULL)::int + (sensor_376 IS NOT NULL)::int + (sensor_377 IS NOT NULL)::int + (sensor_385 IS NOT NULL)::int + (sensor_386 IS NOT NULL)::int + (sensor_387 IS NOT NULL)::int + (sensor_388 IS NOT NULL)::int + (sensor_389 IS NOT NULL)::int + (sensor_390 IS NOT NULL)::int + (sensor_391 IS NOT NULL)::int + (sensor_392 IS NOT NULL)::int + (sensor_393 IS NOT NULL)::int + (sensor_405 IS NOT NULL)::int + (sensor_406 IS NOT NULL)::int + (sensor_407 IS NOT NULL)::int + (sensor_408 IS NOT NULL)::int + (sensor_409 IS NOT NULL)::int + (sensor_410 IS NOT NULL)::int + (sensor_411 IS NOT NULL)::int + (sensor_412 IS NOT NULL)::int + (sensor_413 IS NOT NULL)::int + (sensor_415 IS NOT NULL)::int + (sensor_416 IS NOT NULL)::int + (sensor_417 IS NOT NULL)::int + (sensor_418 IS NOT NULL)::int + (sensor_419 IS NOT NULL)::int + (sensor_420 IS NOT NULL)::int + (sensor_421 IS NOT NULL)::int + (sensor_423 IS NOT NULL)::int + (sensor_424 IS NOT NULL)::int + (sensor_425 IS NOT NULL)::int + (sensor_426 IS NOT NULL)::int + (sensor_427 IS NOT NULL)::int + (sensor_428 IS NOT NULL)::int + (sensor_429 IS NOT NULL)::int + (sensor_430 IS NOT NULL)::int + (sensor_431 IS NOT NULL)::int + (sensor_432 IS NOT NULL)::int + (sensor_433 IS NOT NULL)::int + (sensor_434 IS NOT NULL)::int + (sensor_435 IS NOT NULL)::int + (sensor_436 IS NOT NULL)::int + (sensor_437 IS NOT NULL)::int + (sensor_438 IS NOT NULL)::int + (sensor_439 IS NOT NULL)::int + (sensor_440 IS NOT NULL)::int + (sensor_441 IS NOT NULL)::int + (sensor_442 IS NOT NULL)::int + (sensor_443 IS NOT NULL)::int + (sensor_444 IS NOT NULL)::int + (sensor_445 IS NOT NULL)::int + (sensor_446 IS NOT NULL)::int + (sensor_447 IS NOT NULL)::int + (sensor_448 IS NOT NULL)::int + (sensor_452 IS NOT NULL)::int + (sensor_453 IS NOT NULL)::int + (sensor_454 IS NOT NULL)::int + (sensor_455 IS NOT NULL)::int + (sensor_456 IS NOT NULL)::int + (sensor_457 IS NOT NULL)::int + (sensor_459 IS NOT NULL)::int + (sensor_460 IS NOT NULL)::int + (sensor_467 IS NOT NULL)::int + (sensor_468 IS NOT NULL)::int + (sensor_469 IS NOT NULL)::int + (sensor_470 IS NOT NULL)::int + (sensor_471 IS NOT NULL)::int + (sensor_472 IS NOT NULL)::int + (sensor_473 IS NOT NULL)::int + (sensor_474 IS NOT NULL)::int + (sensor_475 IS NOT NULL)::int + (sensor_476 IS NOT NULL)::int + (sensor_477 IS NOT NULL)::int + (sensor_478 IS NOT NULL)::int + (sensor_479 IS NOT NULL)::int + (sensor_480 IS NOT NULL)::int + (sensor_482 IS NOT NULL)::int + (sensor_483 IS NOT NULL)::int + (sensor_484 IS NOT NULL)::int + (sensor_485 IS NOT NULL)::int + (sensor_486 IS NOT NULL)::int + (sensor_487 IS NOT NULL)::int + (sensor_488 IS NOT NULL)::int + (sensor_489 IS NOT NULL)::int + (sensor_490 IS NOT NULL)::int + (sensor_491 IS NOT NULL)::int + (sensor_493 IS NOT NULL)::int + (sensor_494 IS NOT NULL)::int + (sensor_495 IS NOT NULL)::int + (sensor_496 IS NOT NULL)::int + (sensor_497 IS NOT NULL)::int + (sensor_499 IS NOT NULL)::int + (sensor_500 IS NOT NULL)::int + (sensor_510 IS NOT NULL)::int + (sensor_511 IS NOT NULL)::int + (sensor_519 IS NOT NULL)::int + (sensor_520 IS NOT NULL)::int + (sensor_521 IS NOT NULL)::int + (sensor_522 IS NOT NULL)::int + (sensor_523 IS NOT NULL)::int + (sensor_524 IS NOT NULL)::int + (sensor_525 IS NOT NULL)::int + (sensor_526 IS NOT NULL)::int + (sensor_527 IS NOT NULL)::int + (sensor_539 IS NOT NULL)::int + (sensor_540 IS NOT NULL)::int + (sensor_541 IS NOT NULL)::int + (sensor_542 IS NOT NULL)::int + (sensor_543 IS NOT NULL)::int + (sensor_544 IS NOT NULL)::int + (sensor_545 IS NOT NULL)::int + (sensor_546 IS NOT NULL)::int + (sensor_547 IS NOT NULL)::int + (sensor_548 IS NOT NULL)::int + (sensor_549 IS NOT NULL)::int + (sensor_550 IS NOT NULL)::int + (sensor_551 IS NOT NULL)::int + (sensor_552 IS NOT NULL)::int + (sensor_553 IS NOT NULL)::int + (sensor_554 IS NOT NULL)::int + (sensor_555 IS NOT NULL)::int + (sensor_556 IS NOT NULL)::int + (sensor_557 IS NOT NULL)::int + (sensor_558 IS NOT NULL)::int + (sensor_559 IS NOT NULL)::int + (sensor_560 IS NOT NULL)::int + (sensor_561 IS NOT NULL)::int + (sensor_562 IS NOT NULL)::int + (sensor_563 IS NOT NULL)::int + (sensor_564 IS NOT NULL)::int + (sensor_565 IS NOT NULL)::int + (sensor_566 IS NOT NULL)::int + (sensor_567 IS NOT NULL)::int + (sensor_568 IS NOT NULL)::int + (sensor_569 IS NOT NULL)::int + (sensor_570 IS NOT NULL)::int + (sensor_571 IS NOT NULL)::int + (sensor_572 IS NOT NULL)::int + (sensor_573 IS NOT NULL)::int + (sensor_574 IS NOT NULL)::int + (sensor_575 IS NOT NULL)::int + (sensor_576 IS NOT NULL)::int + (sensor_577 IS NOT NULL)::int + (sensor_582 IS NOT NULL)::int + (sensor_583 IS NOT NULL)::int + (sensor_584 IS NOT NULL)::int + (sensor_585 IS NOT NULL)::int + (sensor_586 IS NOT NULL)::int + (sensor_587 IS NOT NULL)::int + (sensor_588 IS NOT NULL)::int + (sensor_589 IS NOT NULL)::int)
            FROM staging.secom_cleaned)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'long-form readings vs non-null wide cells (expect 688014 per P2-003 load)'

UNION ALL SELECT 'DQ-H03', 'MetroPT readings match staging rows x signals', 'sensors', 'ERROR',
    ABS((SELECT COUNT(*) FROM analytics.fact_sensor_reading WHERE source_system = 'METROPT3')
        - (SELECT COUNT(*) FROM staging.metropt3_readings)
        * (SELECT COUNT(*) FROM analytics.dim_sensor WHERE source_system = 'METROPT3')),
    CASE WHEN ABS((SELECT COUNT(*) FROM analytics.fact_sensor_reading WHERE source_system = 'METROPT3')
        - (SELECT COUNT(*) FROM staging.metropt3_readings)
        * (SELECT COUNT(*) FROM analytics.dim_sensor WHERE source_system = 'METROPT3')) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'readings vs 15 signals per observation (expect 22754220 per P2-003 load)'

UNION ALL SELECT 'DQ-H04', 'every SECOM dim sensor has readings', 'sensors', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'dim sensors without fact readings (expect 446 identities per P1-001 evidence)'
FROM analytics.dim_sensor AS d
WHERE d.source_system = 'SECOM'
    AND NOT EXISTS (
        SELECT 1 FROM analytics.fact_sensor_reading AS f
        WHERE f.sensor_key = d.sensor_key
    )

UNION ALL SELECT 'DQ-H05', 'every MetroPT dim sensor has readings', 'sensors', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'dim sensors without fact readings (expect 15 identities per P1-002 evidence)'
FROM analytics.dim_sensor AS d
WHERE d.source_system = 'METROPT3'
    AND NOT EXISTS (
        SELECT 1 FROM analytics.fact_sensor_reading AS f
        WHERE f.sensor_key = d.sensor_key
    )

UNION ALL SELECT 'DQ-H06', 'MetroPT reading timestamps match staging bounds', 'sensors', 'ERROR',
    CASE WHEN (SELECT MIN(reading_ts) FROM analytics.fact_sensor_reading WHERE source_system = 'METROPT3')
        = (SELECT MIN(timestamp) FROM staging.metropt3_readings)
        AND (SELECT MAX(reading_ts) FROM analytics.fact_sensor_reading WHERE source_system = 'METROPT3')
        = (SELECT MAX(timestamp) FROM staging.metropt3_readings)
        THEN 0 ELSE 1 END,
    CASE WHEN (SELECT MIN(reading_ts) FROM analytics.fact_sensor_reading WHERE source_system = 'METROPT3')
        = (SELECT MIN(timestamp) FROM staging.metropt3_readings)
        AND (SELECT MAX(reading_ts) FROM analytics.fact_sensor_reading WHERE source_system = 'METROPT3')
        = (SELECT MAX(timestamp) FROM staging.metropt3_readings)
        THEN 'PASS' ELSE 'FAIL' END,
    'no invented timestamps: fact bounds must equal staging bounds'

UNION ALL SELECT 'DQ-H07', 'SECOM reading timestamps match staging bounds', 'sensors', 'ERROR',
    CASE WHEN (SELECT MIN(reading_ts) FROM analytics.fact_sensor_reading WHERE source_system = 'SECOM')
        = (SELECT MIN(timestamp) FROM staging.secom_cleaned)
        AND (SELECT MAX(reading_ts) FROM analytics.fact_sensor_reading WHERE source_system = 'SECOM')
        = (SELECT MAX(timestamp) FROM staging.secom_cleaned)
        THEN 0 ELSE 1 END,
    CASE WHEN (SELECT MIN(reading_ts) FROM analytics.fact_sensor_reading WHERE source_system = 'SECOM')
        = (SELECT MIN(timestamp) FROM staging.secom_cleaned)
        AND (SELECT MAX(reading_ts) FROM analytics.fact_sensor_reading WHERE source_system = 'SECOM')
        = (SELECT MAX(timestamp) FROM staging.secom_cleaned)
        THEN 'PASS' ELSE 'FAIL' END,
    'no invented timestamps: fact bounds must equal staging bounds'

UNION ALL SELECT 'DQ-I01', 'equipment period start <= end', 'equipment', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'periods ending before they start'
FROM analytics.fact_equipment_state_period
WHERE end_ts < start_ts

UNION ALL SELECT 'DQ-I02', 'failure periods match documented intervals', 'equipment', 'ERROR',
    ABS((SELECT COUNT(*) FROM analytics.fact_equipment_state_period WHERE period_type = 'failure_window')
        - (SELECT COUNT(*) FROM staging.metropt3_failure_intervals)),
    CASE WHEN ABS((SELECT COUNT(*) FROM analytics.fact_equipment_state_period WHERE period_type = 'failure_window')
        - (SELECT COUNT(*) FROM staging.metropt3_failure_intervals)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'failure windows vs intervals artifact (expect 4 documented events)'

UNION ALL SELECT 'DQ-I03', 'prefailure periods match failure periods', 'equipment', 'ERROR',
    ABS((SELECT COUNT(*) FROM analytics.fact_equipment_state_period WHERE period_type = 'prefailure_window')
        - (SELECT COUNT(*) FROM analytics.fact_equipment_state_period WHERE period_type = 'failure_window')),
    CASE WHEN ABS((SELECT COUNT(*) FROM analytics.fact_equipment_state_period WHERE period_type = 'prefailure_window')
        - (SELECT COUNT(*) FROM analytics.fact_equipment_state_period WHERE period_type = 'failure_window')) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'one derived 24 h prefailure window per failure (expect 4)'

UNION ALL SELECT 'DQ-I04', 'operating labels come from staging states', 'equipment', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'operating_state periods with labels never observed in staging'
FROM analytics.fact_equipment_state_period AS f
WHERE f.period_type = 'operating_state'
    AND NOT EXISTS (
        SELECT 1 FROM staging.metropt3_readings AS r
        WHERE r.operating_state = f.state_label
    )

UNION ALL SELECT 'DQ-I05', 'failure labels match documented kinds', 'equipment', 'ERROR',
    COUNT(*),
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'failure windows with undocumented kinds'
FROM analytics.fact_equipment_state_period AS f
WHERE f.period_type = 'failure_window'
    AND NOT EXISTS (
        SELECT 1 FROM staging.metropt3_failure_intervals AS i
        WHERE i.kind = f.state_label
    )

UNION ALL SELECT 'DQ-J01', 'production staging-to-fact reconciliation', 'reconciliation', 'ERROR',
    ABS((SELECT COUNT(*) FROM staging.mes_production_hourly) - (SELECT COUNT(*) FROM analytics.fact_production_hourly)),
    CASE WHEN ABS((SELECT COUNT(*) FROM staging.mes_production_hourly) - (SELECT COUNT(*) FROM analytics.fact_production_hourly)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'hourly rows staging vs fact'

UNION ALL SELECT 'DQ-J02', 'downtime staging-to-fact reconciliation', 'reconciliation', 'ERROR',
    ABS((SELECT COUNT(*) FROM staging.mes_downtime_events) - (SELECT COUNT(*) FROM analytics.fact_downtime_event)),
    CASE WHEN ABS((SELECT COUNT(*) FROM staging.mes_downtime_events) - (SELECT COUNT(*) FROM analytics.fact_downtime_event)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'downtime rows staging vs fact'

UNION ALL SELECT 'DQ-J03', 'manpower staging-to-fact reconciliation', 'reconciliation', 'ERROR',
    ABS((SELECT COUNT(*) FROM staging.mes_manpower_shifts) - (SELECT COUNT(*) FROM analytics.fact_manpower_shift)),
    CASE WHEN ABS((SELECT COUNT(*) FROM staging.mes_manpower_shifts) - (SELECT COUNT(*) FROM analytics.fact_manpower_shift)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'manpower rows staging vs fact'

UNION ALL SELECT 'DQ-J04', 'station staging-to-fact reconciliation', 'reconciliation', 'ERROR',
    ABS((SELECT COUNT(*) FROM staging.mes_station_operations) - (SELECT COUNT(*) FROM analytics.fact_station_operation)),
    CASE WHEN ABS((SELECT COUNT(*) FROM staging.mes_station_operations) - (SELECT COUNT(*) FROM analytics.fact_station_operation)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'station rows staging vs fact'

UNION ALL SELECT 'DQ-J05', 'scrap staging-to-fact reconciliation', 'reconciliation', 'ERROR',
    ABS((SELECT COUNT(*) FROM staging.mes_quality_events) - (SELECT COUNT(*) FROM analytics.fact_quality_scrap)),
    CASE WHEN ABS((SELECT COUNT(*) FROM staging.mes_quality_events) - (SELECT COUNT(*) FROM analytics.fact_quality_scrap)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'scrap rows staging vs fact'

UNION ALL SELECT 'DQ-J06', 'work order staging-to-dim reconciliation', 'reconciliation', 'ERROR',
    ABS((SELECT COUNT(*) FROM staging.mes_work_orders) - (SELECT COUNT(*) FROM analytics.dim_work_order)),
    CASE WHEN ABS((SELECT COUNT(*) FROM staging.mes_work_orders) - (SELECT COUNT(*) FROM analytics.dim_work_order)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'work order rows staging vs dim'

UNION ALL SELECT 'DQ-J07', 'flagged failure rows match intervals artifact', 'reconciliation', 'ERROR',
    ABS(COALESCE((SELECT SUM(in_failure_window) FROM staging.metropt3_readings), 0)
        - COALESCE((SELECT SUM(readings_in_window) FROM staging.metropt3_failure_intervals), 0)),
    CASE WHEN ABS(COALESCE((SELECT SUM(in_failure_window) FROM staging.metropt3_readings), 0)
        - COALESCE((SELECT SUM(readings_in_window) FROM staging.metropt3_failure_intervals), 0)) = 0 THEN 'PASS' ELSE 'FAIL' END,
    'in-window flags vs per-event counts (logging gaps stay gaps, no interpolation)';
