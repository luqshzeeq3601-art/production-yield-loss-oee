# Resume Bullets — Production Yield Loss & OEE Early-Warning System

All claims trace to `reports/impact_claims.json` (safe_to_use = true only).

## A. 3 concise resume bullets

- Built an end-to-end manufacturing analytics platform processing 1.5M+ industrial sensor observations and 17,280 MES production records with Python and PostgreSQL.
- Automated a 6-hour/week Excel reporting workflow to a <10-minute target pipeline (97.2% reduction, ~303 analyst-hours/year).
- Developed OEE, Pareto, RCA, and SPC analytics; plant OEE 74.41% with top-three causes driving 74.38% of scrap cost and 87.75% of unplanned downtime.

## B. 5 extended resume bullets

- Built a PostgreSQL 16 star-schema warehouse (9 dimensions, 9 facts) loading 23.4M sensor readings with row-for-row source-to-fact reconciliation and 65/65 passing DQ checks.
- Backtested an SPC early-warning engine (Western Electric + EWMA + Hotelling T²) on 1,097 Phase II lots: 100% recall of 46 failures a median ~18 h before manual review, reported honestly at 4.21% precision against a 60% target.
- Decomposed plant OEE into 91.29% Availability x 84.50% Performance x 96.46% Quality (74.41%), isolating L2 night-shift and L3 tool-wear loss patterns via Pareto and statistical RCA.
- Modeled a 30% combined loss-reduction scenario projecting OEE improvement from 74.41% to 78.96% and $1.69M annual recoverable value.
- Delivered a reconciled Power BI semantic layer (36 DAX measures, SQL-vs-DAX diff ~1e-14%) with a 7-page dashboard specification and a 14-stage automated pipeline.

## C. 60-second interview explanation

"Plants found yield problems days late in Excel, so I built a pipeline that ingests SECOM and compressor sensor data plus simulated MES operations into a PostgreSQL star schema, runs SPC early-warning and OEE/Pareto/RCA analytics, and serves a Power BI layer. It decomposes OEE to 74.41%, concentrates three-quarters of scrap and almost 90% of downtime into three causes each, and cuts reporting from six hours to under ten minutes. The SPC backtest caught every failure about 18 hours earlier — but at 4% precision, so I reported the miss honestly and recommended multivariate-first refinement instead of claiming victory. Everything reconciles: 259 tests, 65 DQ checks, 75 cross-system checks."

## D. Technical interview talking points

- Phase I/Phase II discipline: limits frozen on the first 30% of lots; Phase II never touched during estimation; no post-hoc threshold tuning.
- Why precision collapsed: univariate rules over ~590 noisy sensors at 4% prevalence; false-alarm math and the precision/recall trade-off.
- OEE aggregate-component math (never averaged row-level percentages) and SQL-vs-DAX reconciliation method.
- Star-schema grain choices, staging TRUNCATE + INSERT-ON-CONFLICT rerun semantics, and the 70,628 = 70,620 + 4 + 4 equipment-period composition.
- Configured targets vs measured runtime: the <10 min figure is a pipeline-plus-refresh target, stated as such.
- Modeled vs realized: what-if economics ($22.50/unit margin) sizes the prize; nothing was "saved."

## E. Recruiter-friendly project summary

End-to-end manufacturing analytics platform (Python, PostgreSQL, Power BI) over 1.5M+ sensor observations and 180 days of operations: OEE 74.41% decomposed, top causes isolated, reporting automated (6 h to <10 min target), SPC backtest with 100% recall reported transparently at 4.21% precision, and a modeled $1.69M recovery scenario — all validated by 259 tests and 75/75 reconciliation checks.
