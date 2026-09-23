# Interview Q&A

**Why PostgreSQL?** ACID staging-to-fact loads with row-for-row reconciliation, constraint-enforced grain, and SQL views that Power BI consumes directly — proven by 65/65 DQ checks and 75/75 reconciliation.

**Why a star schema?** Conformed dimensions (line, shift, product, sensor, reason) let OEE slice identically in SQL, Python, and DAX; the SQL↔DAX diff of ~1e-14% is the evidence it worked.

**Why did SPC precision fail?** Univariate rules over ~590 noisy sensors at 4.19% prevalence flag nearly every lot (99.5 alerts/100). Recall without precision is not operationally usable — hence PARTIAL, not success.

**Why not tune Phase II thresholds?** Limits frozen on Phase I; tuning on evaluation labels would leak and invalidate the backtest. The miss is reported, with multivariate-first refinement as the recommendation.

**How is OEE calculated?** Availability = Σrun/Σplanned, Performance = Σideal/Σrun, Quality = Σgood/Σtotal, OEE = A×P×Q from aggregates.

**Why not average row-level OEE?** Hourly percentages weight small and large hours equally; aggregate-component math weights by actual time and units.

**How was data quality validated?** 65 automated checks plus source→staging→fact reconciliation and a 75-check cross-system audit; zero violations, zero rejected rows.

**Why Pareto?** It concentrates effort: 3 of 6 causes explain 74.38% of scrap cost and 87.75% of downtime.

**Why is the RCA statistical, not causal?** Tests show association (chi-square, contrasts) and rediscover injected scenarios; association does not prove shop-floor causality.

**Why is $1.69M modeled, not realized?** It prices a hypothetical 30% loss reduction at a $22.50/unit config assumption. Nothing was saved; it sizes the prize.

**Path to production?** Freeze rule refinements on new labeled data, stream the SPC engine behind the MES with measured latency, complete the `.pbix`, and re-validate precision before any alerting rollout.

**What next?** Multivariate-first alerting with cost-aware thresholds, then a live precision/recall re-measurement.
