"""
gui_components.py
All ipywidgets UI panels. Each panel is a self-contained class with a .widget property.
When migrating to Panel (or another framework), only this file needs to change.
"""

import base64
import io
import logging

import ipywidgets as widgets
import pandas as pd
from data_manager import MEASUREMENT_TYPE
from hysprint_utils.api_calls import get_all_batches_wth_data
from hysprint_utils.batch_selection import create_batch_selection
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import WidgetFactory
from IPython.display import HTML
from IPython.display import display as ipydisplay
from natsort import natsorted

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BatchPanel
# ---------------------------------------------------------------------------


class BatchPanel:
    """
    Batch selection UI that wraps the existing create_batch_selection utility
    and adds an optional AbsPL-specific filter button on top.
    """

    def __init__(self, url: str, token: str, on_load, measurement_type: str):
        self._url = url
        self._token = token
        self._measurement_type = measurement_type

        self._batch_widget = create_batch_selection(url, token, on_load)

        # The SelectMultiple is the second child of the VBox returned by create_batch_selection
        self._selector = self._batch_widget.children[1]

        filter_btn = WidgetFactory.create_button(
            "Show only batches with EQE data", button_style="warning"
        )
        filter_btn.on_click(self._apply_filter)

        self._container = widgets.VBox([self._batch_widget, filter_btn])

    def _apply_filter(self, _):
        filtered = natsorted(
            get_all_batches_wth_data(self._url, self._token, self._measurement_type)
        )
        self._selector.options = filtered

    def _build(self):
        base = create_batch_selection(self._url, self._token, self._on_load)

        # grab the SelectMultiple so we can update its options after filtering
        self._batch_selector = next(
            (c for c in base.children if isinstance(c, widgets.SelectMultiple)), None
        )
        total = len(self._batch_selector.options) if self._batch_selector else 0

        self._filter_btn = WidgetFactory.create_button(
            description=f"Filter: show only batches with AbsPL data ({total} total)",
            button_style="info",
            min_width=False,
        )
        self._filter_btn.layout.width = "450px"
        self._filter_status = WidgetFactory.create_output(border=False)
        self._filter_btn.on_click(self._run_filter)
        self._total = total

        self._container = widgets.VBox(
            [
                widgets.HTML(
                    f"<p>Select from all {total} available batches, "
                    "or use the filter button to narrow to batches with AbsPL data:</p>"
                ),
                self._filter_btn,
                self._filter_status,
                base,
            ]
        )

    def _run_filter(self, b):
        self._filter_btn.disabled = True
        self._filter_btn.description = "Filtering in progress..."

        logger.info("Finding batches with AbsPL data...")

        try:
            valid = get_all_batches_wth_data(self._url, self._token, MEASUREMENT_TYPE)
            if self._batch_selector:
                self._batch_selector.options = natsorted(valid)

            logger.info("Done: %d of %d batches have AbsPL data.", len(valid), self._total)
            self._filter_btn.description = "Done: %d batches with AbsPL data" % len(valid)

        except Exception as e:
            logger.error("Error during filtering: %s", e)
            self._filter_btn.disabled = False
            self._filter_btn.description = "Filter: show only batches with AbsPL data (retry)"

    @property
    def widget(self):
        return self._container


# ---------------------------------------------------------------------------
# FilterPanel
# ---------------------------------------------------------------------------


