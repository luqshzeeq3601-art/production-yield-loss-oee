# Power BI Connection Checklist

## Database startup

From the repository root:

```powershell
py -3.11 --version
py -3.11 -m pip install -e .
py -3.11 -m scripts.bootstrap_powerbi_db start
py -3.11 -m scripts.bootstrap_powerbi_db check --full-analytics
```

The current PostgreSQL 16.15 instance uses vendor binaries at
`.local/postgresql16/pgsql/bin/` and persistent data at `.local/pgdata/`.
It runs independently of the helper and test servers. After a reboot, run `start`.
Stored data persists. Stop with `py -3.11 -m scripts.bootstrap_powerbi_db stop`.

For a fresh checkout, obtain the vendor Windows ZIP through the
[PostgreSQL download page](https://www.postgresql.org/download/windows/), extract
`pgsql/bin`, `pgsql/lib`, `pgsql/share` into `.local/postgresql16/`, and run
`prepare`. This machine used `postgresql-16.15-1-windows-x64-binaries.zip`.
The helper uses documented [pg_ctl startup](https://www.postgresql.org/docs/16/app-pg-ctl.html),
initializes SCRAM authentication, creates the database if absent, and generates
credentials only when no local `.env` exists. Existing credentials/clusters are preserved.

```powershell
# Dashboard-serving load: no MetroPT reading-level CSV required.
py -3.11 -m scripts.bootstrap_powerbi_db prepare
# Optional full analytical warehouse if the real MetroPT file is available:
py -3.11 -m scripts.bootstrap_powerbi_db load --full-analytics
```

Serving runs **59 DQ checks**; six reading-dependent checks are explicitly
outside scope. This prepared full warehouse runs all **65**. Full analytical
loads retain the original loader contract; use serving refresh for an unchanged
snapshot with diagnostics already imported.

## Connection

- Host: `127.0.0.1`
- Port: `5432`
- Database: `production_yield_oee`
- User: `powerbi_local`
- Authentication: PostgreSQL database username/password (SCRAM-SHA-256)
- Password source: ignored local `.env`, `POSTGRES_PASSWORD`; enter privately in Desktop
- Helper environment: `POSTGRES_HOST/PORT/DB/USER/PASSWORD`; process environment wins
- DATABASE_URL source: optional `.env`/process override; unset in this prepared setup
- TLS: loopback server has no provisioned TLS; accept unencrypted connection if prompted

## Required schemas

- `analytics`: Power BI-facing relations.
- `staging`: internal loader/DQ only; do not import.

## Required Power BI-facing relations

Use `model_mapping.csv` as the exact 25-relation contract, all under `analytics`:

- Dimensions: `vw_powerbi_date` (rename `dim_date`), `dim_line`, `dim_time_shift`,
  `dim_station_machine`, `dim_product`, `dim_downtime_reason`, `dim_defect_cause`, `dim_sensor`.
- Facts: `fact_production_hourly`, `fact_downtime_event`, `fact_quality_scrap`,
  `fact_quality_lot`, `fact_manpower_shift`, `fact_station_operation`, `fact_spc_alert`.
- Serving views: `vw_spc_readings` (rename `fact_sensor_reading`), `vw_work_orders`.
- Evidence: `pb_spc_methods`, `pb_spc_lots`, `pb_spc_failures`, `pb_spc_limits`,
  `pb_impact_metrics`, `pb_dq_checks`, `pb_reconciliation`, `pb_oee_bridge`.
- SQL check views (not additional imports): `vw_oee_plant`, `vw_oee_line_shift`,
  `vw_oee_loss_decomposition`, `vw_pareto_scrap`, `vw_pareto_downtime`.

No page imports MetroPT reading-level data. Compact interval/state evidence is
retained for DQ. The complete analytical pipeline still requires the full source.

## Power BI Desktop

For the **next task**:

1. Get Data.
2. PostgreSQL database.
3. Enter server `127.0.0.1:5432`.
4. Enter database `production_yield_oee`.
5. Choose Database authentication and local credentials.
6. Select the 25 mapped analytics relations.
7. Load/Transform: rename the two view aliases, set types, then Close & Apply.
8. Set single-direction relationships and mark the continuous date table.
9. Create DAX measures, import theme, and follow the seven-page specification.

## Recommended connectivity mode

**Import** suits this reproducible snapshot and offline viewing. DirectQuery
needs the local server running and adds query latency. This historical benchmark
does not provide deployed manufacturing early warning in either mode.

## Expected validation

- Total Units = **1,074,073**; Good Units = **1,036,026**; Scrap Units = **38,047**.
- Availability ≈ **91.29%**; Performance ≈ **84.50%**; Quality ≈ **96.46%**; OEE ≈ **74.41%**.
- Scrap Cost = **$555,891**; unplanned downtime ≈ **2,859.13 h**.
- DQ = **65/65 PASS** on the current full warehouse; zero unexpected violations.
- Artifact reconciliation = **75/75 PASS**; supplemental live SQL checks are separate.
- Work Orders = **720**, complete **266**, partial **454**; completion **36.94%**.
- Phase II failure prevalence **4.19%**; WE precision **4.23%**; WE+EWMA precision **4.21%**.
- Actual Desktop headline KPIs must match SQL within **0.1%**, with slicers cleared.

## Troubleshooting

- **Connection refused:** run `start`, inspect `.local/postgresql.log`, then run `check`.
- **Credential failure:** inspect `.env` privately and clear obsolete credentials
  in Desktop Data source settings. Desktop does not automatically read `.env`.
- **Wrong/occupied port:** before a new cluster is initialized, set a stable free
  `POSTGRES_PORT` in `.env`. For an existing cluster, stop it, change both
  `.local/pgdata/postgresql.conf` and `.env`, then start. Use no random test port.
- **Missing view:** run serving `load` then `check`; select the `analytics` schema.
- **Mismatched KPI:** clear filters and inspect source selection, keys, joins,
  relation direction, and additive component measures. Do not average row OEE or force values.
- **Driver issue:** modern Desktop includes Npgsql. For older versions follow
  [Microsoft's PostgreSQL connector guidance](https://learn.microsoft.com/en-us/power-query/connectors/postgresql).
- **Missing MetroPT readings:** run the serving profile without `--full-analytics`;
  the file is not a seven-page dependency. Never synthesize readings to fill a gap.
- **SPC dates vanish:** keep 2024 MES slicers disconnected from 2008 SPC benchmark tables.
- **Full load after diagnostic import:** the original full loader expects the
  analytical alert-stage contract. Use serving refresh for an unchanged snapshot.

See `desktop_assembly_guide.md` for filter boundaries, caveats, and post-import checks.
