"""
TRPL GUI Components
===================
All ipywidgets code lives here and only here.
data_manager, plot_manager are imported as plain local names.
"""

from __future__ import annotations

import logging

import ipywidgets as widgets
import pandas as pd
import plot_manager as pm
import plotly.graph_objects as go
from data_manager import (
    MEASUREMENT_TYPE,
    AnalysisInputError,
    TRPLDataManager,
    analyse_traces,
)
from IPython.display import HTML, Javascript
from IPython.display import display as ipydisplay

from hysprint_utils.api_calls import get_all_batches_wth_data
from hysprint_utils.batch_selection import create_batch_selection
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import WidgetFactory

logger = logging.getLogger(__name__)

PLOT_HEIGHT_PX = 520


def _responsive(fig: go.Figure) -> widgets.Widget:
    """A figure that fills the width of its container and has a real height.

    A plain go.Figure shown with display() inside an Output rendered tiny under Voila: nothing
    gave it a width or a height. Same approach as JV-Analysis: a FigureWidget (rendered through
    the widget comm, not a mimetype renderer), no explicit size on the figure itself, and a
    sized wrapper box whose inner Plotly div is forced to 100% by PLOT_CSS."""
    fig.update_layout(autosize=True, width=None, height=None)
    widget = go.FigureWidget(fig)
    widget._config = {"responsive": True, "displaylogo": False}
    box = widgets.Box([widget], layout=widgets.Layout(width="100%", height=f"{PLOT_HEIGHT_PX}px"))
    box.add_class("trpl-plot")
    return box


PLOT_CSS = "<style>.trpl-plot > div { width: 100% !important; height: 100% !important; }</style>"


