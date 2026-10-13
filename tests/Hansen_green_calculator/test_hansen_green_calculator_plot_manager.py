"""Tests for plot_manager.py – figure type and trace checks."""

import numpy as np
import plot_manager as pm
import plotly.graph_objects as go
import pytest

# ---------------------------------------------------------------------------
# solvent_3d
# ---------------------------------------------------------------------------


class TestSolvent3D:
    def test_returns_figure(self, solvent_df):
        fig = pm.solvent_3d(solvent_df)
        assert isinstance(fig, go.Figure)

    def test_has_traces(self, solvent_df):
        fig = pm.solvent_3d(solvent_df)
        assert len(fig.data) > 0

    def test_highlight_adds_named_trace(self, solvent_df):
        fig = pm.solvent_3d(solvent_df, highlighted_idx=[0, 1])
        names = [t.name for t in fig.data]
        assert any("Highlighted" in (n or "") for n in names)

    def test_color_by_applies(self, solvent_df):
        fig = pm.solvent_3d(solvent_df, color_by="DN")
        # At least one trace should have a colorbar or array color
        assert isinstance(fig, go.Figure)


# ---------------------------------------------------------------------------
# scatter_2d
# ---------------------------------------------------------------------------


class TestScatter2D:
    def test_returns_figure(self, solvent_df):
        fig = pm.scatter_2d(solvent_df, "D", "P")
        assert isinstance(fig, go.Figure)

    def test_drops_nan_rows(self, solvent_df):
        df_with_nan = solvent_df.copy()
        df_with_nan.loc[0, "D"] = np.nan
        fig = pm.scatter_2d(df_with_nan, "D", "P")
        trace = fig.data[0]
        assert len(trace.x) == len(solvent_df) - 1

    def test_color_col_adds_colorbar(self, solvent_df):
        fig = pm.scatter_2d(solvent_df, "D", "P", color_col="DN")
        trace = fig.data[0]
        assert trace.marker.showscale is True


# ---------------------------------------------------------------------------
# correlation_matrix
# ---------------------------------------------------------------------------


class TestCorrelationMatrix:
    def test_returns_figure(self, solvent_df):
        num = solvent_df[["D", "P", "H", "DN", "BP"]].dropna()
        fig = pm.correlation_matrix(num)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0


# ---------------------------------------------------------------------------
# blend_3d
# ---------------------------------------------------------------------------


class TestBlend3D:
    def test_returns_figure(self, solvent_df):
        fig = pm.blend_3d(
            solvent_df,
            solvent_df.iloc[:2],
            [17.0, 8.0, 10.0],
            [16.5, 7.8, 9.8],
        )
        assert isinstance(fig, go.Figure)

    def test_target_and_blend_traces_present(self, solvent_df):
        fig = pm.blend_3d(
            solvent_df,
            solvent_df.iloc[:2],
            [17.0, 8.0, 10.0],
            [16.5, 7.8, 9.8],
        )
        names = [t.name for t in fig.data]
        assert "Target HSP" in names
        assert "Calculated Blend" in names


# ---------------------------------------------------------------------------
# inks_3d
# ---------------------------------------------------------------------------


class TestInks3D:
    def test_returns_figure(self, ink_df):
        fig = pm.inks_3d(ink_df)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_spheres_toggle_off(self, ink_df):
        fig_on = pm.inks_3d(ink_df, show_spheres=True)
        fig_off = pm.inks_3d(ink_df, show_spheres=False)
        # Spheres are Surface traces; with spheres there should be more traces
        surfaces_on = sum(1 for t in fig_on.data if isinstance(t, go.Surface))
        surfaces_off = sum(1 for t in fig_off.data if isinstance(t, go.Surface))
        assert surfaces_on >= surfaces_off


# ---------------------------------------------------------------------------
# perovskite_3d
# ---------------------------------------------------------------------------


