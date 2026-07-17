"""
Application state management for MPPT Analysis App
"""


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

    def set_fit_results(self, fit_results, fitted_curves_data, model):
        """Set fitting results"""
        self.fit_results = fit_results
        self.fitted_curves_data = fitted_curves_data
        self.last_fitted_model = model

    def get_sample_ids_list(self):
        """Get list of sample IDs"""
        sample_ids = self.data.get("sample_ids")
        if sample_ids is None:
            return []
        return list(sample_ids) if hasattr(sample_ids, "__iter__") else [sample_ids]
