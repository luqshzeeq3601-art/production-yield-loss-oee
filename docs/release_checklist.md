# Release Checklist — before making the repository public

- [ ] Choose and commit a `LICENSE` (code/docs only; UCI datasets stay excluded — see `docs/data_sources.md`)
- [ ] Assemble `powerbi/OEE_EarlyWarning.pbix` per `powerbi/desktop_assembly_guide.md`; export a PDF for viewers without Power BI
- [ ] Capture dashboard screenshots into `screenshots/` (folder exists and is intentionally empty)
- [ ] Re-run `py -3.11 -m pytest -q -W error` from a clean checkout and confirm green
- [ ] Confirm `git status` shows no credentials, dumps, caches, or raw datasets
- [ ] Confirm `data/raw/` and `data/interim/` stay untracked/local
- [ ] Review `docs/resume_bullets.md` figures against `reports/impact_metrics.csv` one last time
- [ ] Do NOT create Git tags/releases from this checklist alone — release only when explicitly authorized

## Current preparation gate

POWERBI-PREP: 275 tests under Python 3.11; live persistent PostgreSQL DQ 65/65; artifact reconciliation 75/75; 25 relations and seven page dependencies. See `reports/powerbi_preparation_validation.json`. Desktop/PBIX assembly remains the next task.
