"""
gui_components.py
-----------------
All ipywidgets code. Imports data_manager and plot_manager as plain names.

Each panel exposes a .widget property. The key UX changes vs v1:
  - Preset dropdown populates the manual-entry fields; "Add" commits to the list.
  - The active list renders one row per item with an inline "✕" delete button.
"""

from __future__ import annotations

import logging

import data_manager as dm
import ipywidgets as widgets
import plot_manager as pm
import plotly.graph_objects as go
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Small HTML helpers
# ---------------------------------------------------------------------------


def _section_header(text: str) -> widgets.HTML:
    return widgets.HTML(
        value=(
            f"<h3 style='margin:8px 0 4px 0; font-size:14px; "
            f"border-bottom:1px solid #ccc; padding-bottom:4px'>{text}</h3>"
        )
    )


def _status(message: str, ok: bool = True) -> widgets.HTML:
    colour = "#2d7a2d" if ok else "#b33"
    return widgets.HTML(
        value=f"<p style='color:{colour}; margin:2px 0; font-size:12px'>{message}</p>"
    )


def _subheader(text: str) -> widgets.HTML:
    return widgets.HTML(
        value=f"<p style='font-size:12px; font-weight:bold; margin:6px 0 2px 0'>{text}</p>"
    )


# ---------------------------------------------------------------------------
# Reusable: list with per-row delete buttons
# ---------------------------------------------------------------------------


class DeletableList:
    """
    Renders a VBox where each row is:
        [label text]  [✕ button]

    Calls on_delete(index) when the delete button is clicked, then
    re-renders automatically.
    """

    def __init__(self, get_rows_fn, on_delete_fn, empty_text: str = "None added yet.") -> None:
        self._get_rows = get_rows_fn  # () -> list[str]
        self._on_delete = on_delete_fn  # (int) -> None
        self._empty_text = empty_text
        self._container = widgets.VBox(layout=widgets.Layout(gap="2px"))
        self.refresh()

    def refresh(self) -> None:
        rows = self._get_rows()
        if not rows:
            self._container.children = [
                widgets.HTML(value=f"<i style='font-size:12px; color:#888'>{self._empty_text}</i>")
            ]
            return

        row_widgets = []
        for i, label in enumerate(rows):
            idx = i  # capture for closure
            btn = widgets.Button(
                description="✕",
                button_style="",
                layout=widgets.Layout(width="32px", height="28px", padding="0"),
                style={"button_color": "#ffdddd"},
            )
            btn.on_click(lambda _b, i=idx: self._handle_delete(i))
            text = widgets.HTML(
                value=f"<span style='font-size:12px; line-height:28px'>{label}</span>",
                layout=widgets.Layout(flex="1"),
            )
            row_widgets.append(
                widgets.HBox(
                    [btn, text],
                    layout=widgets.Layout(align_items="center", gap="4px"),
                )
            )
        self._container.children = row_widgets

    def _handle_delete(self, index: int) -> None:
        self._on_delete(index)
        self.refresh()

    @property
    def widget(self) -> widgets.VBox:
        return self._container


# ---------------------------------------------------------------------------
# MaterialPanel
# ---------------------------------------------------------------------------


def _mat_row_label(m: dm.Material) -> str:
    return f"<b>{m.name}</b> &nbsp; σ<sub>p</sub>={m.polar} &nbsp; σ<sub>d</sub>={m.dispersive} &nbsp; θ={m.theta}°"


