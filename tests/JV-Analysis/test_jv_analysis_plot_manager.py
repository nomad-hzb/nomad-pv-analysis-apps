# tests/jv_analysis/test_plot_manager.py
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
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
            rows.append(
                {
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
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def curves_df():
    """Minimal curves DataFrame with voltage/current data."""
    rows = []
    voltages = np.linspace(0, 1.1, 20)
    for sample in ["SampleA", "SampleB"]:
        for direction in ["Reverse", "Forward"]:
            for v in voltages:
                rows.append(
                    {
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
                    }
                )
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


def test_showing_plots_again_closes_the_previous_ones():
    import ipywidgets as widgets
    import plotly.graph_objects as go
    from resizable_plot_utility import ResizablePlotManager

    ResizablePlotManager.display_plots_resizable([go.Figure()], ["first"])
    first = list(ResizablePlotManager._live_widgets)
    assert any(isinstance(widget, widgets.HTML) for widget in first)  # the title too
    ResizablePlotManager.display_plots_resizable([go.Figure()], ["second"])
    assert all(widget.comm is None for widget in first)  # closed
    assert ResizablePlotManager._live_widgets and ResizablePlotManager._live_widgets[0] not in first


# ---------------------------------------------------------------------------
# Hover: every box plot names the sample, cell, scan direction, status and variable of
# each point (#279)
# ---------------------------------------------------------------------------

BIG_FOUR = ["Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)"]
HOVER = {
    "Sample": "sample",
    "Cell": "cell",
    "Scan direction": "direction",
    "Status": "status",
    "Variable": "condition",
}


@pytest.fixture
def hover_df(jvc_df):
    """Distinct sample per row, two cells, statuses and variables, unique values, and one
    missing PCE value."""
    df = pd.concat([jvc_df, jvc_df.assign(cell="C2")], ignore_index=True)
    n = len(df)
    df["sample"] = [f"S{i}" for i in range(n)]
    df["status"] = ["L1", "L2"] * (n // 2)
    df["condition"] = ["A", "A", "B", "B"] * (n // 4)
    df["Voc(V)"] = [1.0 + i / 100 for i in range(n)]
    df["Jsc(mA/cm2)"] = [-(20.0 + i) for i in range(n)]
    df["FF(%)"] = [70.0 + i for i in range(n)]
    df["PCE(%)"] = [10.0 + i for i in range(n)]
    df.loc[1, "PCE(%)"] = np.nan  # dropped from y; must not shift the names after it
    return df


def _resolve(text, x, custom):
    """A hovertemplate value: customdata, x, or a literal px wrote into the template."""
    if text.startswith("%{customdata["):
        return str(custom[int(text[len("%{customdata[") : text.index("]")])])
    if text == "%{x}":
        return str(x)
    return text


def _points(fig):
    """(value, {hover label: shown value}) for every drawn point of every box trace."""
    out = []
    for trace in fig.data:
        fields = {}
        for part in trace.hovertemplate.replace("<extra></extra>", "").split("<br>"):
            for sep in (": ", "="):
                label, _, value = part.partition(sep)
                if label in HOVER:
                    fields[label] = value
                    break
        assert set(fields) == set(HOVER), trace.hovertemplate
        xs = trace.x if trace.x is not None else [None] * len(trace.y)
        for x, value, custom in zip(xs, trace.y, trace.customdata):
            if not pd.isna(value):
                shown = {label: _resolve(v, x, custom) for label, v in fields.items()}
                out.append((float(value), shown))
    return out


def _check(fig_or_figs, df, columns=("PCE(%)",)):
    figs = fig_or_figs if isinstance(fig_or_figs, list) else [fig_or_figs]
    expected = {}
    for column in columns:
        rows = df.dropna(subset=[column])
        values = rows[column].abs() if column.startswith("Jsc") else rows[column]
        for value, (_, row) in zip(values, rows.iterrows()):
            expected[float(value)] = {label: str(row[col]) for label, col in HOVER.items()}
    points = [p for fig in figs for p in _points(fig)]
    assert sorted(v for v, _ in points) == sorted(expected)
    for value, shown in points:
        assert shown == expected[value], value


@pytest.mark.parametrize("direction_split", [False, True])
def test_boxplot_hover_matches_the_point_when_a_value_is_missing(
    plot_manager, hover_df, filtered_info, direction_split
):
    fig, _, _ = plot_manager.create_boxplot(
        data=hover_df,
        var_x="condition",
        var_y="pce",
        filtered_info=filtered_info,
        direction_split=direction_split,
    )
    _check(fig, hover_df)


@pytest.mark.parametrize("combination_type", ["sg", "cg", "bg"])
def test_combination_plots_hover_names_every_field(
    plot_manager, hover_df, filtered_info, combination_type
):
    figs, _ = plot_manager.create_combination_plots(
        hover_df, "pce", combination_type, filtered_info
    )
    assert figs
    _check(figs, hover_df)


def test_triple_combination_plot_hover_names_every_field(plot_manager, hover_df, filtered_info):
    figs, _ = plot_manager.create_triple_combination_plots(hover_df, "pce", "sgc", filtered_info)
    _check(figs, hover_df)


@pytest.mark.parametrize("direction_split", [False, True])
@pytest.mark.parametrize("var_x", ["condition", "sample", "status"])
def test_big_four_subplots_hover_names_every_field(
    plot_manager, hover_df, filtered_info, direction_split, var_x
):
    fig, _ = plot_manager.create_voc_jsc_ff_pce_subplots(
        hover_df, filtered_info, var_x=var_x, direction_split=direction_split
    )
    _check(fig, hover_df, BIG_FOUR)