# ---------------------------------------------------------------------------
# ParameterPanel
# ---------------------------------------------------------------------------
class ParameterPanel:
    """Global physical parameters + per-sample parameter table."""

    # Only inputs the analysis actually uses. Bandgap, Nc, Nv, kT and a per-sample "Fit
    # Interval" used to be collected here and read nowhere, so tuning them changed nothing.
    _DEFAULTS = dict(
        lambda_laser=705e-9,
        spot_diameter=2.72e-4,
        thickness=0.0,
        bd_ratio=0.21,
        denoise=0,
    )

    def __init__(self, data: pd.DataFrame) -> None:
        self._data = data
        self._row_widgets: list[dict] = []
        self.widget = self._build()

    # -- public helpers -------------------------------------------------------
    def collect_row_params(self) -> list[dict]:
        return [{k: w.value for k, w in rw.items()} for rw in self._row_widgets]

    def collect_global_params(self) -> dict:
        return {k: w.value for k, w in self._global_widgets.items()}

    # -- build ----------------------------------------------------------------
    def _build(self) -> widgets.VBox:
        d = self._DEFAULTS
        gw = {}  # global widget registry

        def fw(desc, val, key):
            w = widgets.FloatText(value=val, description=desc, style={"description_width": "140px"})
            gw[key] = w
            return w

        def iw(desc, val, key):
            w = widgets.IntText(value=val, description=desc, style={"description_width": "140px"})
            gw[key] = w
            return w

        float_box = widgets.VBox(
            [
                widgets.HTML("<h4>Physical Parameters</h4>"),
                fw("λ laser [m]:", d["lambda_laser"], "lambda_laser"),
                fw("Spot Diameter [cm]:", d["spot_diameter"], "spot_diameter"),
                fw("Thickness [nm]:", d["thickness"], "thickness"),
                fw("BD ratio:", d["bd_ratio"], "bd_ratio"),
            ]
        )
        bool_box = widgets.VBox(
            [
                widgets.HTML("<h4>Processing</h4>"),
                iw("Denoise:", d["denoise"], "denoise"),
            ]
        )
        self._global_widgets = gw

        param_row = widgets.HBox([float_box, bool_box])

        # --- per-sample table ---
        REP_DEFAULT, PWR_DEFAULT = 10000.0, 0.4
        INT_DEFAULT, NEXP_DEFAULT = 10.0, 3

        # global setters
        g_rep = widgets.FloatText(
            value=REP_DEFAULT,
            description="Set all Rep. Rates [Hz]:",
            style={"description_width": "160px"},
        )
        g_pwr = widgets.FloatText(
            value=PWR_DEFAULT,
            description="Set all Powers [µW]:",
            style={"description_width": "160px"},
        )
        g_nd = widgets.FloatText(description="Set all ND:", style={"description_width": "160px"})
        g_int = widgets.FloatText(
            value=INT_DEFAULT,
            description="Set all Int. Times [s]:",
            style={"description_width": "160px"},
        )
        g_nexp = widgets.IntText(
            value=NEXP_DEFAULT,
            description="Set all Num. Exp.:",
            style={"description_width": "160px"},
        )

        def _set_all(field, change):
            if change["type"] == "change" and change["name"] == "value":
                for rw in self._row_widgets:
                    rw[field].value = change["new"]

        g_rep.observe(lambda c: _set_all("rep_rate", c))
        g_pwr.observe(lambda c: _set_all("power", c))
        g_nd.observe(lambda c: _set_all("nd", c))
        g_int.observe(lambda c: _set_all("integration_time", c))
        g_nexp.observe(lambda c: _set_all("num_exponentials", c))

        global_setter_box = widgets.VBox(
            [
                widgets.HTML("<h4>Set All Sample Values</h4>"),
                g_rep,
                g_pwr,
                g_nd,
                g_int,
                g_nexp,
            ]
        )

        header = widgets.HBox(
            [
                widgets.HTML("<b>Sample ID</b>", layout=widgets.Layout(width="200px")),
                widgets.HTML("<b>Data File</b>", layout=widgets.Layout(width="280px")),
                widgets.HTML("<b>Rep. Rate [Hz]</b>", layout=widgets.Layout(width="130px")),
                widgets.HTML("<b>Power [µW]</b>", layout=widgets.Layout(width="120px")),
                widgets.HTML("<b>ND</b>", layout=widgets.Layout(width="100px")),
                widgets.HTML("<b>Int. Time [s]</b>", layout=widgets.Layout(width="120px")),
                widgets.HTML("<b>Num. Exp.</b>", layout=widgets.Layout(width="100px")),
            ]
        )

        table_rows = [header]
        for _, row in self._data.iterrows():
            rw = dict(
                rep_rate=widgets.FloatText(value=REP_DEFAULT, layout=widgets.Layout(width="130px")),
                power=widgets.FloatText(value=PWR_DEFAULT, layout=widgets.Layout(width="120px")),
                nd=widgets.FloatText(layout=widgets.Layout(width="100px")),
                integration_time=widgets.FloatText(
                    value=INT_DEFAULT, layout=widgets.Layout(width="120px")
                ),
                num_exponentials=widgets.IntText(
                    value=NEXP_DEFAULT, layout=widgets.Layout(width="100px")
                ),
            )
            self._row_widgets.append(rw)
            table_rows.append(
                widgets.HBox(
                    [
                        widgets.HTML(
                            str(row.get("sample_id", "")), layout=widgets.Layout(width="200px")
                        ),
                        widgets.HTML(
                            str(row.get("data_file", "")), layout=widgets.Layout(width="280px")
                        ),
                        rw["rep_rate"],
                        rw["power"],
                        rw["nd"],
                        rw["integration_time"],
                        rw["num_exponentials"],
                    ]
                )
            )

        return widgets.VBox(
            [
                param_row,
                global_setter_box,
                widgets.VBox(table_rows),
            ]
        )