class FilterPanel:
    """Interactive range filter for any numeric column in the loaded data."""

    def __init__(self, data_manager):
        self.dm = data_manager
        self._build()

    def _build(self):
        numeric_cols = self.dm.numeric_columns

        self._col_dd = WidgetFactory.create_dropdown(
            options=numeric_cols, description="Column:", width="wide"
        )
        self._col_dd.style = {"description_width": "initial"}

        self._min_input = widgets.FloatText(
            description="Min:",
            layout=widgets.Layout(width="200px"),
            style={"description_width": "40px"},
        )
        self._max_input = widgets.FloatText(
            description="Max:",
            layout=widgets.Layout(width="200px"),
            style={"description_width": "40px"},
        )

        apply_btn = WidgetFactory.create_button("Apply Filter", button_style="success")
        reset_btn = WidgetFactory.create_button("Reset Filters", button_style="danger")
        show_btn = WidgetFactory.create_button("Show Data", button_style="info")

        self._status_out = WidgetFactory.create_output(border=False)
        self._data_out = WidgetFactory.create_output()

        self._col_dd.observe(self._update_range, names="value")
        apply_btn.on_click(self._apply)
        reset_btn.on_click(self._reset)
        show_btn.on_click(self._show_data)

        self._update_range({"new": self._col_dd.value})

        self._container = widgets.VBox(
            [
                widgets.HTML("<p>Select a column and specify a range to keep:</p>"),
                self._col_dd,
                widgets.HBox([self._min_input, self._max_input]),
                widgets.HBox([apply_btn, reset_btn, show_btn]),
                self._status_out,
                self._data_out,
            ]
        )

    def _update_range(self, change):
        col = change["new"]
        if col and self.dm.is_loaded and col in self.dm.data.columns:
            mn, mx = self.dm.get_column_range(col)
            self._min_input.value = mn
            self._max_input.value = mx

    def _apply(self, b):
        col = self._col_dd.value
        success, msg = self.dm.apply_filter(col, self._min_input.value, self._max_input.value)
        logger.info("%s", msg)
        if success:
            self._update_range({"new": col})

    def _reset(self, b):
        self.dm.reset_filters()
        self._update_range({"new": self._col_dd.value})
        logger.info("All filters reset. Original data restored.")
        with self._data_out:
            self._data_out.clear_output()

    def _show_data(self, b):
        with self._data_out:
            self._data_out.clear_output(wait=True)
            ipydisplay(self.dm.data.head(10))
            if len(self.dm.data) > 10:
                logger.info("Showing first 10 of %d rows.", len(self.dm.data))

    @property
    def widget(self):
        return self._container


# ---------------------------------------------------------------------------
# PlottingPanel
# ---------------------------------------------------------------------------


class PlottingPanel:
    """Scatter and box plot controls."""

    def __init__(self, data_manager, plot_manager):
        self.dm = data_manager
        self.pm = plot_manager
        self._build()

    def _build(self):
        numeric_cols = self.dm.numeric_columns
        category_cols = self.dm.category_columns
        all_cols = numeric_cols + category_cols

        self._x_dd = WidgetFactory.create_dropdown(
            options=all_cols, description="X-axis:", width="wide"
        )
        self._x_dd.value = numeric_cols[0] if numeric_cols else all_cols[0]

        self._y_dd = WidgetFactory.create_dropdown(
            options=numeric_cols, description="Y-axis:", width="wide"
        )
        self._y_dd.value = numeric_cols[1] if len(numeric_cols) > 1 else numeric_cols[0]

        self._color_dd = WidgetFactory.create_dropdown(
            options=["None"] + category_cols, description="Color by:", width="wide"
        )
        self._color_dd.value = "variation"

        self._type_dd = WidgetFactory.create_dropdown(
            options=["Scatter plot", "Box plot"],
            description="Plot type:",
            width="wide",
        )

        plot_btn = WidgetFactory.create_button("Generate Plot", button_style="success")
        plot_btn.on_click(self._plot)

        self._plot_out = WidgetFactory.create_output(min_height="large", border=False)

        self._container = widgets.VBox(
            [
                widgets.HBox([self._x_dd, self._y_dd]),
                widgets.HBox([self._color_dd, self._type_dd]),
                plot_btn,
                self._plot_out,
            ]
        )

    def _plot(self, b):
        with self._plot_out:
            self._plot_out.clear_output(wait=True)
            x = self._x_dd.value
            y = self._y_dd.value
            color = None if self._color_dd.value == "None" else self._color_dd.value
            try:
                if self._type_dd.value == "Scatter plot":
                    fig = self.pm.scatter(self.dm.data, x, y, color)
                else:
                    fig = self.pm.box(self.dm.data, y, color)
                ipydisplay(fig)
            except Exception as e:
                ErrorHandler.log_error("generating plot", e, self._plot_out)

    @property
    def widget(self):
        return self._container


# ---------------------------------------------------------------------------
# SpectralPanel
# ---------------------------------------------------------------------------


