# tests/jv_analysis/test_plot_manager.py
import pandas as pd
import numpy as np
import pytest
import plotly.graph_objects as go

from plot_manager import PlotManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plot_manager():
    return PlotManager()


@pytest.fixture
def jvc_df():
    """Minimal JVC DataFrame with two samples, two directions each."""
    rows = []
    for sample in ["SampleA", "SampleB"]:
        for direction in ["Reverse", "Forward"]:
            rows.append({
                "Voc(V)": 1.05 if direction == "Reverse" else 0.98,
                "Jsc(mA/cm2)": -18.3,
                "FF(%)": 78.4,
                "PCE(%)": 15.1 if direction == "Reverse" else 12.8,
                "V_mpp(V)": 0.87,
                "J_mpp(mA/cm2)": -17.4,
                "P_mpp(mW/cm2)": 15.1,
                "R_series(Ohmcm2)": 4.2,
                "R_shunt(Ohmcm2)": 1200.0,
                "sample": sample,
                "batch": "Batch01",
                "condition": "Slot_SAM",
                "cell": "C1",
                "direction": direction,
                "ilum": "1sun",
                "status": "working",
                "sample_id": f"sid-{sample}-{direction}",
            })
    return pd.DataFrame(rows)


@pytest.fixture
def curves_df():
    """Minimal curves DataFrame with voltage/current data."""
    rows = []
    voltages = np.linspace(0, 1.1, 20)
    for sample in ["SampleA", "SampleB"]:
        for direction in ["Reverse", "Forward"]:
            for v in voltages:
                rows.append({
                    "index": f"{sample}_C1",
                    "sample": sample,
                    "batch": "Batch01",
                    "condition": "Slot_SAM",
                    "variable": "Slot_SAM",
                    "cell": "C1",
                    "direction": direction,
                    "ilum": "1sun",
                    "sample_id": f"sid-{sample}-{direction}",
                    "status": "working",
                    "voltage": v,
                    "current": -18.3 * (1 - (v / 1.1) ** 2),
                })
    return pd.DataFrame(rows)


@pytest.fixture
def filtered_info(jvc_df):
    """Tuple of (omitted_df, filter_strings) as expected by plot functions."""
    return (pd.DataFrame(columns=jvc_df.columns), ["PCE(%) < 40", "FF(%) < 89"])


# ---------------------------------------------------------------------------
# PlotManager.create_boxplot
# ---------------------------------------------------------------------------

class TestCreateBoxplot:
    def test_returns_figure(self, plot_manager, jvc_df, filtered_info):
        fig, _, _ = plot_manager.create_boxplot(
            data=jvc_df,
            var_x="condition",
            var_y="pce",
            filtered_info=filtered_info,
        )
        assert isinstance(fig, go.Figure)

    def test_figure_has_box_trace(self, plot_manager, jvc_df, filtered_info):
        fig, _, _ = plot_manager.create_boxplot(
            data=jvc_df,
            var_x="condition",
            var_y="pce",
            filtered_info=filtered_info,
        )
        trace_types = [type(t).__name__ for t in fig.data]
        assert "Box" in trace_types

    def test_figure_has_data(self, plot_manager, jvc_df, filtered_info):
        fig, _, _ = plot_manager.create_boxplot(
            data=jvc_df,
            var_x="condition",
            var_y="pce",
            filtered_info=filtered_info,
        )
        assert len(fig.data) > 0


# ---------------------------------------------------------------------------
# PlotManager.create_histogram
# ---------------------------------------------------------------------------

class TestCreateHistogram:
    def test_returns_figure(self, plot_manager, jvc_df):
        fig, _ = plot_manager.create_histogram(df=jvc_df, var_y="pce")
        assert isinstance(fig, go.Figure)

    def test_figure_has_histogram_trace(self, plot_manager, jvc_df):
        fig, _ = plot_manager.create_histogram(df=jvc_df, var_y="pce")
        trace_types = [type(t).__name__ for t in fig.data]
        assert "Histogram" in trace_types


# ---------------------------------------------------------------------------
# PlotManager.create_jv_best_device_plot
# ---------------------------------------------------------------------------

class TestCreateJVBestDevicePlot:
    def test_returns_figure(self, plot_manager, jvc_df, curves_df):
        fig, _ = plot_manager.create_jv_best_device_plot(
            jvc_data=jvc_df,
            curves_data=curves_df,
        )
        assert isinstance(fig, go.Figure)

    def test_figure_has_scatter_trace(self, plot_manager, jvc_df, curves_df):
        fig, _ = plot_manager.create_jv_best_device_plot(
            jvc_data=jvc_df,
            curves_data=curves_df,
        )
        trace_types = [type(t).__name__ for t in fig.data]
        assert "Scatter" in trace_types

    def test_figure_has_data(self, plot_manager, jvc_df, curves_df):
        fig, _ = plot_manager.create_jv_best_device_plot(
            jvc_data=jvc_df,
            curves_data=curves_df,
        )
        assert len(fig.data) > 0


# ---------------------------------------------------------------------------
# PlotManager.create_jv_all_cells_plot
# ---------------------------------------------------------------------------

class TestCreateJVAllCellsPlot:
    def test_returns_figure(self, plot_manager, jvc_df, curves_df):
        fig, _ = plot_manager.create_jv_all_cells_plot(
            jvc_data=jvc_df,
            curves_data=curves_df,
        )
        assert isinstance(fig, go.Figure)


# ---------------------------------------------------------------------------
# PlotManager.create_correlation_plot
# ---------------------------------------------------------------------------

class TestCreateCorrelationPlot:
    def test_returns_figure(self, plot_manager, jvc_df, filtered_info):
        fig, _ = plot_manager.create_correlation_plot(
            data=jvc_df,
            filtered_info=filtered_info,
        )
        assert isinstance(fig, go.Figure)
