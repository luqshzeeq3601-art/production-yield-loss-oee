# Demo Walkthrough

## A. 2-minute recruiter walkthrough

**Problem:** Yield drops and bottlenecks surfaced days late in manual Excel reports while scrap piled up. **Architecture:** sensor + MES data → Python ingestion → PostgreSQL star schema → DQ/SPC/OEE analytics → Power BI. **Three strongest results:** plant OEE decomposed to 74.41% with top-3 causes carrying 74.38% of scrap cost and 87.75% of downtime; reporting automated from 6 h/week toward <10 min/week (−97.2%); SPC backtest caught 100% of failures ~18 h early — reported transparently at 4.21% precision against a 60% target. **Validation:** 259 tests, 65/65 DQ, 75/75 reconciliation. **Limitation:** MES is simulated and the precision target was missed; economics are modeled, not realized.

## B. 5-minute technical walkthrough

1. **Ingestion:** chunked SECOM/MetroPT-3 loads with timestamp, range, and row-count enforcement (1,567 lots; 1,516,948 rows).
2. **PostgreSQL model:** staging → 9 dimensions / 9 facts, rerun-stable (`TRUNCATE` staging + `INSERT ... ON CONFLICT DO NOTHING`).
3. **DQ:** 65 checks (keys, grains, `good ≤ total`, A/P/Q bounds) with zero violations.
4. **SPC:** FDR-controlled screening, I-MR + Western Electric 1–4, EWMA (λ 0.2), Hotelling T²; Phase I limits frozen before Phase II; chronological backtest vs a next-day 08:00 baseline.
5. **OEE/Pareto/RCA:** aggregate-component OEE math reconciled SQL↔DAX to ~1e-14%; Pareto + chi-square/bottleneck/sensor contrasts that rediscover the injected scenarios using associative language only.
6. **Power BI:** 36 DAX measures, 7 specified pages; final `.pbix` assembly is manual per `powerbi/desktop_assembly_guide.md`.
7. **Testing:** 259 tests under `-W error`, ephemeral PostgreSQL 16, deterministic reruns, documentation-claim gates.

## C. Suggested repository navigation

1. `README.md` (results + limitations) → 2. `docs/architecture.md` → 3. `reports/` (impact, reconciliation, validation evidence) → 4. `docs/case_study.md` → 5. `powerbi/` (spec, measures, assembly guide) → 6. `tests/` (claim and regression gates).