class MaterialPanel:
    def __init__(self, data_mgr: dm.WettingDataManager) -> None:
        self._dm = data_mgr

        # --- preset dropdown ------------------------------------------------
        self._preset_dd = widgets.Dropdown(
            options=dm.PRESET_MATERIAL_OPTIONS,
            value=dm.PRESET_MATERIAL_OPTIONS[0],
            description="Preset:",
            layout=widgets.Layout(width="300px"),
            style={"description_width": "55px"},
        )
        self._preset_dd.observe(self._on_preset_change, names="value")

        # --- manual entry fields --------------------------------------------
        self._name = widgets.Text(
            value="",
            placeholder="Material name",
            description="Name:",
            layout=widgets.Layout(width="280px"),
            style={"description_width": "55px"},
        )
        self._polar = widgets.FloatText(
            value=0.0,
            description="Polar:",
            layout=widgets.Layout(width="190px"),
            style={"description_width": "55px"},
        )
        self._dispersive = widgets.FloatText(
            value=0.0,
            description="Dispersive:",
            layout=widgets.Layout(width="210px"),
            style={"description_width": "75px"},
        )
        self._theta = widgets.FloatSlider(
            value=0.0,
            min=0.0,
            max=180.0,
            step=1.0,
            description="θ (°):",
            continuous_update=False,
            layout=widgets.Layout(width="320px"),
            style={"description_width": "45px"},
        )

        # --- add button -----------------------------------------------------
        self._add_btn = widgets.Button(
            description="Add Material",
            button_style="primary",
            layout=widgets.Layout(width="130px"),
        )
        self._add_btn.on_click(self._on_add)

        # --- status ---------------------------------------------------------
        self._status_out = widgets.Output()

        # --- deletable list -------------------------------------------------
        self._list = DeletableList(
            get_rows_fn=lambda: [_mat_row_label(m) for m in self._dm.materials],
            on_delete_fn=self._dm.remove_material,
            empty_text="No materials added yet.",
        )

    def _on_preset_change(self, change) -> None:
        preset = dm.get_preset_material(change["new"])
        if preset is None:
            return
        self._name.value = preset["name"]
        self._polar.value = preset["polar"]
        self._dispersive.value = preset["dispersive"]
        self._theta.value = preset["theta"]

    def _on_add(self, _b) -> None:
        ok, msg = self._dm.add_material(
            name=self._name.value.strip() or "Unnamed",
            polar=self._polar.value,
            dispersive=self._dispersive.value,
            theta=self._theta.value,
        )
        with self._status_out:
            self._status_out.clear_output(wait=True)
            ipydisplay(_status(msg, ok))
        if ok:
            self._list.refresh()
            # Reset preset dropdown so user can pick another
            self._preset_dd.value = dm.PRESET_MATERIAL_OPTIONS[0]

    def refresh(self) -> None:
        self._list.refresh()

    @property
    def widget(self) -> widgets.VBox:
        return widgets.VBox(
            [
                _section_header("Materials"),
                _subheader("Pick a preset or enter values manually:"),
                self._preset_dd,
                self._name,
                widgets.HBox([self._polar, self._dispersive]),
                self._theta,
                self._add_btn,
                self._status_out,
                _subheader("Active materials:"),
                self._list.widget,
            ],
            layout=widgets.Layout(min_width="360px", padding="8px"),
        )


# ---------------------------------------------------------------------------
# SolventPanel
# ---------------------------------------------------------------------------


def _sol_row_label(s: dm.Solvent) -> str:
    return f"<b>{s.name}</b> &nbsp; σ<sub>p</sub>={s.polar} &nbsp; σ<sub>d</sub>={s.dispersive}"


class SolventPanel:
    def __init__(self, data_mgr: dm.WettingDataManager) -> None:
        self._dm = data_mgr

        self._preset_dd = widgets.Dropdown(
            options=dm.PRESET_SOLVENT_OPTIONS,
            value=dm.PRESET_SOLVENT_OPTIONS[0],
            description="Preset:",
            layout=widgets.Layout(width="300px"),
            style={"description_width": "55px"},
        )
        self._preset_dd.observe(self._on_preset_change, names="value")

        self._name = widgets.Text(
            value="",
            placeholder="Solvent name",
            description="Name:",
            layout=widgets.Layout(width="280px"),
            style={"description_width": "55px"},
        )
        self._polar = widgets.FloatText(
            value=0.0,
            description="Polar:",
            layout=widgets.Layout(width="190px"),
            style={"description_width": "55px"},
        )
        self._dispersive = widgets.FloatText(
            value=0.0,
            description="Dispersive:",
            layout=widgets.Layout(width="210px"),
            style={"description_width": "75px"},
        )

        self._add_btn = widgets.Button(
            description="Add Solvent",
            button_style="primary",
            layout=widgets.Layout(width="120px"),
        )
        self._add_btn.on_click(self._on_add)

        self._status_out = widgets.Output()

        self._list = DeletableList(
            get_rows_fn=lambda: [_sol_row_label(s) for s in self._dm.solvents],
            on_delete_fn=self._dm.remove_solvent,
            empty_text="No solvents added yet.",
        )

    def _on_preset_change(self, change) -> None:
        preset = dm.get_preset_solvent(change["new"])
        if preset is None:
            return
        self._name.value = preset["name"]
        self._polar.value = preset["polar"]
        self._dispersive.value = preset["dispersive"]

    def _on_add(self, _b) -> None:
        ok, msg = self._dm.add_solvent(
            name=self._name.value.strip() or "Unnamed",
            polar=self._polar.value,
            dispersive=self._dispersive.value,
        )
        with self._status_out:
            self._status_out.clear_output(wait=True)
            ipydisplay(_status(msg, ok))
        if ok:
            self._list.refresh()
            self._preset_dd.value = dm.PRESET_SOLVENT_OPTIONS[0]

    def refresh(self) -> None:
        self._list.refresh()

    @property
    def widget(self) -> widgets.VBox:
        return widgets.VBox(
            [
                _section_header("Solvents / Liquid Points"),
                _subheader("Pick a preset or enter values manually:"),
                self._preset_dd,
                self._name,
                widgets.HBox([self._polar, self._dispersive]),
                self._add_btn,
                self._status_out,
                _subheader("Active solvents:"),
                self._list.widget,
            ],
            layout=widgets.Layout(min_width="360px", padding="8px"),
        )