class SpectralPanel:
    """Wavelength vs. luminescence spectral plot controls."""

    def __init__(self, data_manager, plot_manager):
        self.dm = data_manager
        self.pm = plot_manager
        self._build()

    def _build(self):
        spectral_cols = self.dm.get_available_spectral_columns()
        variations = self.dm.get_variations()

        if not spectral_cols:
            self._container = widgets.HTML(
                "<p>No spectral data columns (luminescence_flux_density / "
                "raw_spectrum_counts) found in the loaded data.</p>"
            )
            return

        self._variation_sel = widgets.SelectMultiple(
            options=variations,
            value=variations[: min(5, len(variations))],
            description="Variations:",
            layout=widgets.Layout(width="60%", height="120px"),
        )

        self._scale_radio = WidgetFactory.create_radio_buttons(
            options=["linear", "log"], description="Y scale:", value="linear"
        )
        self._normalize_cb = widgets.Checkbox(
            value=False, description="Normalize spectra", indent=False
        )
        self._y_col_dd = WidgetFactory.create_dropdown(
            options=spectral_cols,
            description="Data column:",
            width="wide",
            value=spectral_cols[0],
        )

        plot_btn = WidgetFactory.create_button("Generate Spectral Plot", button_style="success")
        plot_btn.on_click(self._plot)

        self._status_out = WidgetFactory.create_output(border=False)
        self._plot_out = WidgetFactory.create_output(min_height="large", border=False)

        self._container = widgets.VBox(
            [
                widgets.HTML("<p>Select variations to plot:</p>"),
                self._variation_sel,
                widgets.HBox([self._scale_radio, self._normalize_cb]),
                self._y_col_dd,
                plot_btn,
                self._status_out,
                self._plot_out,
            ]
        )

    def _plot(self, b):
        selected = list(self._variation_sel.value)
        if not selected:
            logger.warning("No variation selected for plotting.")
            return

        logger.info("Generating plot...")

        try:
            fig = self.pm.spectral(
                self.dm.data,
                selected,
                self._y_col_dd.value,
                scale=self._scale_radio.value,
                normalize=self._normalize_cb.value,
            )
            with self._plot_out:
                self._plot_out.clear_output(wait=True)
                ipydisplay(fig)
            with self._status_out:
                self._status_out.clear_output(wait=True)
        except Exception as e:
            ErrorHandler.log_error(
                "generating spectral plot", e, self._status_out, show_traceback=True
            )

    @property
    def widget(self):
        return self._container


# ---------------------------------------------------------------------------
# DataTablePanel
# ---------------------------------------------------------------------------


class DataTablePanel:
    """
    Data table view with column selection and CSV / pivot-table export.
    The download_area Output widget is self-contained here (no globals needed).
    """

    def __init__(self, data_manager):
        self.dm = data_manager
        self._build()

    def _build(self):
        columns = self.dm.data.columns.tolist()
        numeric_cols = self.dm.numeric_columns
        category_cols = self.dm.category_columns

        self._col_sel = widgets.SelectMultiple(
            options=columns,
            value=columns[:5],
            description="Columns:",
            layout=widgets.Layout(width="50%", height="100px"),
        )

        update_btn = WidgetFactory.create_button("Update Table", button_style="info")
        export_btn = WidgetFactory.create_button("Export CSV", button_style="warning")

        self._pivot_col_dd = WidgetFactory.create_dropdown(
            options=numeric_cols, description="Pivot column:", width="wide"
        )
        self._pivot_group_dd = WidgetFactory.create_dropdown(
            options=category_cols, description="Group by:", width="wide"
        )
        pivot_btn = WidgetFactory.create_button("Export Pivot Table", button_style="success")

        self._table_out = WidgetFactory.create_output(min_height="large")
        # Must be in the widget tree for the injected <script> to execute.
        self._download_area = widgets.Output()

        update_btn.on_click(self._update_table)
        export_btn.on_click(self._export_csv)
        pivot_btn.on_click(self._export_pivot)

        self._update_table(None)

        self._container = widgets.VBox(
            [
                widgets.HTML("<h4>Select columns to display:</h4>"),
                self._col_sel,
                widgets.HBox([update_btn, export_btn]),
                widgets.HTML("<h4>Export Pivot Table:</h4>"),
                widgets.HTML(
                    "<p>Creates a table where each column is a group value "
                    "and rows are the selected metric.</p>"
                ),
                self._pivot_col_dd,
                self._pivot_group_dd,
                pivot_btn,
                self._table_out,
                self._download_area,
            ]
        )

    def _update_table(self, b):
        with self._table_out:
            self._table_out.clear_output(wait=True)
            cols = (
                list(self._col_sel.value) if self._col_sel.value else self.dm.data.columns.tolist()
            )
            ipydisplay(self.dm.data[cols].head(20))
            if len(self.dm.data) > 20:
                logger.info("Showing first 20 of %d rows.", len(self.dm.data))

    def _trigger_download(self, csv_string: str, filename: str):
        """Inject a JS anchor-click to trigger a browser file download."""
        content_b64 = base64.b64encode(csv_string.encode()).decode()
        data_url = f"data:text/plain;charset=utf-8;base64,{content_b64}"
        js = f"""
            var a = document.createElement('a');
            a.setAttribute('download', '{filename}');
            a.setAttribute('href', '{data_url}');
            a.click();
        """
        with self._download_area:
            self._download_area.clear_output()
            ipydisplay(HTML(f"<script>{js}</script>"))

    def _export_csv(self, b):
        ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        filename = f"abspl_data_{ts}.csv"
        self._trigger_download(self.dm.to_csv_string(), filename)
        logger.info("Downloading %s ...", filename)
        self._update_table(None)

    def _export_pivot(self, b):
        value_col = self._pivot_col_dd.value
        group_col = self._pivot_group_dd.value
        if not value_col:
            logger.warning("No pivot column selected.")
            return
        try:
            pivot = self.dm.get_pivot_table(value_col, group_col)
            buf = io.StringIO()
            pivot.to_csv(buf)
            ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
            filename = f"abspl_pivot_{value_col}_by_{group_col}_{ts}.csv"
            self._trigger_download(buf.getvalue(), filename)
            logger.info("Downloading %s ...", filename)
            with self._table_out:
                self._table_out.clear_output(wait=True)
                ipydisplay(pivot.head(10))
        except Exception as e:
            with self._table_out:
                self._table_out.clear_output(wait=True)
            ErrorHandler.log_error("exporting pivot table", e, self._table_out)

    @property
    def widget(self):
        return self._container


