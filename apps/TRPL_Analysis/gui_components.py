"""
TRPL GUI Components
===================
All ipywidgets code lives here and only here.
data_manager, plot_manager are imported as plain local names.
"""

from __future__ import annotations

import logging

import ipywidgets as widgets
import numpy as np
import pandas as pd
import plot_manager as pm

# ---------------------------------------------------------------------------
# Helper: physics functions (extracted from the original notebook's flat code)
# These are pure Python / numpy and belong logically near data_manager, but
# they are called from the GUI after user input is collected.  They live in
# a small private module imported here.
# ---------------------------------------------------------------------------
# NOTE: rather than importing a private module that doesn't exist yet, we
# inline the physics helpers as module-level functions here.  They have zero
# widget dependencies so they satisfy the architecture rule.
import scipy.optimize
import scipy.signal
from data_manager import MEASUREMENT_TYPE, TRPLDataManager
from hysprint_utils.api_calls import get_all_batches_wth_data
from hysprint_utils.batch_selection import create_batch_selection
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import WidgetFactory
from IPython.display import display as ipydisplay
from scipy.interpolate import BSpline, generate_knots, make_splrep
from scipy.optimize import minimize

logger = logging.getLogger(__name__)
def _fit_convex_spline(x, y, spl0, n_grid=200, tol=0.0):
    """Refit BSpline coefficients with convexity constraint f'' >= tol."""
    x, y = np.asarray(x), np.asarray(y)
    t_s, k, c0 = spl0.t, spl0.k, spl0.c
    n = c0.size

    def design(x_eval, nu=0):
        A = np.empty((len(x_eval), n))
        for j in range(n):
            c = np.zeros(n)
            c[j] = 1.0
            A[:, j] = BSpline(t_s, c, k)(x_eval, nu=nu)
        return A

    A_data = design(x)
    x_grid = np.linspace(x.min(), x.max(), n_grid)
    A_d2 = design(x_grid, nu=2)

    def obj(c):
        r = A_data @ c - y
        return 0.5 * np.dot(r, r)

    def obj_jac(c):
        return A_data.T @ (A_data @ c - y)

    cons = {"type": "ineq", "fun": lambda c: A_d2 @ c - tol, "jac": lambda c: A_d2}

    res = minimize(obj, c0, jac=obj_jac, constraints=cons, method="SLSQP")
    if not res.success:
        raise RuntimeError("Convex spline fit failed: " + res.message)
    return BSpline(t_s, res.x, k)


def _fitfunc_2(x, *params):
    s = 0
    for p1, p2 in zip(params[0::2], params[1::2]):
        s += p1 * np.exp(-p2 * x)
    return s


def _calculate_N0s(hc, spot_area, lambda_laser, thickness, bd_ratio, data):
    photon_energy = hc / lambda_laser
    n0s, fluences = [], []
    for _, row in data.iterrows():
        power_per_pulse = row.laser_power / row.repetition_rate
        ppd = power_per_pulse / spot_area
        photons = ppd / photon_energy
        fluences.append(photons)
        n0s.append(1e-6 * (photons / thickness) * bd_ratio)
    return np.array(n0s), np.array(fluences)


def _calculate_noise(counts, denoise_value):
    if denoise_value < 0:
        return float(np.mean(np.trim_zeros(counts, trim="b")[denoise_value:]))
    if denoise_value > 0:
        return float(np.mean(counts[:denoise_value]))
    return 0.0


def _rate_calc(count, integration_time_s, binsize_s, reprate):
    return count / (binsize_s * integration_time_s * reprate)