# ---------------------------------------------------------------------------
# PlotSettingsPanel  (unchanged in structure, no refresh calls needed here)
# ---------------------------------------------------------------------------


class PlotSettingsPanel:
    def __init__(
        self,
        data_mgr: dm.WettingDataManager,
        plot_panel: "PlotPanel",
        material_panel: MaterialPanel,
        solvent_panel: SolventPanel,
    ) -> None:
        self._dm = data_mgr
        self._plot_panel = plot_panel
        self._mat_panel = material_panel
        self._sol_panel = solvent_panel

        self._title = widgets.Text(
            value="Wetting Envelope",
            description="Title:",
            layout=widgets.Layout(width="320px"),
        )
        self._correction_exp = widgets.FloatSlider(
            value=2.0,
            min=1.0,
            max=2.0,
            step=0.01,
            description="Correction exp:",
            continuous_update=False,
            layout=widgets.Layout(width="360px"),
            style={"description_width": "110px"},
        )

        self._plot_btn = widgets.Button(
            description="Plot",
            button_style="success",
            layout=widgets.Layout(width="100px"),
        )
        self._clear_btn = widgets.Button(
            description="Clear All",
            button_style="danger",
            layout=widgets.Layout(width="100px"),
        )
        self._plot_btn.on_click(self._on_plot)
        self._clear_btn.on_click(self._on_clear)

    def _on_plot(self, _b) -> None:
        if not self._dm.has_data:
            self._plot_panel.show_message("Add at least one material before plotting.")
            return
        fig = pm.WettingPlotManager.wetting_envelope(
            materials=self._dm.materials,
            solvents=self._dm.solvents,
            title=self._title.value,
            correction_exp=self._correction_exp.value,
        )
        self._plot_panel.show_figure(fig)

    def _on_clear(self, _b) -> None:
        self._dm.clear()
        self._mat_panel.refresh()
        self._sol_panel.refresh()
        self._plot_panel.clear()

    @property
    def widget(self) -> widgets.VBox:
        return widgets.VBox(
            [
                _section_header("Plot Settings"),
                self._title,
                self._correction_exp,
                widgets.HBox([self._plot_btn, self._clear_btn], layout=widgets.Layout(gap="8px")),
            ],
            layout=widgets.Layout(padding="8px"),
        )


# ---------------------------------------------------------------------------
# PlotPanel  (unchanged)
# ---------------------------------------------------------------------------


class PlotPanel:
    def __init__(self) -> None:
        self._out = widgets.Output(
            layout=widgets.Layout(
                min_height="540px",
                border="1px solid #ddd",
            )
        )

    def show_figure(self, fig: go.Figure) -> None:
        with self._out:
            self._out.clear_output(wait=True)
            ipydisplay(go.FigureWidget(fig))

    def show_message(self, msg: str) -> None:
        with self._out:
            self._out.clear_output(wait=True)
            ipydisplay(widgets.HTML(value=f"<p style='color:#b33; padding:12px'>{msg}</p>"))

    def clear(self) -> None:
        with self._out:
            self._out.clear_output()

    @property
    def widget(self) -> widgets.VBox:
        return widgets.VBox([self._out])