# ---------------------------------------------------------------------------
# StatisticsPanel
# ---------------------------------------------------------------------------


class StatisticsPanel:
    """Statistical summary and grouped comparison plots."""

    def __init__(self, data_manager, plot_manager):
        self.dm = data_manager
        self.pm = plot_manager
        self._build()

    def _build(self):
        numeric_cols = self.dm.numeric_columns
        category_cols = self.dm.category_columns

        self._col_dd = WidgetFactory.create_dropdown(
            options=numeric_cols, description="Column:", width="wide"
        )
        self._groupby_dd = WidgetFactory.create_dropdown(
            options=["None"] + category_cols,
            description="Group by:",
            width="wide",
            value="variation",
        )

        stats_btn = WidgetFactory.create_button("Calculate Statistics", button_style="info")
        stats_btn.on_click(self._calculate)

        self._stats_out = WidgetFactory.create_output(min_height="large", border=False)

        self._container = widgets.VBox(
            [
                widgets.HBox([self._col_dd, self._groupby_dd]),
                stats_btn,
                self._stats_out,
            ]
        )

    def _calculate(self, b):
        col = self._col_dd.value
        groupby = self._groupby_dd.value

        with self._stats_out:
            self._stats_out.clear_output(wait=True)
            if not col:
                logger.warning("No column selected for statistics.")
                return

            ipydisplay(HTML(f"<h4>Overall statistics for {col}</h4>"))
            ipydisplay(self.dm.data[col].describe())

            if groupby != "None":
                ipydisplay(HTML(f"<h4>Statistics for {col} grouped by {groupby}</h4>"))
                ipydisplay(self.dm.data.groupby(groupby)[col].describe())
                try:
                    fig = self.pm.statistics_box(self.dm.data, col, groupby)
                    ipydisplay(fig)
                except Exception as e:
                    ErrorHandler.log_error("generating statistics plot", e)

    @property
    def widget(self):
        return self._container


# ---------------------------------------------------------------------------
# AdvancedPanel  (tab container with toggle)
# ---------------------------------------------------------------------------


class AdvancedPanel:
    """Tab container for DataTablePanel and StatisticsPanel, revealed on demand."""

    def __init__(self, data_manager, plot_manager):
        table_panel = DataTablePanel(data_manager)
        stats_panel = StatisticsPanel(data_manager, plot_manager)

        tabs = widgets.Tab()
        tabs.children = [table_panel.widget, stats_panel.widget]
        tabs.set_title(0, "Data Table")
        tabs.set_title(1, "Statistics")

        toggle_btn = WidgetFactory.create_button(
            "Show / Hide Advanced Features", button_style="primary"
        )
        self._content_out = widgets.Output()
        self._visible = False

        def _toggle(b):
            self._visible = not self._visible
            self._content_out.clear_output()
            if self._visible:
                with self._content_out:
                    ipydisplay(tabs)

        toggle_btn.on_click(_toggle)
        self._container = widgets.VBox([toggle_btn, self._content_out])

    @property
    def widget(self):
        return self._container
