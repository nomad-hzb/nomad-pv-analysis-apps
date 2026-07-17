"""
Plot management for MPPT Analysis App
"""

import logging

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)


class PlotManager:
    """Handles all plotting operations for the MPPT analysis"""

    def __init__(self, app_state, data_manager):
        self.app_state = app_state
        self.data_manager = data_manager

    def get_fitted_curve_data(self, sample_id, curve_id, variable):
        """Generate fitted curve data for a specific sample and curve"""
        if not self.app_state.fitted_curves_data:
            return None, None

        # Look for the fitted curve data
        curve_key = (sample_id, curve_id)
        if curve_key not in self.app_state.fitted_curves_data:
            return None, None

        fitted_data = self.app_state.fitted_curves_data[curve_key]

        if variable == "power_density":
            return fitted_data["time"], fitted_data["fitted_power"]
        else:
            # For other variables (voltage, current_density), we don't have fitted curves
            # so return None to indicate no fitted data available
            return None, None

    def plot_curves(self, variable, style, show_fits=False):
        """Generate curve plots based on selected variable and style"""
        # Get the curve data for selected samples
        selected_data = self.data_manager.get_selected_curve_data(
            self.app_state.data["curves"],
            self.app_state.data["sample_ids"],
            self.app_state.data["selected_samples"],
            variable,
        )

        if not selected_data:
            logger.warning("No curve data found for selected samples")
            return []

        # Generate plots based on style
        if style == "individual":
            return self.plot_individual_curves(selected_data, variable, show_fits)
        elif style == "together":
            return [self.plot_all_together(selected_data, variable, show_fits)]
        elif style == "by_sample":
            return self.plot_by_sample(selected_data, variable, show_fits)
        elif style == "area_quartiles":
            return self.plot_area_quartiles(selected_data, variable)
        elif style == "area_std":
            return self.plot_area_std(selected_data, variable)
        return []

    def plot_individual_curves(self, data, variable, show_fits=False):
        """Plot each curve individually; returns list of go.Figure"""
        figs = []
        for i, curve in enumerate(data):
            fig = go.Figure()

            fig.add_trace(
                go.Scatter(
                    x=curve["time"],
                    y=curve["data"],
                    mode="lines",
                    name="Data",
                    line=dict(width=2, color="blue"),
                )
            )

            if show_fits:
                fit_time, fit_data = self.get_fitted_curve_data(
                    curve["sample_id"], curve["curve_id"], variable
                )
                if fit_time is not None and fit_data is not None:
                    fig.add_trace(
                        go.Scatter(
                            x=fit_time,
                            y=fit_data,
                            mode="lines",
                            name="Fit",
                            line=dict(width=2, color="red", dash="dash"),
                        )
                    )

            fig.update_layout(
                title=f"{variable.replace('_', ' ').title()} - {curve['sample_id']} Curve {curve['curve_id']}",  # noqa: E501
                xaxis_title="Time (hours)",
                yaxis_title=variable.replace("_", " ").title(),
                width=800,
                height=500,
            )

            figs.append(fig)
        return figs

    def plot_all_together(self, data, variable, show_fits=False):
        """Plot all curves together in one plot; returns go.Figure"""
        fig = go.Figure()

        for curve in data:
            fig.add_trace(
                go.Scatter(
                    x=curve["time"],
                    y=curve["data"],
                    mode="lines",
                    name=f"{curve['sample_id']}_curve_{curve['curve_id']}",
                    line=dict(width=1.5),
                    opacity=0.7,
                )
            )

            if show_fits:
                fit_time, fit_data = self.get_fitted_curve_data(
                    curve["sample_id"], curve["curve_id"], variable
                )
                if fit_time is not None and fit_data is not None:
                    fig.add_trace(
                        go.Scatter(
                            x=fit_time,
                            y=fit_data,
                            mode="lines",
                            name=f"Fit_{curve['sample_id']}_curve_{curve['curve_id']}",
                            line=dict(width=1.5, dash="dash"),
                            opacity=0.7,
                        )
                    )

        fig.update_layout(
            title=f"{variable.replace('_', ' ').title()} - All Curves",
            xaxis_title="Time (hours)",
            yaxis_title=variable.replace("_", " ").title(),
            width=1000,
            height=600,
        )

        return fig

    def plot_by_sample(self, data, variable, show_fits=False):
        """Plot curves grouped by sample; returns list of go.Figure"""
        samples = {}
        for curve in data:
            if curve["sample_id"] not in samples:
                samples[curve["sample_id"]] = []
            samples[curve["sample_id"]].append(curve)

        figs = []
        for sample_id, curves in samples.items():
            fig = go.Figure()

            for curve in curves:
                fig.add_trace(
                    go.Scatter(
                        x=curve["time"],
                        y=curve["data"],
                        mode="lines",
                        name=f"Data Curve {curve['curve_id']}",
                        line=dict(width=2),
                    )
                )

                if show_fits:
                    fit_time, fit_data = self.get_fitted_curve_data(
                        curve["sample_id"], curve["curve_id"], variable
                    )
                    if fit_time is not None and fit_data is not None:
                        fig.add_trace(
                            go.Scatter(
                                x=fit_time,
                                y=fit_data,
                                mode="lines",
                                name=f"Fit Curve {curve['curve_id']}",
                                line=dict(width=2, dash="dash"),
                            )
                        )

            fig.update_layout(
                title=f"{variable.replace('_', ' ').title()} - {sample_id}",
                xaxis_title="Time (hours)",
                yaxis_title=variable.replace("_", " ").title(),
                width=800,
                height=500,
            )

            figs.append(fig)
        return figs

    def plot_area_quartiles(self, data, variable):
        """Plot with median line and quartile area; returns list of go.Figure"""
        samples = {}
        for curve in data:
            if curve["sample_id"] not in samples:
                samples[curve["sample_id"]] = []
            samples[curve["sample_id"]].append(curve)

        figs = []
        for sample_id, curves in samples.items():
            if len(curves) < 2:
                continue

            all_times = np.concatenate([curve["time"] for curve in curves])
            time_grid = np.linspace(all_times.min(), all_times.max(), 200)

            interpolated_data = np.array(
                [np.interp(time_grid, curve["time"], curve["data"]) for curve in curves]
            )

            median = np.median(interpolated_data, axis=0)
            q25 = np.percentile(interpolated_data, 25, axis=0)
            q75 = np.percentile(interpolated_data, 75, axis=0)

            fig = go.Figure()

            fig.add_trace(
                go.Scatter(
                    x=np.concatenate([time_grid, time_grid[::-1]]),
                    y=np.concatenate([q75, q25[::-1]]),
                    fill="toself",
                    fillcolor="rgba(0,100,80,0.2)",
                    line=dict(color="rgba(255,255,255,0)"),
                    showlegend=True,
                    name="25th-75th percentile",
                )
            )

            fig.add_trace(
                go.Scatter(
                    x=time_grid,
                    y=median,
                    mode="lines",
                    name="Median",
                    line=dict(color="blue", width=3),
                )
            )

            fig.update_layout(
                title=f"{variable.replace('_', ' ').title()} - {sample_id} (Median + Quartiles)",
                xaxis_title="Time (hours)",
                yaxis_title=variable.replace("_", " ").title(),
                width=800,
                height=500,
            )

            figs.append(fig)
        return figs

    def plot_area_std(self, data, variable):
        """Plot with mean line and standard deviation area; returns list of go.Figure"""
        samples = {}
        for curve in data:
            if curve["sample_id"] not in samples:
                samples[curve["sample_id"]] = []
            samples[curve["sample_id"]].append(curve)

        figs = []
        for sample_id, curves in samples.items():
            if len(curves) < 2:
                continue

            all_times = np.concatenate([curve["time"] for curve in curves])
            time_grid = np.linspace(all_times.min(), all_times.max(), 200)

            interpolated_data = np.array(
                [np.interp(time_grid, curve["time"], curve["data"]) for curve in curves]
            )

            mean = np.mean(interpolated_data, axis=0)
            std = np.std(interpolated_data, axis=0)

            fig = go.Figure()

            fig.add_trace(
                go.Scatter(
                    x=np.concatenate([time_grid, time_grid[::-1]]),
                    y=np.concatenate([mean + std, (mean - std)[::-1]]),
                    fill="toself",
                    fillcolor="rgba(0,100,80,0.2)",
                    line=dict(color="rgba(255,255,255,0)"),
                    showlegend=True,
                    name="±1 Standard Deviation",
                )
            )

            fig.add_trace(
                go.Scatter(
                    x=time_grid, y=mean, mode="lines", name="Mean", line=dict(color="red", width=3)
                )
            )

            fig.update_layout(
                title=f"{variable.replace('_', ' ').title()} - {sample_id} (Mean ± Std Dev)",
                xaxis_title="Time (hours)",
                yaxis_title=variable.replace("_", " ").title(),
                width=800,
                height=500,
            )

            figs.append(fig)
        return figs

    def plot_histograms(self):
        """Generate histograms for t80 and ts parameters; returns go.Figure or None"""
        if not self.app_state.has_fit_results():
            logger.warning("No fitting results available for histograms")
            return None

        available_params = list(self.app_state.fit_results.columns)
        hist_params = [p for p in ["t80", "T80", "tS", "ts", "Ts80"] if p in available_params]

        if not hist_params:
            logger.warning("No time parameters (t80, T80, tS, Ts80) found in fitting results")
            return None

        n_params = len(hist_params)
        cols = min(2, n_params)
        rows = (n_params + 1) // 2

        fig = make_subplots(
            rows=rows, cols=cols, subplot_titles=[f"{param} Distribution" for param in hist_params]
        )

        for i, param in enumerate(hist_params):
            row = i // cols + 1
            col = i % cols + 1

            values = self.app_state.fit_results[param].dropna()

            if len(values) > 0:
                fig.add_trace(
                    go.Histogram(x=values, name=param, opacity=0.7, nbinsx=20), row=row, col=col
                )

        fig.update_layout(
            title="Parameter Distributions from Curve Fitting",
            height=400 * rows,
            width=800,
            showlegend=False,
        )

        for i, param in enumerate(hist_params):
            row = i // cols + 1
            col = i % cols + 1
            fig.update_xaxes(title_text="%s (hours)" % param, row=row, col=col)
            fig.update_yaxes(title_text="Count", row=row, col=col)

        return fig
