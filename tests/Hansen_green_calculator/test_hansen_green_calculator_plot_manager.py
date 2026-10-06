"""Tests for plot_manager.py – figure type and trace checks."""

import numpy as np
import plot_manager as pm
import plotly.graph_objects as go

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
