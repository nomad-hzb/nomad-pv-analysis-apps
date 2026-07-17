"""gui_components.py -- all ipywidgets code lives here and only here."""

from __future__ import annotations

import logging
import urllib.parse

import data_manager as dm_module
import ipywidgets as widgets
import pandas as pd
import plot_manager
from data_manager import MEASUREMENT_TYPE  # noqa: F401
from hysprint_utils.api_calls import get_all_batches_wth_data
from hysprint_utils.batch_selection import create_batch_selection
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import WidgetFactory
from IPython.display import HTML
from IPython.display import display as ipydisplay
from natsort import natsorted

logger = logging.getLogger(__name__)

_WARNING = "\u26a0"

# ---------------------------------------------------------------------------
# Name-function presets (mirroring original plot_options toggle buttons)
# ---------------------------------------------------------------------------

_NAME_FUNCTIONS: dict[str, object] = {
    "sample name": lambda sample_name, cell_name: sample_name,
    "sample + cell": lambda sample_name, cell_name: f"{sample_name} {cell_name}",
    "cell only": lambda sample_name, cell_name: cell_name,
}


class BatchPanel:
    def __init__(self, url: str, token: str, on_load, measurement_type: str):
        self._url = url
        self._token = token
        self._measurement_type = measurement_type

        self._batch_widget = create_batch_selection(url, token, on_load)

        # The SelectMultiple is the second child of the VBox returned by create_batch_selection
        self._selector = self._batch_widget.children[1]

        filter_btn = WidgetFactory.create_button(
            "Show EQE batches", button_style="warning"
        )
        filter_btn.on_click(self._apply_filter)

        self.widget = widgets.VBox([self._batch_widget, filter_btn])

    def _apply_filter(self, _):
        filtered = natsorted(
            get_all_batches_wth_data(self._url, self._token, self._measurement_type)
        )
        self._selector.options = filtered


# ---------------------------------------------------------------------------
# _SampleRow -- one row per sample in the variables panel
# ---------------------------------------------------------------------------


class _SampleRow(widgets.HBox):
    """One row per sample: include-checkbox + sample-id label + name text input."""

    def __init__(
        self,
        sample_id: str,
        name_preset: str,
        data_manager: dm_module.EQEDataManager,
    ):
        self.sample_id = sample_id
        self._dm = data_manager
        self._n_curves = len(data_manager.params.loc[sample_id])
        self._curve_defaults = self._build_curve_defaults()

        self._checkbox = widgets.Checkbox(value=True, indent=False, layout={"width": "40px"})
        self._name_input = widgets.Text(
            value=self._preset_name(sample_id, name_preset, data_manager),
            placeholder="Name in plot",
            layout={"width": "300px"},
        )
        sample_label = widgets.Label(value=sample_id, layout={"width": "220px"})

        super().__init__([self._checkbox, sample_label, self._name_input])

    def _build_curve_defaults(self) -> list[str]:
        defaults = []
        sub_df = self._dm.params.loc[self.sample_id]
        for idx in sub_df.index:
            entry_idx, curve_idx = idx
            try:
                entry_name = self._dm.entries.loc[(self.sample_id, entry_idx), "entry_names"]
            except KeyError:
                entry_name = str(entry_idx)
            defaults.append(entry_name.removeprefix(self.sample_id) + " " + str(curve_idx))
        return defaults

    def update_name(self, preset: str) -> None:
        """Update the name input to match a new preset."""
        self._name_input.value = self._preset_name(self.sample_id, preset, self._dm)

    def get_sample_name(self) -> str:
        return self._name_input.value.strip() or self.sample_id

    def get_cell_selection(self) -> list[bool]:
        return [self._checkbox.value] * self._n_curves

    def get_curve_names(self) -> list[str]:
        return self._curve_defaults

    @staticmethod
    def _preset_name(sample_id: str, preset: str, dm: dm_module.EQEDataManager) -> str:
        item_split = sample_id.split("&")
        batch = item_split[0] if len(item_split) >= 2 else ""
        variable = "&".join(item_split[1:]) if len(item_split) >= 2 else sample_id
        if preset == "batch":
            return batch if batch else "_".join(sample_id.split("_")[:-1])
        if preset == "sample name":
            return variable
        if preset == "sample description":
            try:
                desc = dm.properties.loc[sample_id, "description"]
                return str(desc) if desc else sample_id
            except KeyError:
                return sample_id
        return ""  # "custom"


