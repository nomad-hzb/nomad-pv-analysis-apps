# Global_analyzer: traps of this app

- The default aggregation is "All Points", so a row is a pixel, not a sample. Any statistic must group by `sample_id` (`ml_analysis.sample_groups`); never merge on `sample_id` when it can repeat, look rows up by position or `source_index`.
- `set_analysis_columns` takes `results_groups` and `metadata_groups` before `categorical_cols`: pass categoricals by keyword.
- Filters and sample exclusions are staged on the Filters tab and applied only on "Confirm filters" (`_applied_filters`, `_applied_excluded`); Plotting and every analysis tab read the applied ones.
- The `batch` column is the batch the sample was selected from (`DataManager.sample_batch`), not the sub-batch read from the sample id.
- `app.py` (`SampleDataExplorer`) is split into mixins: `analysis_data_handlers.py` (Filters and Analysis Data tab handlers) and `analysis_handlers.py` (downloads, correlations, Random Forest, Bayesian optimization, experimental tools). They rely on the attributes `SampleDataExplorer.__init__` sets up; the test conftest puts the app folder on `sys.path`, so they resolve by bare name.
