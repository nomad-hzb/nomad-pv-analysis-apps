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
            "selected_samples": [],  # User-selected samples
            "custom_names": {},  # Custom sample names
        }

        # Fitting results
        self.fit_results = None
        self.fitted_curves_data = {}
        self.last_fitted_model = None

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
            "custom_names": {},
        }
        self.fit_results = None
        self.fitted_curves_data = {}
        self.last_fitted_model = None
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

    def set_selected_samples(self, selected_samples, custom_names=None):
        """Set selected samples and custom names"""
        self.data["selected_samples"] = selected_samples
        if custom_names:
            self.data["custom_names"] = custom_names

    def set_fit_results(self, fitted_curves_data):
        """Replace every fit result at once (the 'apply to all' path)."""
        self.fitted_curves_data = dict(fitted_curves_data)
        self._rebuild_fit_results_df()

    def update_sample_fit_results(self, sample_id, fits_by_curve):
        """Replace one sample's fits, leaving every other sample's fits untouched
        (the individual, one-sample-at-a-time fitting path)."""
        self.fitted_curves_data = {
            key: fit for key, fit in self.fitted_curves_data.items() if key[0] != sample_id
        }
        for curve_id, fit in fits_by_curve.items():
            self.fitted_curves_data[(sample_id, curve_id)] = fit
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