# ---------------------------------------------------------------------------
# VariablesPanel
# ---------------------------------------------------------------------------


class VariablesPanel:
    """Section 2: dataset naming and per-sample visibility selection."""

    def __init__(self, data_manager: dm_module.EQEDataManager):
        self._dm = data_manager
        self._overview_out = WidgetFactory.create_output(min_height="large", scrollable=True)
        self._overview_out.layout.width = "100%"
        self._rows: list[_SampleRow] = []
        self._rows_box = widgets.VBox()

        self._preset_dd = widgets.Dropdown(
            options=["sample name", "batch", "sample description", "custom"],
            index=0,
            description="name preset:",
            tooltip="Presets for how samples will be named in the plot",
        )
        self._preset_dd.observe(self._on_preset_changed, names=["value"])

        self._build_rows()
        self._refresh_overview()

        self.widget = widgets.VBox(
            [
                self._overview_out,
                widgets.HTML(
                    f"<h3>Dataset names</h3><p>{len(data_manager.sample_ids)} samples found. "
                    "Enter names used in the plots -- curves sharing the same name are grouped.</p>"
                ),
                self._preset_dd,
                self._rows_box,
            ]
        )

    def _build_rows(self):
        self._rows = [
            _SampleRow(sid, self._preset_dd.value, self._dm)
            for sid in self._dm.sample_ids
        ]
        self._rows_box.children = tuple(self._rows)

    def _on_preset_changed(self, _):
        for row in self._rows:
            row.update_name(self._preset_dd.value)

    def apply(self):
        """Apply current widget state to the data manager (called on tab switch)."""
        for row in self._rows:
            self._dm.apply_names_and_selection(
                row.sample_id,
                row.get_sample_name(),
                row.get_cell_selection(),
                row.get_curve_names(),
            )
        self._refresh_overview()

    def _refresh_overview(self):
        overview = self._dm.get_overview_table()
        param_cols = [
            "bandgap_eqe",
            "integrated_jsc",
            "integrated_j0rad",
            "voc_rad",
            "urbach_energy",
            "light_bias",
        ]
        with self._overview_out:
            self._overview_out.clear_output()
            with pd.option_context("display.float_format", "{:,.2e}".format):
                ipydisplay(HTML(overview.to_html()))
                ipydisplay(
                    HTML(self._dm.params.to_html(columns=param_cols, justify="left", border=1))
                )


# ---------------------------------------------------------------------------
# CurvePlotPanel
# ---------------------------------------------------------------------------


class CurvePlotPanel:
    """EQE curve plot with grouping and unit toggle."""

    def __init__(self, data_manager: dm_module.EQEDataManager):
        self._dm = data_manager
        self._plot_out = widgets.Output()
        self._download_area = widgets.Output()

        self._group_cb = widgets.Checkbox(
            description="group curves with same name", indent=False, value=True
        )
        self._stat_toggle = widgets.ToggleButtons(
            description="group type",
            options=[("median, quartiles", False), ("average, std", True)],
            index=0,
        )
        self._unit_toggle = widgets.ToggleButtons(
            options=[
                ("photon energy", ("photon energy / eV", "photon_energy_array")),
                ("wavelength", ("wavelength / nm", "wavelength_array")),
            ],
            index=0,
        )
        self._name_fn_dd = WidgetFactory.create_dropdown(
            options=list(_NAME_FUNCTIONS.keys()),
            description="curve label:",
        )
        self._width = widgets.IntText(value=900, description="width px:", layout={"width": "200px"})
        self._height = widgets.IntText(
            value=500, description="height px:", layout={"width": "200px"}
        )

        refresh_btn = WidgetFactory.create_button("Refresh plot", button_style="primary")
        refresh_btn.on_click(self._refresh)

        self.widget = widgets.VBox(
            [
                self._group_cb,
                self._stat_toggle,
                self._unit_toggle,
                self._name_fn_dd,
                widgets.HBox([self._width, self._height]),
                refresh_btn,
                self._plot_out,
                self._download_area,
            ]
        )

    def refresh(self):
        self._refresh(None)

    def _refresh(self, _):
        axis_title, axis_col = self._unit_toggle.value
        name_fn = _NAME_FUNCTIONS[self._name_fn_dd.value]
        try:
            fig = plot_manager.plot_eqe_curves(
                dm=self._dm,
                axis_col=axis_col,
                axis_title=axis_title,
                width=self._width.value,
                height=self._height.value,
                group_by_name=self._group_cb.value,
                use_std=self._stat_toggle.value,
                name_fn=name_fn,
            )
            with self._plot_out:
                self._plot_out.clear_output()
                fig.show()
        except Exception as exc:
            ErrorHandler.log_error(
                "Failed to generate EQE curve plot", exc, self._plot_out, show_traceback=True
            )


