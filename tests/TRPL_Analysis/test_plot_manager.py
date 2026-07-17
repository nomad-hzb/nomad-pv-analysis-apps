"""PlotManager: figure type and trace checks."""
import numpy as np
import plotly.graph_objects as go
import pytest
from plot_manager import TRPLPlotManager


def test_trpl_traces_returns_figure(sample_df):
    fig = TRPLPlotManager.trpl_traces(sample_df, y_col="counts")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == len(sample_df)


def test_trpl_traces_normalized_max_is_one(sample_df):
    fig = TRPLPlotManager.trpl_traces(sample_df, y_col="counts", normalize=True)
    for trace in fig.data:
        if trace.y is not None and len(trace.y) > 0:
            assert max(trace.y) <= 1.0 + 1e-9


def test_differential_lifetime_time_returns_figure():
    t = np.linspace(0, 100e-9, 50)
    tau = np.linspace(1e-7, 1e-8, 49)
    fig = TRPLPlotManager.differential_lifetime_time([tau], [t], ["S001"])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1


def test_differential_lifetime_density_returns_figure():
    n = np.logspace(14, 17, 50)
    tau = np.linspace(1e-7, 1e-8, 49)
    fig = TRPLPlotManager.differential_lifetime_density([tau], [n], ["S001"])
    assert isinstance(fig, go.Figure)
    assert fig.layout.xaxis.type == "log"
    assert fig.layout.yaxis.type == "log"


def test_scatter_returns_figure(sample_df):
    # ns_per_bin is a scalar column available in the fixture
    fig = TRPLPlotManager.scatter(sample_df, x_col="ns_per_bin", y_col="ns_per_bin")
    assert isinstance(fig, go.Figure)


def test_box_returns_figure(sample_df):
    fig = TRPLPlotManager.box(sample_df, y_col="ns_per_bin", x_col="variation")
    assert isinstance(fig, go.Figure)