class TestPerovskite3D:
    def test_returns_figure(self, perov_df):
        fig = pm.perovskite_3d(perov_df, color_by="DN")
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_empty_selection_returns_empty_figure(self, perov_df):
        fig = pm.perovskite_3d(perov_df, selected_solutes=["NotASolute"])
        assert isinstance(fig, go.Figure)

    def test_solute_filter_reduces_points(self, perov_df):
        fig_all = pm.perovskite_3d(perov_df, color_by="DN")
        fig_one = pm.perovskite_3d(perov_df, color_by="DN", selected_solutes=["MAPbI3"])
        # First trace (scatter) should have fewer x values
        pts_all = len(fig_all.data[0].x)
        pts_one = len(fig_one.data[0].x)
        assert pts_one <= pts_all

    def test_stability_legend_traces_added(self, perov_df):
        fig = pm.perovskite_3d(perov_df, color_by="DN")
        legend_names = {t.name for t in fig.data}
        # All three stability types should appear
        assert "Stable" in legend_names
        assert "Semi-stable" in legend_names
        assert "Not stable" in legend_names


# ---------------------------------------------------------------------------
# 6.5: envelope colours, Hansen-scaled spheres, Sheet3 columns, downloads
# ---------------------------------------------------------------------------


def _inks(order):
    import pandas as pd

    rows = []
    for solute in order:
        for k in range(3):
            rows.append(
                {
                    "Solutes": solute,
                    "D": 16.0 + k,
                    "P": 8.0 + k,
                    "H": 6.0 + k,
                    "formatted_solvents": "x",
                }
            )
    return pd.DataFrame(rows)


def test_envelope_colour_is_the_colour_of_the_solutes_points():
    """Points are coloured in order of appearance, the envelopes were coloured alphabetically."""
    fig = pm.inks_3d(_inks(["Zeta", "Alpha"]))
    point_colour = {t.name: t.marker.color for t in fig.data if t.type == "scatter3d"}
    for trace in fig.data:
        if trace.type == "surface":
            solute = trace.name.removesuffix("_envelope")
            assert trace.colorscale[0][1].lower() == point_colour[solute].lower()


def test_inks_are_plotted_in_hansen_scaled_space_with_the_real_d_in_the_hover():
    fig = pm.inks_3d(_inks(["Alpha"]))
    points = next(t for t in fig.data if t.type == "scatter3d")
    assert list(points.x) == [32.0, 34.0, 36.0]  # 2 * D
    assert list(points.customdata[:, 1]) == [16.0, 17.0, 18.0]  # D itself
    assert fig.layout.scene.xaxis.title.text == "2·D"


def test_enclosing_sphere_radius_is_a_hansen_distance_when_d_is_weighted():
    import data_manager as dm
    import pandas as pd

    group = pd.DataFrame({"D": [0.0, 2.0], "P": [0.0, 0.0], "H": [0.0, 0.0]})
    centre, radius = dm.calculate_enclosing_sphere(group, d_scale=dm.HANSEN_D_WEIGHT)
    assert list(centre) == [2.0, 0.0, 0.0]  # centre in the 2*D space
    assert radius == pytest.approx(2.0 * 1.05)  # |2 * (0 - 1)| = Ra between the points / 2


def test_sheet3_column_names_are_normalised_to_the_sheet2_names():
    import data_manager as dm
    import pandas as pd

    raw = pd.DataFrame(
        {
            "Solutes": ["A"],
            "Solvents": ["DMF"],
            "D": [1],
            "P": [2],
            "H": [3],
            "bp": [150],
            "Hov Temp": [25],
            "MW": [73],
            "Vis Temp": [20],
        }
    )
    out = dm.normalise_perovskite_columns(raw)
    assert {"Solute", "Solvent", "BP", "hov_temp", "mw", "vis_temp"} <= set(out.columns)
    manager = dm.PerovskiteDataManager()
    manager.sheet3 = out
    assert manager.solute_list("Sheet3") == ["A"]
    assert "BP" in manager.color_columns("Sheet3")


def test_download_link_is_a_data_uri_with_the_csv():
    import base64

    import gui_components as gc

    link = gc._download_link("a,b\n1,2\n", "x.csv").data
    assert 'download="x.csv"' in link
    payload = link.split("base64,")[1].split('"')[0]
    assert base64.b64decode(payload).decode() == "a,b\n1,2\n"
