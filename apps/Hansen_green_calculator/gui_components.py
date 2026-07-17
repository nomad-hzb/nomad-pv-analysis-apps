"""
gui_components.py
All ipywidgets code.  One Panel class per tab.
No physics/data logic – delegates to data_manager and plot_manager.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

import data_manager as dm
import ipywidgets as widgets
import pandas as pd
import plot_manager as pm
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Shared widget factory (lightweight, no hysprint_utils dependency)
# ---------------------------------------------------------------------------

_BTN_LAYOUT = widgets.Layout(min_width="110px")
_WIDE = widgets.Layout(width="400px")
_MEDIUM = widgets.Layout(width="260px")
_OUTPUT_STD = widgets.Layout(min_height="200px", overflow="auto", border="1px solid #ddd")
_OUTPUT_PLOT = widgets.Layout(min_height="400px")


def _btn(label: str, style: str = "primary", **kw) -> widgets.Button:
    kw.setdefault("layout", _BTN_LAYOUT)
    return widgets.Button(description=label, button_style=style, **kw)


def _dd(options, label: str = "", value=None, width="260px") -> widgets.Dropdown:
    kw = dict(
        options=options,
        description=label,
        layout=widgets.Layout(width=width),
        style={"description_width": "80px"},
    )
    if value is not None:
        kw["value"] = value
    return widgets.Dropdown(**kw)


def _sep(text: str = "") -> widgets.HTML:
    if text:
        return widgets.HTML(f"<hr/><b>{text}</b>")
    return widgets.HTML("<hr/>")


# ---------------------------------------------------------------------------
# Panel 1 – Solvent 3D Explorer
# ---------------------------------------------------------------------------


class SolventExplorerPanel:
    """3D Hansen scatter for db.csv with search highlight."""

    def __init__(self, solvent_dm: dm.SolventDataManager):
        self._dm = solvent_dm
        self._build()

    def _build(self):
        self._search = widgets.Text(
            placeholder="Search name / CAS / synonym …", description="Search:", layout=_WIDE
        )
        self._color_dd = _dd(["None"] + self._dm.numeric_columns, "Colour by:")
        self._plot_out = widgets.Output(layout=_OUTPUT_PLOT)
        self._info_out = widgets.Output(layout=_OUTPUT_STD)
        self._highlighted: list = []

        self._search.observe(self._on_search, names="value")
        self._color_dd.observe(self._refresh, names="value")

        controls = widgets.HBox([self._search, self._color_dd])
        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    "<h3>3D Solvent Space Explorer</h3>"
                    "<p style='color:grey;font-size:0.9em'>Search for compounds to highlight them. "
                    "All solvents remain visible.</p>"
                ),
                controls,
                self._plot_out,
                _sep("Search info"),
                self._info_out,
            ]
        )
        self._refresh(None)

    def _on_search(self, change):
        term = change["new"]
        if term.strip():
            matches = self._dm.search(term)
            self._highlighted = list(matches.index)
            with self._info_out:
                self._info_out.clear_output()
                if matches.empty:
                    logger.info("No compounds found for '%s'.", term)
                else:
                    cols = [c for c in ["Name", "CAS", "D", "P", "H"] if c in matches.columns]
                    ipydisplay(matches[cols].head(10))
        else:
            self._highlighted = []
            self._info_out.clear_output()
        self._refresh(None)

    def _refresh(self, _):
        color = self._color_dd.value if self._color_dd.value != "None" else None
        fig = pm.solvent_3d(self._dm.data, color_by=color, highlighted_idx=self._highlighted)
        with self._plot_out:
            self._plot_out.clear_output(wait=True)
            ipydisplay(fig)


# ---------------------------------------------------------------------------
# Panel 2 – 2D Scatter / Correlation Matrix
# ---------------------------------------------------------------------------


class DataVisualizerPanel:
    """2D scatter + correlation matrix for db.csv."""

    def __init__(self, solvent_dm: dm.SolventDataManager):
        self._dm = solvent_dm
        self._build()

    def _build(self):
        num_cols = self._dm.numeric_columns
        color_opts = ["None"] + num_cols

        self._x_dd = _dd(num_cols, "X axis:", value=num_cols[0] if num_cols else None)
        self._y_dd = _dd(
            num_cols,
            "Y axis:",
            value=num_cols[1] if len(num_cols) > 1 else num_cols[0] if num_cols else None,
        )
        self._c_dd = _dd(color_opts, "Colour:", value="None")
        self._scatter_out = widgets.Output(layout=_OUTPUT_PLOT)
        self._corr_out = widgets.Output(layout=_OUTPUT_PLOT)
        self._corr_btn = _btn("Show Correlation Matrix", "info")

        for w in (self._x_dd, self._y_dd, self._c_dd):
            w.observe(self._refresh_scatter, names="value")
        self._corr_btn.on_click(self._show_corr)

        controls = widgets.HBox([self._x_dd, self._y_dd, self._c_dd])
        self.widget = widgets.VBox(
            [
                widgets.HTML("<h3>2D Property Explorer</h3>"),
                controls,
                self._scatter_out,
                _sep(),
                widgets.HBox([self._corr_btn]),
                self._corr_out,
            ]
        )
        self._refresh_scatter(None)

    def _refresh_scatter(self, _):
        x = self._x_dd.value
        y = self._y_dd.value
        c = self._c_dd.value if self._c_dd.value != "None" else None
        if x and y:
            fig = pm.scatter_2d(self._dm.data, x, y, c)
            with self._scatter_out:
                self._scatter_out.clear_output(wait=True)
                ipydisplay(fig)

    def _show_corr(self, _):
        fig = pm.correlation_matrix(self._dm.data)
        with self._corr_out:
            self._corr_out.clear_output(wait=True)
            ipydisplay(fig)


# ---------------------------------------------------------------------------
# Panel 3 – Blend Optimizer
# ---------------------------------------------------------------------------


class BlendCalculatorPanel:
    """Search solvents, set target HSP, optimise blend."""

    def __init__(self, solvent_dm: dm.SolventDataManager):
        self._dm = solvent_dm
        self._selected: dict = {}  # {row_idx: {'data': pd.Series, 'pct': float}}
        self._last_result: Optional[dict] = None
        self._build()

    def _build(self):
        # Search
        self._search = widgets.Text(placeholder="Search …", description="Search:", layout=_WIDE)
        self._results = widgets.Select(
            options=[], description="Results:", layout=widgets.Layout(width="500px", height="120px")
        )
        self._add_btn = _btn("Add Solvent", "success")
        self._selected_list = widgets.Select(
            options=[],
            description="Selected:",
            layout=widgets.Layout(width="480px", height="120px"),
        )
        self._remove_btn = _btn("Remove", "danger")

        # Target HSP sliders
        self._d_sl = widgets.FloatSlider(
            value=17.0,
            min=0,
            max=35,
            step=0.1,
            description="Target δD:",
            style={"description_width": "80px"},
            layout=widgets.Layout(width="400px"),
        )
        self._p_sl = widgets.FloatSlider(
            value=8.0,
            min=0,
            max=25,
            step=0.1,
            description="Target δP:",
            style={"description_width": "80px"},
            layout=widgets.Layout(width="400px"),
        )
        self._h_sl = widgets.FloatSlider(
            value=10.0,
            min=0,
            max=30,
            step=0.1,
            description="Target δH:",
            style={"description_width": "80px"},
            layout=widgets.Layout(width="400px"),
        )
        self._min_pct = widgets.FloatText(
            value=2.0, description="Min % each:", layout=widgets.Layout(width="180px")
        )
        self._color_dd = _dd(["None"] + self._dm.numeric_columns, "Colour by:")

        # Action buttons
        self._calc_btn = _btn("Optimise Blend", "primary")
        self._save_btn = _btn("Save CSV", "info")
        self._download_area = widgets.Output()

        # Output areas
        self._result_out = widgets.Output(layout=_OUTPUT_STD)
        self._plot_out = widgets.Output(layout=_OUTPUT_PLOT)

        # Wire up
        self._search.observe(self._on_search, names="value")
        self._add_btn.on_click(self._on_add)
        self._remove_btn.on_click(self._on_remove)
        self._calc_btn.on_click(self._on_calc)
        self._save_btn.on_click(self._on_save)
        self._color_dd.observe(self._refresh_plot, names="value")

        left = widgets.VBox(
            [
                widgets.HTML("<h4>Search &amp; Select Solvents</h4>"),
                self._search,
                self._results,
                self._add_btn,
                _sep("Selected"),
                self._selected_list,
                self._remove_btn,
            ],
            layout=widgets.Layout(width="520px"),
        )

        right = widgets.VBox(
            [
                widgets.HTML("<h4>Target Hansen Parameters</h4>"),
                self._d_sl,
                self._p_sl,
                self._h_sl,
                widgets.HBox([self._min_pct, self._color_dd]),
                widgets.HBox([self._calc_btn, self._save_btn]),
                self._download_area,
            ],
            layout=widgets.Layout(width="500px"),
        )

        self.widget = widgets.VBox(
            [
                widgets.HTML("<h3>Blend Optimiser</h3>"),
                widgets.HBox([left, right]),
                _sep("Results"),
                self._result_out,
                _sep("3D Visualisation"),
                self._plot_out,
            ]
        )

    def _on_search(self, change):
        matches = self._dm.search(change["new"])
        if matches.empty:
            self._results.options = []
        else:
            opts = []
            for idx, row in matches.iterrows():
                label = f"{row.get('No.', idx)} – {row.get('Name', '?')}"
                cas = row.get("CAS", "")
                if cas and str(cas) != "nan":
                    label += f" (CAS {cas})"
                opts.append((label, idx))
            self._results.options = opts

    def _on_add(self, _):
        if self._results.value is None:
            return
        idx = self._results.value
        if idx not in self._selected:
            row = self._dm.get_by_index(idx)
            if row is not None:
                self._selected[idx] = {"data": row, "pct": 0.0}
                self._refresh_selected_list()

    def _on_remove(self, _):
        if self._selected_list.value is not None:
            idx = self._selected_list.value
            self._selected.pop(idx, None)
            self._refresh_selected_list()

    def _refresh_selected_list(self):
        opts = []
        for idx, info in self._selected.items():
            name = info["data"].get("Name", f"#{idx}")
            opts.append((f"{name}  ({info['pct']:.1f}%)", idx))
        self._selected_list.options = opts

    def _on_calc(self, _):
        if not self._selected:
            logger.warning("No solvents selected.")
            return
        sel_df = pd.DataFrame([info["data"] for info in self._selected.values()])
        target = [self._d_sl.value, self._p_sl.value, self._h_sl.value]
        fracs, dist, blend_hsp = dm.find_optimal_blend(
            target, sel_df, min_percentage=self._min_pct.value / 100.0
        )

        results_rows = []
        for i, (idx, info) in enumerate(self._selected.items()):
            name = info["data"].get("Name", f"#{idx}")
            pct = fracs[i] * 100
            self._selected[idx]["pct"] = pct
            results_rows.append({"Solvent": name, "Fraction": fracs[i], "Percentage": pct})
        res_df = pd.DataFrame(results_rows)

        logger.info(
            "Target: dD=%.1f dP=%.1f dH=%.1f | Blend: dD=%.2f dP=%.2f dH=%.2f | Ra=%.3f",
            target[0],
            target[1],
            target[2],
            blend_hsp[0],
            blend_hsp[1],
            blend_hsp[2],
            dist,
        )
        with self._result_out:
            self._result_out.clear_output()
            ipydisplay(res_df.round(3))

        self._last_result = dict(
            target=target, blend=blend_hsp, distance=dist, res_df=res_df, sel_df=sel_df
        )
        self._refresh_selected_list()
        self._refresh_plot(None)

    def _refresh_plot(self, _):
        if self._last_result is None:
            return
        color = self._color_dd.value if self._color_dd.value != "None" else None
        fig = pm.blend_3d(
            self._dm.data,
            self._last_result["sel_df"],
            self._last_result["target"],
            self._last_result["blend"],
            color_by=color,
        )
        with self._plot_out:
            self._plot_out.clear_output(wait=True)
            ipydisplay(fig)

    def _on_save(self, _):
        if self._last_result is None:
            logger.warning("No blend result to save; run optimisation first.")
            return
        csv_str = dm.export_blend_csv(
            self._last_result["target"],
            self._last_result["blend"],
            self._last_result["distance"],
            self._last_result["res_df"],
            self._last_result["sel_df"],
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"blend_results_{timestamp}.csv"
        with open(fname, "w") as f:
            f.write(csv_str)
        logger.info("Blend results saved to %s", fname)


# ---------------------------------------------------------------------------
# Panel 4 – Mixture Weighted Average
# ---------------------------------------------------------------------------


class MixtureCalculatorPanel:
    """Manual % blend → weighted average of all properties."""

    def __init__(self, solvent_dm: dm.SolventDataManager):
        self._dm = solvent_dm
        self._selected: dict = {}
        self._pct_inputs: dict = {}
        self._build()

    def _build(self):
        self._search = widgets.Text(placeholder="Search …", description="Search:", layout=_WIDE)
        self._results = widgets.Select(
            options=[], description="Results:", layout=widgets.Layout(width="500px", height="120px")
        )
        self._add_btn = _btn("Add Solvent", "success")
        self._solvent_container = widgets.VBox(
            [widgets.HTML("<b>Selected solvents and percentages</b>")],
            layout=widgets.Layout(width="580px", max_height="280px", overflow="auto"),
        )
        self._status = widgets.HTML('<p style="color:gray">No solvents selected.</p>')
        self._calc_btn = _btn("Calculate Average", "primary")
        self._clear_btn = _btn("Clear All", "warning")
        self._save_btn = _btn("Save CSV", "info")
        self._result_out = widgets.Output(layout=_OUTPUT_STD)
        self._download_area = widgets.Output()
        self._last_results = None

        self._search.observe(self._on_search, names="value")
        self._add_btn.on_click(self._on_add)
        self._calc_btn.on_click(self._on_calc)
        self._clear_btn.on_click(self._on_clear)
        self._save_btn.on_click(self._on_save)

        left = widgets.VBox(
            [
                widgets.HTML("<h4>Search &amp; Add Solvents</h4>"),
                self._search,
                self._results,
                self._add_btn,
            ],
            layout=widgets.Layout(width="520px"),
        )

        right = widgets.VBox(
            [
                widgets.HTML("<h4>Mixture Composition</h4>"),
                self._solvent_container,
                self._status,
                widgets.HBox([self._calc_btn, self._clear_btn, self._save_btn]),
                self._download_area,
            ],
            layout=widgets.Layout(width="600px"),
        )

        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    "<h3>Mixture Weighted Average Calculator</h3>"
                    "<p style='color:grey;font-size:0.9em'>"
                    "Enter volume percentages (must sum to 100 %) then click Calculate.</p>"
                ),
                widgets.HBox([left, right]),
                _sep("Results"),
                self._result_out,
            ]
        )

    def _on_search(self, change):
        matches = self._dm.search(change["new"])
        if matches.empty:
            self._results.options = []
        else:
            opts = []
            for idx, row in matches.iterrows():
                label = f"{row.get('No.', idx)} – {row.get('Name', '?')}"
                opts.append((label, idx))
            self._results.options = opts

    def _on_add(self, _):
        if self._results.value is None:
            return
        idx = self._results.value
        if idx not in self._selected:
            row = self._dm.get_by_index(idx)
            if row is not None:
                self._selected[idx] = {"data": row, "percentage": 0.0}
                self._rebuild_container()

    def _rebuild_container(self):
        children = [widgets.HTML("<b>Solvent</b>")]
        self._pct_inputs = {}
        for idx, info in self._selected.items():
            name = info["data"].get("Name", f"#{idx}")
            lbl = widgets.HTML(
                f"<span style='width:280px;display:inline-block'>{name}</span>",
                layout=widgets.Layout(width="280px"),
            )
            inp = widgets.FloatText(
                value=info["percentage"],
                description="%:",
                layout=widgets.Layout(width="100px"),
                style={"description_width": "25px"},
            )
            rm = widgets.Button(
                description="✖", button_style="danger", layout=widgets.Layout(width="38px")
            )

            def _pct_changed(change, _idx=idx):
                self._selected[_idx]["percentage"] = change["new"]
                self._update_status()

            def _remove(_b, _idx=idx):
                self._selected.pop(_idx, None)
                self._rebuild_container()

            inp.observe(_pct_changed, names="value")
            rm.on_click(_remove)
            self._pct_inputs[idx] = inp
            children.append(widgets.HBox([lbl, inp, rm]))

        self._solvent_container.children = children
        self._update_status()

    def _update_status(self):
        total = sum(info["percentage"] for info in self._selected.values())
        if not self._selected:
            self._status.value = '<p style="color:gray">No solvents selected.</p>'
        elif abs(total - 100) < 0.01:
            self._status.value = f'<p style="color:green">✓ Total: {total:.1f} %</p>'
        else:
            self._status.value = (
                f'<p style="color:{"orange" if total < 100 else "red"}">'
                f"Total: {total:.1f} % (must be 100 %)</p>"
            )

    def _on_clear(self, _):
        self._selected.clear()
        self._rebuild_container()
        self._result_out.clear_output()

    def _on_calc(self, _):
        if not self._selected:
            logger.warning("No solvents added to mixture.")
            return
        total = sum(info["percentage"] for info in self._selected.values())
        if abs(total - 100) > 0.5:
            logger.warning("Percentages sum to %.1f %%; adjust to 100 %%.", total)
            return

        avgs = dm.weighted_average(self._selected, self._dm.data)
        self._last_results = avgs

        logger.info("Mixture weighted averages calculated.")
        with self._result_out:
            self._result_out.clear_output()
            rows = []
            for prop, val in sorted(avgs.items()):
                if val is not None:
                    rows.append({"Property": prop, "Weighted average": f"{val:.4g}"})
            ipydisplay(pd.DataFrame(rows))

    def _on_save(self, _):
        if not self._last_results:
            logger.warning("No mixture result to save; calculate first.")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"mixture_averages_{timestamp}.csv"
        buf = io.StringIO()
        buf.write("# Mixture Composition\n")
        pd.DataFrame(
            [
                {"Solvent": info["data"].get("Name"), "Percentage": info["percentage"]}
                for info in self._selected.values()
            ]
        ).to_csv(buf, index=False)
        buf.write("\n# Weighted Averages\n")
        pd.DataFrame(
            [
                {"Property": k, "Value": v}
                for k, v in sorted(self._last_results.items())
                if v is not None
            ]
        ).to_csv(buf, index=False)
        with open(fname, "w") as f:
            f.write(buf.getvalue())
        logger.info("Mixture averages saved to %s", fname)


# ---------------------------------------------------------------------------
# Panel 5 – Inks (PlottedInks.xlsx Inks sheet)
# ---------------------------------------------------------------------------


class InksPanel:
    """3D plot of Inks with toggleable solute envelopes."""

    def __init__(self, ink_dm: dm.InkDataManager):
        self._dm = ink_dm
        self._build()

    def _build(self):
        self._sphere_toggle = widgets.ToggleButton(
            value=True,
            description="Show Solute Volumes",
            button_style="info",
            icon="eye",
            layout=widgets.Layout(width="180px"),
        )
        self._sphere_toggle.observe(self._refresh, names="value")
        self._plot_out = widgets.Output(layout=_OUTPUT_PLOT)

        self.widget = widgets.VBox(
            [
                widgets.HTML("<h3>Inks – Hansen Space (coloured by Solute)</h3>"),
                widgets.HBox([self._sphere_toggle]),
                self._plot_out,
            ]
        )
        self._refresh(None)

    def _refresh(self, _):
        fig = pm.inks_3d(self._dm.data, show_spheres=self._sphere_toggle.value)
        with self._plot_out:
            self._plot_out.clear_output(wait=True)
            ipydisplay(fig)


# ---------------------------------------------------------------------------
# Panel 6 – Perovskite (Sheet2 / Sheet3)
# ---------------------------------------------------------------------------


class PerovskitePanel:
    """3D perovskite solute/solvent plot with multi-solute filter."""

    def __init__(self, perov_dm: dm.PerovskiteDataManager):
        self._dm = perov_dm
        self._build()

    def _build(self):
        self._sheet_dd = _dd(["Sheet2", "Sheet3"], "Dataset:")
        self._color_dd = _dd(
            self._dm.color_columns("Sheet2"),
            "Colour by:",
            value=self._dm.color_columns("Sheet2")[0] if self._dm.color_columns("Sheet2") else None,
        )
        self._solute_box = widgets.SelectMultiple(
            options=self._dm.solute_list("Sheet2"),
            value=self._dm.solute_list("Sheet2"),
            description="Solutes:",
            layout=widgets.Layout(height="150px", width="360px"),
            style={"description_width": "70px"},
        )
        self._sel_all = _btn("Select All", "info", layout=widgets.Layout(width="120px"))
        self._clear_sel = _btn("Clear", "warning", layout=widgets.Layout(width="80px"))
        self._plot_out = widgets.Output(layout=_OUTPUT_PLOT)

        self._sheet_dd.observe(self._on_sheet_change, names="value")
        self._color_dd.observe(self._refresh, names="value")
        self._solute_box.observe(self._refresh, names="value")
        self._sel_all.on_click(lambda _: self._set_all_solutes(True))
        self._clear_sel.on_click(lambda _: self._set_all_solutes(False))

        controls = widgets.VBox(
            [
                widgets.HBox([self._sheet_dd, self._color_dd]),
                widgets.HTML("<small>Hold Ctrl/⌘ to select multiple solutes</small>"),
                self._solute_box,
                widgets.HBox([self._sel_all, self._clear_sel]),
            ]
        )

        self.widget = widgets.VBox(
            [
                widgets.HTML("<h3>Perovskite Solute / Solvent – Hansen Space</h3>"),
                controls,
                self._plot_out,
            ]
        )
        self._refresh(None)

    def _on_sheet_change(self, change):
        sheet = change["new"]
        solutes = self._dm.solute_list(sheet)
        colors = self._dm.color_columns(sheet)
        self._solute_box.options = solutes
        self._solute_box.value = solutes
        self._color_dd.options = colors
        if colors:
            self._color_dd.value = colors[0]
        self._refresh(None)

    def _set_all_solutes(self, select_all: bool):
        if select_all:
            self._solute_box.value = self._solute_box.options
        else:
            self._solute_box.value = []

    def _refresh(self, _):
        sheet = self._sheet_dd.value
        color = self._color_dd.value
        solutes = list(self._solute_box.value)
        df = self._dm.get_sheet(sheet)
        if df.empty:
            logger.warning("Sheet '%s' not loaded or empty.", sheet)
            return
        fig = pm.perovskite_3d(df, color_by=color, selected_solutes=solutes or None)
        with self._plot_out:
            self._plot_out.clear_output(wait=True)
            ipydisplay(fig)