# ---------------------------------------------------------------------------
# BoxPlotPanel
# ---------------------------------------------------------------------------


class BoxPlotPanel:
    """EQE parameter box plot."""

    _BOX_OPTIONS = [
        ("bandgap", ("bandgap_eqe", "bandgap / eV")),
        ("jsc", ("integrated_jsc", "jsc / A/cm\u00b2")),
        ("j0rad", ("integrated_j0rad", "j0rad / A/cm\u00b2")),
        ("voc rad", ("voc_rad", "Voc rad / V")),
        ("urbach energy", ("urbach_energy", "urbach energy / eV")),
    ]

    def __init__(self, data_manager: dm_module.EQEDataManager):
        self._dm = data_manager
        self._plot_out = widgets.Output()
        self._download_area = widgets.Output()

        self._param_toggle = widgets.ToggleButtons(options=self._BOX_OPTIONS, index=1)
        self._param_toggle.observe(lambda _: self._refresh(None), names=["value"])
        self._name_fn_dd = WidgetFactory.create_dropdown(
            options=list(_NAME_FUNCTIONS.keys()),
            description="label style:",
        )
        self._width = widgets.IntText(value=900, description="width px:", layout={"width": "200px"})
        self._height = widgets.IntText(
            value=500, description="height px:", layout={"width": "200px"}
        )

        refresh_btn = WidgetFactory.create_button("Refresh plot", button_style="primary")
        refresh_btn.on_click(self._refresh)

        self.widget = widgets.VBox(
            [
                self._param_toggle,
                self._name_fn_dd,
                widgets.HBox([self._width, self._height]),
                refresh_btn,
                self._plot_out,
                self._download_area,
            ]
        )

    def refresh(self):
        self._refresh(None)

    def _refresh(self, _):
        col, axis_title = self._param_toggle.value
        name_fn = _NAME_FUNCTIONS[self._name_fn_dd.value]
        try:
            fig = plot_manager.plot_boxplot(
                dm=self._dm,
                column_name=col,
                axis_title=axis_title,
                width=self._width.value,
                height=self._height.value,
                name_fn=name_fn,
            )
            with self._plot_out:
                self._plot_out.clear_output()
                fig.show()
        except Exception as exc:
            ErrorHandler.log_error(
                "Failed to generate boxplot", exc, self._plot_out, show_traceback=True
            )


# ---------------------------------------------------------------------------
# DownloadPanel
# ---------------------------------------------------------------------------


class DownloadPanel:
    """Triggers CSV downloads for all four DataFrames."""

    def __init__(self, data_manager: dm_module.EQEDataManager):
        self._dm = data_manager
        self._download_area = widgets.Output()
        btn = WidgetFactory.create_button("Prepare CSV downloads")
        btn.on_click(self._trigger)
        self.widget = widgets.VBox([btn, self._download_area])

    def _trigger(self, _):
        csv_dict = self._dm.to_csv_dict()
        with self._download_area:
            self._download_area.clear_output()
            for filename, content in csv_dict.items():
                encoded = urllib.parse.quote(content)
                ipydisplay(
                    HTML(
                        f'<a download="{filename}" '
                        f'href="data:text/csv;charset=utf-8,{encoded}" '
                        f'target="_blank">Download {filename}</a>'
                    )
                )
