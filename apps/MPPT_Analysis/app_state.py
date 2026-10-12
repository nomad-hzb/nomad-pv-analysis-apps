"""
Application state management for MPPT Analysis App
"""

import pandas as pd


class AppState:
    """Centralized state management for the MPPT Analysis application"""

    def __init__(self):
        # Core data storage
        self.data = {
            "curves": None,  # MPPT curve data
            "sample_ids": None,  # Available sample IDs
            "entries": None,  # Entry descriptions
            "properties": None,  # Sample properties
            "selected_samples": [],  # Samples with at least one selected curve
            "selected_curves": None,  # [(sample_id, curve_id)]; None = every curve
            "custom_names": {},  # Custom sample names
        }

        # Fitting results
        self.fit_results = None
        self.fitted_curves_data = {}
        self.last_fitted_model = None

        # Outlier-cleaned power_density, {(sample_id, curve_id): array with NaN at
        # the removed points}. A layer on top of data["curves"], which stays raw.
        self.cleaned_power = {}

        # UI state
        self.sample_selectors = {}

        # API configuration
        self.url = None
        self.token = None

    def reset_data(self):
        """Reset all data to initial state"""
        self.data = {
            "curves": None,
            "sample_ids": None,
            "entries": None,
            "properties": None,
            "selected_samples": [],
            "selected_curves": None,
            "custom_names": {},
        }
        self.fit_results = None
        self.fitted_curves_data = {}
        self.last_fitted_model = None
        self.cleaned_power = {}
        self.sample_selectors = {}

    def has_curves_data(self):
        """Check if curve data is loaded"""
        return self.data.get("curves") is not None

    def has_selected_samples(self):
        """Check if samples are selected"""
        return len(self.data.get("selected_samples", [])) > 0

    def has_fit_results(self):
        """Check if fitting results are available"""
        return self.fit_results is not None and len(self.fit_results) > 0

    def selected_curve_ids(self, sample_id):
        """Curve ids of one sample that are selected, or None for "all of them"."""
        selected = self.data.get("selected_curves")
        if selected is None:
            return None
        return [cid for sid, cid in selected if sid == sample_id]

    def get_selected_curves_count(self):
        """Number of individually selected curves (None selection counts nothing here)."""
        selected = self.data.get("selected_curves")
        return len(selected) if selected is not None else 0

    def get_selected_samples_count(self):
        """Get count of selected samples"""
        return len(self.data.get("selected_samples", []))

    def get_fit_results_count(self):
        """Get count of fitted curves"""
        return len(self.fit_results) if self.fit_results is not None else 0

    def set_api_config(self, url, token):
        """Set API configuration"""
        self.url = url
        self.token = token

    def load_curves_data(self, curves, sample_ids, entries, properties):
        """Load curve data into state"""
        self.data["curves"] = curves
        self.data["sample_ids"] = sample_ids
        self.data["entries"] = entries
        self.data["properties"] = properties

    def set_selected_samples(self, selected_samples, custom_names=None, selected_curves=None):
        """Set selected samples and custom names.

        selected_curves: [(sample_id, curve_id)] of the individual measurements
        (pixels) to analyse. None keeps the older meaning "every curve of every
        selected sample".
        """
        self.data["selected_samples"] = selected_samples
        self.data["selected_curves"] = None if selected_curves is None else list(selected_curves)
        if custom_names:
            self.data["custom_names"] = custom_names

    def set_fit_results(self, fitted_curves_data):
        """Replace every fit result at once (the 'apply to all' path)."""
        self.fitted_curves_data = dict(fitted_curves_data)
        self._rebuild_fit_results_df()

    def update_curve_fit_results(self, fits_by_key):
        """Replace the fits of the given (sample_id, curve_id) keys, leaving every
        other curve's fit untouched (the individual, one-curve-at-a-time path)."""
        self.fitted_curves_data.update(fits_by_key)
        self._rebuild_fit_results_df()

    def set_cleaned_power(self, cleaned_by_key):
        """Store outlier-cleaned power_density for {(sample_id, curve_id): array}.

        The fit of every cleaned curve is dropped: it was made on the previous data
        and would no longer match what the preview and the tables show.
        """
        self.cleaned_power.update(cleaned_by_key)
        self._drop_fits(cleaned_by_key)

    def clear_cleaned_power(self, keys=None):
        """Go back to the raw data for the given keys (all of them when None)."""
        keys = (
            list(self.cleaned_power)
            if keys is None
            else [k for k in keys if k in self.cleaned_power]
        )
        for key in keys:
            del self.cleaned_power[key]
        self._drop_fits(keys)

    def _drop_fits(self, keys):
        dropped = [key for key in keys if key in self.fitted_curves_data]
        if dropped:
            for key in dropped:
                del self.fitted_curves_data[key]
            self._rebuild_fit_results_df()

    def get_sample_fit_results(self, sample_id):
        """Return {curve_id: fit_dict} for whatever has already been fitted for one sample."""
        return {key[1]: fit for key, fit in self.fitted_curves_data.items() if key[0] == sample_id}

    def _rebuild_fit_results_df(self):
        """Recompute self.fit_results from self.fitted_curves_data - the single
        source of truth is fitted_curves_data; the DataFrame is a derived view
        kept around because the Statistical Summary / histograms / download
        sheet already consume it in that shape."""
        rows = []
        for (sample_id, curve_id), fit in self.fitted_curves_data.items():
            row = {
                "sample_id": sample_id,
                "curve_id": curve_id,
                "model": fit["model"].abbreviated_name,
                "n_frames": len(fit["time"]),
                "max_time_h": float(fit["time"].max()) if len(fit["time"]) else None,
            }
            row.update(fit.get("params", {}))
            rows.append(row)
        self.fit_results = pd.DataFrame(rows) if rows else pd.DataFrame()
        if self.fitted_curves_data:
            self.last_fitted_model = next(iter(self.fitted_curves_data.values()))["model"]

    def get_sample_ids_list(self):
        """Get list of sample IDs"""
        sample_ids = self.data.get("sample_ids")
        if sample_ids is None:
            return []
        return list(sample_ids) if hasattr(sample_ids, "__iter__") else [sample_ids]