# ---------------------------------------------------------------------------
# ParameterPanel
# ---------------------------------------------------------------------------
class ParameterPanel:
    """Global physical parameters + per-sample parameter table."""

    # Default values matching the original notebook
    _DEFAULTS = dict(
        bg=0.0,
        lambda_laser=705e-9,
        spot_diameter=2.72e-4,
        thickness=0.0,
        nc=2e18,
        nv=2e18,
        kt=27.7e-3,
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
            w = WidgetFactory.create_text_input(description=desc)
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
                fw("Bandgap [eV]:", d["bg"], "bg"),
                fw("λ laser [m]:", d["lambda_laser"], "lambda_laser"),
                fw("Spot Diameter [cm]:", d["spot_diameter"], "spot_diameter"),
                fw("Thickness [nm]:", d["thickness"], "thickness"),
                fw("Nc:", d["nc"], "nc"),
                fw("Nv:", d["nv"], "nv"),
                fw("kT [eV]:", d["kt"], "kt"),
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
        INT_DEFAULT, FIT_DEFAULT, NEXP_DEFAULT = 10.0, 100.0, 3

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
        g_fit = widgets.FloatText(
            value=FIT_DEFAULT,
            description="Set all Fit. Intervals:",
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
        g_fit.observe(lambda c: _set_all("fitting_interval", c))
        g_nexp.observe(lambda c: _set_all("num_exponentials", c))

        global_setter_box = widgets.VBox(
            [
                widgets.HTML("<h4>Set All Sample Values</h4>"),
                g_rep,
                g_pwr,
                g_nd,
                g_int,
                g_fit,
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
                widgets.HTML("<b>Fit Interval</b>", layout=widgets.Layout(width="110px")),
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
                fitting_interval=widgets.FloatText(
                    value=FIT_DEFAULT, layout=widgets.Layout(width="110px")
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
                        rw["fitting_interval"],
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
        self._output = WidgetFactory.create_output(min_height="large", scrollable=True)
        btn = WidgetFactory.create_button("Run Analysis", button_style="success")
        btn.on_click(self._run)
        self.widget = widgets.VBox([btn, self._output])

    def _run(self, _b) -> None:
        with self._output:
            self._output.clear_output()
            try:
                gp = self._pp.collect_global_params()
                row_params = self._pp.collect_row_params()

                data = self._dm.data.copy()
                for i, (rp, (_, row)) in enumerate(zip(row_params, data.iterrows())):
                    data.at[row.name, "repetition_rate"] = rp["rep_rate"]
                    data.at[row.name, "laser_power"] = rp["power"]
                    data.at[row.name, "nd"] = rp["nd"]
                    data.at[row.name, "integration_time"] = rp["integration_time"]

                denoise_val = int(gp["denoise"])
                data["noise"] = [
                    _calculate_noise(np.array(row["counts"]), denoise_val)
                    for _, row in data.iterrows()
                ]

                # Convert counts to rate, subtract noise
                hc = 1.98645e-25
                spot_area = np.pi * (gp["spot_diameter"] / 2) ** 2
                counts_list, cnn_list, cnn_norm_list, noise_list = [], [], [], []
                for _, row in data.iterrows():
                    raw = np.array(row["counts"])
                    ns_bin = row["ns_per_bin"]  # already in ns
                    rep = row["repetition_rate"]
                    int_t = row["integration_time"]
                    rate = _rate_calc(raw, int_t, ns_bin, rep)
                    noise_rate = _rate_calc(row["noise"], int_t, ns_bin, rep)
                    cnn = rate - noise_rate
                    peak = np.amax(cnn) if np.amax(cnn) > 0 else 1.0
                    counts_list.append(rate)
                    cnn_list.append(cnn)
                    cnn_norm_list.append(cnn / peak)
                    noise_list.append(noise_rate)

                data["counts"] = counts_list
                data["counts_no_noise"] = cnn_list
                data["counts_no_noise_normalized"] = cnn_norm_list
                data["noise"] = noise_list

                thickness = gp["thickness"]
                if thickness == 0:
                    raise ValueError(
                        "Thickness is 0 nm. Set a non-zero value in 'Thickness [nm]' before running analysis."
                    )
                n0s, fluences = _calculate_N0s(
                    hc,
                    spot_area,
                    gp["lambda_laser"],
                    thickness,
                    gp["bd_ratio"],
                    data,
                )
                data["n0s"] = n0s
                data["fluences"] = fluences

                # Raw trace plot
                fig_raw = pm.TRPLPlotManager.trpl_traces(data, y_col="counts")
                ipydisplay(fig_raw)

                # Differential lifetime analysis
                tau_diffs, densities, times = [], [], []
                for i, (_, row) in enumerate(data.iterrows()):
                    n_exp = int(row_params[i]["num_exponentials"])
                    t = np.array(row["time"])
                    pl = np.array(row["counts_no_noise"])
                    pl_argmax = int(np.argmax(pl))
                    t = t[pl_argmax:] / 1e12
                    pl = pl[pl_argmax:]
                    t_min = t[0]
                    t = t - t_min

                    fit_sav = scipy.signal.savgol_filter(pl, 51, 3)
                    s = 1e-5
                    knots = list(generate_knots(t, fit_sav, s=s, k=3, nest=30))
                    spr0 = make_splrep(t, fit_sav, k=3, s=s, t=knots[-1])
                    fit_knots_vals = make_splrep(t, fit_sav, k=3, s=s, t=knots[-1])(t)
                    mask = fit_knots_vals > 10 * row["noise"]
                    spl_convex_obj = _fit_convex_spline(
                        t[mask], fit_sav[mask], spr0, n_grid=300, tol=0.0
                    )
                    spl_convex = spl_convex_obj(t[mask])

                    p0 = [1, 1e4] * n_exp
                    lb = (1e-12,) * (2 * n_exp)
                    ub = (np.inf,) * (2 * n_exp)
                    p, _ = scipy.optimize.curve_fit(
                        lambda x, *params: _fitfunc_2(x, *params) + row["noise"],
                        1e3 * t[mask],
                        pl[mask],
                        maxfev=100000,
                        p0=p0,
                        bounds=(lb, ub),
                    )
                    fit = _fitfunc_2(t * 1e3, *p) + row["noise"]
                    t += t_min

                    tau_diff = -2 * (np.diff(t) / np.diff(np.log(fit)))
                    carrier_densities = np.sqrt(fit / np.max(fit)) * row["n0s"]
                    tau_diffs.append(tau_diff)
                    densities.append(carrier_densities)
                    times.append(t[: len(fit)])

                labels = [f"{r['sample_id']}" for _, r in data.iterrows()]

                fig_tau_t = pm.TRPLPlotManager.differential_lifetime_time(tau_diffs, times, labels)
                fig_tau_n = pm.TRPLPlotManager.differential_lifetime_density(
                    tau_diffs, densities, labels
                )
                ipydisplay(fig_tau_t)
                ipydisplay(fig_tau_n)

                ErrorHandler.log_success("Analysis completed.", self._output)

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
