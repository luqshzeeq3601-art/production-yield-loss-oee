# Data Setup

How a new user obtains every dataset. Raw data is gitignored and never redistributed from this repository.

## SECOM (real, UCI Machine Learning Repository)

- Source: UCI ML Repository, SECOM dataset (`secom.zip`), public direct download recorded in `src/config.yaml` (`secom.source_url`).
- Expected files after download: `secom.data` (sensors) + `secom_labels.data` (pass/fail).
- Destination: `data/raw/` (gitignored).
- Validation on ingest: 1,567 lots, 591 columns (590 sensors + label), timestamps Jul–Oct 2008, binary pass/fail target; cleaning drops sensors with >50% nulls or zero variance (446 retained) — see `reports/secom_cleaning_summary.json`.

## MetroPT-3 (real, UCI Machine Learning Repository)

- Source: UCI ML Repository, MetroPT-3 dataset (DOI `10.24432/C5VW3R`, CC-BY-4.0), direct ZIP download in `src/config.yaml` (`metropt3.source_url`).
- Expected file: `MetroPT3(AirCompressor).csv` under `data/raw/metropt3/`.
- Validation on ingest: 1,516,948 rows enforced via `expected_rows`, non-decreasing timestamps, 7 analog numeric signals with zero nulls, 8 digital binary signals; 4 documented failure intervals mapped to rows plus 24 h pre-failure windows — see `reports/metropt3_ingestion_summary.json`.

## Simulated MES (generated locally)

- No download needed: `py -3.11 -m src.simulate_mes` generates 4 lines × 3 shifts × 180 days with fixed seed 42.
- Outputs: `data/processed/mes_*.csv` (production, downtime, work orders, manpower, stations, quality).
- Three scenarios are openly injected (L2 night-shift minor stops, L3 tool wear, supplier-material hold) and documented in `IMPLEMENTATION_PLAN.md` and `reports/mes_simulation_summary.json`.

## Verify what you have

```bash
py -3.11 -m scripts.verify_data --processed-only
```

checks expected files, required columns, and row-count ranges for the committed processed layer without needing raw downloads or a database. Raw-file checks run only when `data/raw/` is present.