# ---------------------------------------------------------------------------
# AnalysisPanel
# ---------------------------------------------------------------------------
class AnalysisPanel:
    """Run button + output area for TRPL processing and plotting."""

    def __init__(self, data_manager: TRPLDataManager, param_panel: ParameterPanel) -> None:
        self._dm = data_manager
        self._pp = param_panel
        self._plots: list = []  # plot boxes of the last run, closed when the next run starts
        # Full width and no fixed height: a scrollable Output has a fixed pixel size, which
        # boxed every plot into a few hundred pixels.
        self._output = WidgetFactory.create_output(min_height="large")
        self._output.layout.width = "100%"
        self._output.layout.height = "auto"
        self._output.layout.overflow = "visible"
        btn = WidgetFactory.create_button("Run Analysis", button_style="success")
        btn.on_click(self._run)
        self.widget = widgets.VBox([btn, self._output], layout=widgets.Layout(width="100%"))

    def _keep(self, widget):
        self._plots.append(widget)
        return widget

    def _run(self, _b) -> None:
        # clear_output only hides widgets: close the plots of the previous run
        for old in self._plots:
            for child in old.children:
                child.close()
            old.close()
        self._plots = []
        with self._output:
            self._output.clear_output()
            try:
                frame, results = analyse_traces(
                    self._dm.data,
                    self._pp.collect_global_params(),
                    self._pp.collect_row_params(),
                )
                # Raw trace plot, in counts per second
                ipydisplay(HTML(PLOT_CSS))
                fig_raw = pm.TRPLPlotManager.trpl_traces(
                    frame, y_col="counts", y_title="PL rate [counts/s]"
                )
                ipydisplay(self._keep(_responsive(fig_raw)))

                done = [r for r in results if not r.error]
                for failed in (r for r in results if r.error):
                    ErrorHandler.log_error(
                        f"Differential lifetime failed for {failed.label}",
                        ValueError(failed.error),
                        output_widget=self._output,
                    )
                if done:
                    tau_diffs = [r.tau_diff_s for r in done]
                    labels = [r.sample_id for r in done]
                    ipydisplay(
                        self._keep(
                            _responsive(
                                pm.TRPLPlotManager.differential_lifetime_time(
                                    tau_diffs, [r.time_s for r in done], labels
                                )
                            )
                        )
                    )
                    ipydisplay(
                        self._keep(
                            _responsive(
                                pm.TRPLPlotManager.differential_lifetime_density(
                                    tau_diffs, [r.density_cm3 for r in done], labels
                                )
                            )
                        )
                    )
                    ErrorHandler.log_success(
                        f"Analysis completed for {len(done)} of {len(results)} trace(s).",
                        self._output,
                    )
                else:
                    ErrorHandler.log_error("No trace could be analysed.", None, self._output)

                # Plotly lays a responsive figure out at its 700 px default until the window
                # fires a resize; trigger one once the plots are in the page.
                ipydisplay(
                    Javascript(
                        "setTimeout(function(){window.dispatchEvent(new Event('resize'));}, 400);"
                    )
                )

            except AnalysisInputError as exc:
                print(f"⚠️ {exc}")
            except Exception as exc:
                ErrorHandler.log_error(
                    "Analysis failed", exc, output_widget=self._output, show_traceback=True
                )


# ---------------------------------------------------------------------------
# BatchFilterPanel
# ---------------------------------------------------------------------------
class BatchFilterPanel:
    """Wraps create_batch_selection with an optional TRPL-filter button."""

    def __init__(self, url: str, token: str, on_load) -> None:
        self._url = url
        self._token = token
        self._on_load = on_load

        self._status_out = widgets.Output()
        self._filter_btn = WidgetFactory.create_button(
            "Show TRPL batches",
            button_style="info",
        )
        self._filter_btn.on_click(self._do_filter)

        self._batch_widget = create_batch_selection(url, token, on_load)
        self._batch_selector = self._find_selector()

        total = len(self._batch_selector.options) if self._batch_selector else "?"
        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    f"<p>Select from all {total} available batches, "
                    f"or filter to those with TRPL data:</p>"
                ),
                self._filter_btn,
                self._status_out,
                self._batch_widget,
            ]
        )

    def _find_selector(self):
        for child in self._batch_widget.children:
            if isinstance(child, widgets.SelectMultiple):
                return child
        return None

    def _do_filter(self, _b):
        self._filter_btn.disabled = True
        self._filter_btn.description = "Filtering..."
        logger.info("Querying NOMAD for batches with TRPL data...")
        with self._status_out:
            self._status_out.clear_output(wait=True)
            valid = get_all_batches_wth_data(self._url, self._token, MEASUREMENT_TYPE)
            if self._batch_selector:
                self._batch_selector.options = valid
            self._status_out.clear_output(wait=True)
        logger.info("Found %d batches with TRPL data.", len(valid))
        self._filter_btn.description = "Done – %d batches found" % len(valid)


# ---------------------------------------------------------------------------
# DataUI  (assembled by app.py after load)
# ---------------------------------------------------------------------------
class DataUI:
    """Full post-load UI: parameter panel + analysis panel."""

    def __init__(self, data_manager: TRPLDataManager) -> None:
        self._param_panel = ParameterPanel(data_manager.data)
        self._analysis_panel = AnalysisPanel(data_manager, self._param_panel)
        self.widget = widgets.VBox(
            [
                self._param_panel.widget,
                self._analysis_panel.widget,
            ]
        )
