# smart_databaser: load-bearing decisions

Process types, columns and archive paths come from `shared/hysprint_utils/process_specs.py`; the Excel_creator sheet builders are loaded by path through `excel_creator_modules.py`.
- "Group" is UI wording for "Set"; `SamplePlan.variation_group_index` keeps "group".
- Experiment Info is row 0 of the process sequence builder (disabled single-option dropdown).
- "Adopt from template batch" always uses `state.whole_experiment_template_batch_id`; "Override from batch..." is the generic picker.
- Preview placeholders are cache-only (`NomadSessionCache.peek_processing_steps`): `_render()` runs on every keystroke and must never fetch.
- A widget whose display depends on `ExperimentState` changed outside its own handlers needs a public `refresh()` wired into `refresh_all` in `app.py`.
- A field marked "varies" is never autofilled; Replicate and Adopt restore the previous state if they fail.
- Before calling something an ingestion bug, force a reprocess and re-fetch: staging lag looks like a defect.
