from typing import Any, cast

import lmfit
import numpy as np
import pandas as pd
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import erfc


# class to store information about a model and results obtained with it
class fit_model:
    def __init__(
        self, name, parfunc, abbreviated_name, columns, n_params, default_guess, description=""
    ):
        self.name = name
        self.parfunc = parfunc
        self.abbreviated_name = abbreviated_name
        self.columns = columns
        self.n_params = n_params  # free parameters actually fit (columns also has R2/T80/LEY etc.)
        # default_guess(power, times) -> {param_name: value} using this model's own
        # hardcoded starting-guess heuristics (e.g. A=power[0]), keyed by the same
        # display names as `columns`. Used both as parfunc's baseline before any
        # override, and by the GUI to pre-populate editable parameter fields before
        # a fit has run.
        self.default_guess = default_guess
        self.description = description
        self.do = True
        self.data = pd.DataFrame()


# ------------------------
# model functions, t is time, other arguments are parameters
# functions must be able to process numpy arrays functions from scipy and numpy generally wont cause issues
# ------------------------


def linear_decay(t, a, b):
    return a * t + b


def exponential_decay(t, a3, b3):
    return a3 * np.exp(-t / b3)


def biexponential_decay(t, a1, b1, a2, b2):
    return a1 * np.exp(-t / b1) + a2 * np.exp(-t / b2)


def logistic_plus_exp(t, A, tau, L, k, x0):
    return A * np.exp(-t / tau) + L / (1 + np.exp(-k * (t - x0)))


def stretched_exponential(t, A, tau, beta):
    return A * np.exp(-((t / tau) ** beta))


def erfc_linear(t, PCE0, k, t0, b):
    return (0.5 * erfc((t - t0) / b)) * (PCE0 - k * t)


# ----------------------
# parameter functions
# arguments: array of power values, array of time values
# returns: list of relevant parameters(e.g. t80), power values of the fitted function at the given time values
# ----------------------


def stretched_exponential_defaults(power, times):
    return {"A": float(power[0]), "tau": float(times[-1]), "beta": 1.0}


def stretched_exponential_params(power, times, initial_values=None):
    stretched_exponential_model = lmfit.Model(
        stretched_exponential
    )  # create Model object from the function
    guess: dict[str, Any] = stretched_exponential_defaults(power, times)
    guess.update(initial_values or {})
    initial_params = stretched_exponential_model.make_params(**guess)  # initial values for the fit
    # tau appears as (t/tau)**beta - an unbounded optimizer can wander tau
    # negative, making the base negative; raised to a non-integer beta that's
    # a NaN in numpy (and aborts the fit). Both must stay positive to keep
    # the model well-defined at every point the optimizer visits.
    initial_params["tau"].set(min=1e-6)
    initial_params["beta"].set(min=1e-6)

    result = stretched_exponential_model.fit(
        power, initial_params, t=times
    )  # perform fit, result is an instance of lmfit.ModelResult

    A = result.best_values["A"]
    tau = result.best_values["tau"]
    beta = result.best_values["beta"]

    def model_at(t):
        return stretched_exponential(t, A, tau, beta)

    def closed_form(threshold):
        # A*exp(-(t/tau)**beta) = threshold => t = tau*(-ln(threshold/A))**(1/beta)
        if threshold >= A:
            return 0.0  # already at/below threshold at t=0
        return tau * (-np.log(threshold / A)) ** (1 / beta)

    reference = initial_reference(power)
    T80 = crossing_time(times, power, reference, 0.8, model_at, closed_form)
    T95 = crossing_time(times, power, reference, 0.95, model_at, closed_form)
    # A monotonic decay from t=0 has no burn-in dip to stabilize from - the
    # "stabilized" reference is the same as the initial one.
    tS, Ts80, Ts95 = 0.0, T80, T95
    PCE_1000h = pce_after_1000h(times, power, model_at)
    ley_end = T80 if np.isfinite(T80) else times[-1]
    lifetime_energy = calculate_ley(stretched_exponential, [A, tau, beta], ley_end)

    # put all relevant parameters into a list, if errors were calculated return parameters as uncertainties.ufloats, otherwise as normal floats
    ley_1000h = ley_after_1000h(times, power, model_at)

    if result.errorbars:
        result_values = [
            result.uvars["A"],
            result.uvars["tau"],
            result.uvars["beta"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    else:
        result_values = [
            result.best_values["A"],
            result.best_values["tau"],
            result.best_values["beta"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    return result_values, result.best_fit, result


def linear_defaults(power, times):
    guessed = lmfit.models.LinearModel().guess(power, x=times)
    return {"slope": guessed["slope"].value, "intercept": guessed["intercept"].value}


def linear_params(power, times, initial_values=None):
    linear_model = lmfit.models.LinearModel()
    initial_params = linear_model.guess(power, x=times)
    for name, value in (initial_values or {}).items():
        if name in initial_params:
            initial_params[name].set(value=value)
    result = linear_model.fit(power, initial_params, x=times)

    slope = result.best_values["slope"]
    intercept = result.best_values["intercept"]

    def model_at(t):
        return linear_decay(t, slope, intercept)

    def closed_form(threshold):
        # slope*t + intercept = threshold => t = (threshold - intercept) / slope
        if intercept <= threshold:
            return 0.0
        if slope >= 0:
            return None  # flat or rising - never decays to the threshold
        return (threshold - intercept) / slope

    reference = initial_reference(power)
    T80 = crossing_time(times, power, reference, 0.8, model_at, closed_form)
    T95 = crossing_time(times, power, reference, 0.95, model_at, closed_form)
    tS, Ts80, Ts95 = 0.0, T80, T95
    PCE_1000h = pce_after_1000h(times, power, model_at)
    ley_end = T80 if np.isfinite(T80) else times[-1]
    lifetime_energy = (0.5 * slope * ley_end**2 + intercept * ley_end) * LEY_MWH_CM2_TO_KWH_M2

    ley_1000h = ley_after_1000h(times, power, model_at)

    if result.errorbars:
        result_values = [
            result.uvars["slope"],
            result.uvars["intercept"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    else:
        result_values = [
            result.best_values["slope"],
            result.best_values["intercept"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    return result_values, result.best_fit, result


def exponential_defaults(power, times):
    guessed = lmfit.models.ExponentialModel().guess(power, x=times)
    return {"amplitude": guessed["amplitude"].value, "decay": guessed["decay"].value}


def exponential_params(power, times, initial_values=None):
    exponential_model = lmfit.models.ExponentialModel()
    initial_params = exponential_model.guess(power, x=times)
    for name, value in (initial_values or {}).items():
        if name in initial_params:
            initial_params[name].set(value=value)
    # decay is a denominator in exp(-t/decay) - keep it positive so the
    # optimizer can't cross zero and produce a divide-by-zero/NaN.
    initial_params["decay"].set(min=1e-6)
    result = exponential_model.fit(power, initial_params, x=times)

    amplitude = result.best_values["amplitude"]
    decay = result.best_values["decay"]

    def model_at(t):
        return exponential_decay(t, amplitude, decay)

    def closed_form(threshold):
        # amplitude*exp(-t/decay) = threshold => t = decay*ln(amplitude/threshold)
        if threshold >= amplitude:
            return 0.0
        return decay * np.log(amplitude / threshold)

    reference = initial_reference(power)
    T80 = crossing_time(times, power, reference, 0.8, model_at, closed_form)
    T95 = crossing_time(times, power, reference, 0.95, model_at, closed_form)
    tS, Ts80, Ts95 = 0.0, T80, T95
    PCE_1000h = pce_after_1000h(times, power, model_at)
    ley_end = T80 if np.isfinite(T80) else times[-1]
    lifetime_energy = (
        amplitude * decay * (1 - np.exp(-ley_end / decay)) * LEY_MWH_CM2_TO_KWH_M2
    )  # explicit solution to integral

    ley_1000h = ley_after_1000h(times, power, model_at)

    if result.errorbars:
        result_values = [
            result.uvars["amplitude"],
            result.uvars["decay"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    else:
        result_values = [
            result.best_values["amplitude"],
            result.best_values["decay"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    return result_values, result.best_fit, result


# display names (A1/tau1/A2/tau2, matching fit_model.columns) -> the underlying
# lmfit composite model's own parameter names (exp1_amplitude/exp1_decay/...)
_BIEXP_DISPLAY_TO_LMFIT = {
    "A1": "exp1_amplitude",
    "tau1": "exp1_decay",
    "A2": "exp2_amplitude",
    "tau2": "exp2_decay",
}


def biexponential_defaults(power, times):
    # assume decay consists of a dominant slow decay and a weaker fast decay
    return {
        "A1": float(power[0]),
        "tau1": float(times[-1]),
        "A2": float(power[0]) / 10,
        "tau2": float(times[-1]) / 10,
    }


def biexponential_params(power, times, initial_values=None):
    biexp_model = lmfit.models.ExponentialModel(prefix="exp1_") + lmfit.models.ExponentialModel(
        prefix="exp2_"
    )
    guess: dict[str, Any] = biexponential_defaults(power, times)
    guess.update(initial_values or {})
    initial_params = biexp_model.make_params(
        **{_BIEXP_DISPLAY_TO_LMFIT[name]: value for name, value in guess.items()}
    )
    # both decays are denominators in exp(-t/tau) - see stretched_exponential_params.
    initial_params["exp1_decay"].set(min=1e-6)
    initial_params["exp2_decay"].set(min=1e-6)
    result = biexp_model.fit(power, initial_params, x=times)

    A1 = result.best_values["exp1_amplitude"]
    tau1 = result.best_values["exp1_decay"]
    A2 = result.best_values["exp2_amplitude"]
    tau2 = result.best_values["exp2_decay"]
    tau_fast = min(tau1, tau2)
    A_slow = (
        A1 if tau1 >= tau2 else A2
    )  # amplitude of the slower-decaying (dominant, long-term) term

    def model_at(t):
        return biexponential_decay(t, A1, tau1, A2, tau2)

    # T80/T95: relative to the initial reference, over the full two-term
    # curve - no elementary closed form exists for a sum of two exponentials,
    # so these are solved via bounded root-finding on the exact equation.
    reference = initial_reference(power)
    T80 = crossing_time(times, power, reference, 0.8, model_at)
    T95 = crossing_time(times, power, reference, 0.95, model_at)

    # tS/Ts80/Ts95: this model's existing (pre-#26) convention treats the
    # FASTER-decaying term as the burn-in transient and the SLOWER term as
    # the long-term degradation once burn-in is over - tS is when the fast
    # term has decayed to 1% of itself (a fixed closed-form constant, not a
    # measured/extrapolated crossing), and Ts80/Ts95 are the full curve's
    # crossings relative to the slow term's own amplitude (its value once
    # the fast term has vanished), found the same way as T80/T95 above.
    tS = -tau_fast * np.log(0.01)
    if tS > times[-1]:
        # beyond the measurement it is an extrapolation artefact (1350 h on 100 h of data)
        tS = Ts80 = Ts95 = float("nan")
    else:
        Ts80 = crossing_time(times, power, A_slow, 0.8, model_at, search_from=tS)
        Ts95 = crossing_time(times, power, A_slow, 0.95, model_at, search_from=tS)

    PCE_1000h = pce_after_1000h(times, power, model_at)
    # LEY integrates up to T80 (the initial-referenced threshold), matching
    # this field's schema definition - biexponential previously used Ts80
    # here only because T80 didn't exist yet for this model.
    ley_end = T80 if np.isfinite(T80) else times[-1]
    lifetime_energy = (
        A1 * tau1 * (1 - np.exp(-ley_end / tau1)) + A2 * tau2 * (1 - np.exp(-ley_end / tau2))
    ) * LEY_MWH_CM2_TO_KWH_M2  # explicit solution for integral

    ley_1000h = ley_after_1000h(times, power, model_at)

    if result.errorbars:
        result_values = [
            result.uvars["exp1_amplitude"],
            result.uvars["exp1_decay"],
            result.uvars["exp2_amplitude"],
            result.uvars["exp2_decay"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    else:
        result_values = [
            result.best_values["exp1_amplitude"],
            result.best_values["exp1_decay"],
            result.best_values["exp2_amplitude"],
            result.best_values["exp2_decay"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    return result_values, result.best_fit, result


def logistic_defaults(power, times):
    return {
        "A": float(power[0]) / 2,
        "tau": float(times[-1]),
        "L": float(power[0]) / 2,
        "k": float(times[-1]) / 5,
        "x0": float(times[-1]) / 2,
    }


def logistic_params(power, times, initial_values=None):
    log_exp_model = lmfit.Model(logistic_plus_exp)
    guess: dict[str, Any] = logistic_defaults(power, times)
    guess.update(initial_values or {})
    initial_params = log_exp_model.make_params(**guess)
    # tau: denominator in exp(-t/tau), see stretched_exponential_params. k: divides
    # both L and the T80/lifetime-energy formulas below, so it can't be zero either.
    initial_params["tau"].set(min=1e-6)
    initial_params["k"].set(min=1e-6)
    result = log_exp_model.fit(power, initial_params, t=times)

    A = result.best_values["A"]
    tau = result.best_values["tau"]
    L = result.best_values["L"]
    k = result.best_values["k"]
    x0 = result.best_values["x0"]

    def model_at(t):
        return logistic_plus_exp(t, A, tau, L, k, x0)

    tS, PCE_tS = find_tS(times, result)

    # T80/T95: relative to the initial reference. Ts80/Ts95: relative to the
    # post-burn-in stabilized value (PCE_tS, from find_tS above). Neither has
    # an elementary closed form (exponential + logistic terms together), so
    # both are solved via bounded root-finding on the exact equation.
    reference = initial_reference(power)
    T80 = crossing_time(times, power, reference, 0.8, model_at)
    T95 = crossing_time(times, power, reference, 0.95, model_at)
    Ts80 = crossing_time(times, power, PCE_tS, 0.8, model_at, search_from=tS)
    Ts95 = crossing_time(times, power, PCE_tS, 0.95, model_at, search_from=tS)

    PCE_1000h = pce_after_1000h(times, power, model_at)
    # LEY integrates up to T80 (the initial-referenced threshold), matching
    # this field's schema definition - previously used Ts80 here only
    # because T80 didn't exist yet for this model.
    ley_end = T80 if np.isfinite(T80) else times[-1]
    # log(1 + e^z) as logaddexp(0, z): the plain form overflows to inf for a large k (the
    # optimiser often lands on one), which made the whole NOMAD write-back fail.
    lifetime_energy = (
        A * tau * (1 - np.exp(-ley_end / tau))  # exponential part
        + L / k * (np.logaddexp(0, k * (ley_end - x0)) - np.logaddexp(0, -k * x0))  # logistic part
    ) * LEY_MWH_CM2_TO_KWH_M2

    # for some reason does not calculate errors
    ley_1000h = ley_after_1000h(times, power, model_at)

    if result.errorbars:
        result_values = [
            result.uvars["A"],
            result.uvars["tau"],
            result.uvars["L"],
            result.uvars["k"],
            result.uvars["x0"],
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    else:
        result_values = [
            A,
            tau,
            L,
            k,
            x0,
            result.rsquared,
            T80,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    return result_values, result.best_fit, result


def erfc_defaults(power, times):
    return {
        "PCE0": float(power[0]),
        "k": float(times[-1]) / 10,
        "t0": float(times[-1]) / 2,
        # b=0 (the original default) divides by zero in erfc_linear's own (t-t0)/b -
        # guaranteed to fail before any optimization even starts.
        "b": max(float(times[-1]) / 20, 1e-3),
    }


def erfc_params(power, times, initial_values=None):
    erfc_model = lmfit.Model(erfc_linear)
    guess: dict[str, Any] = erfc_defaults(power, times)
    guess.update(initial_values or {})
    initial_params = erfc_model.make_params(**guess)
    # b is a denominator inside erfc((t-t0)/b) - the same div-by-zero/NaN
    # risk as tau elsewhere; the default guess already avoids 0 but the
    # optimizer is still free to wander back to it without this bound.
    initial_params["b"].set(min=1e-6)
    result = erfc_model.fit(power, initial_params, t=times)

    PCE0 = result.best_values["PCE0"]
    k = result.best_values["k"]
    t0 = result.best_values["t0"]
    b = result.best_values["b"]

    def model_at(t):
        return erfc_linear(t, PCE0, k, t0, b)

    # erfc((t-t0)/b) itself always decays to 0 as t grows (for b>0), so the
    # whole curve is suppressed toward 0 regardless of the linear term's
    # sign - not "dominated by the linear part at large t" as one might
    # guess. The product of erfc and a linear term in the same variable has
    # no elementary closed-form inverse, so this is solved via bounded
    # root-finding, same as the other compound models.
    reference = initial_reference(power)
    T80 = crossing_time(times, power, reference, 0.8, model_at)
    T95 = crossing_time(times, power, reference, 0.95, model_at)
    tS, Ts80, Ts95 = 0.0, T80, T95

    # T80* from the linear part alone (PCE0 - k*t = 0.8*PCE0), ignoring the
    # erfc envelope - a distinct, pre-existing secondary figure of merit,
    # not this model's main T80.
    T80_linear = (0.2 * PCE0) / k if k != 0 else None

    PCE_1000h = pce_after_1000h(times, power, model_at)
    ley_end = T80 if np.isfinite(T80) else times[-1]
    lifetime_energy = calculate_ley(erfc_linear, [PCE0, k, t0, b], ley_end)

    ley_1000h = ley_after_1000h(times, power, model_at)

    if result.errorbars:
        result_values = [
            result.uvars["PCE0"],
            result.uvars["k"],
            result.uvars["t0"],
            result.uvars["b"],
            result.rsquared,
            T80,
            T80_linear,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    else:
        result_values = [
            result.best_values["PCE0"],
            result.best_values["k"],
            result.best_values["t0"],
            result.best_values["b"],
            result.rsquared,
            T80,
            T80_linear,
            T95,
            Ts80,
            Ts95,
            tS,
            PCE_1000h,
            lifetime_energy,
            ley_1000h,
        ]
    return result_values, result.best_fit, result


# ------------------------
# Utility Functions
# ------------------------


# Lifetime energy yield. The app works in mW/cm^2 and hours, so an integral of power density
# over time is in mWh/cm^2; NOMAD's `lifetime_energy_yield` is in kWh/m^2. One mWh/cm^2 is
# 1e-3 Wh / 1e-4 m^2 = 10 Wh/m^2 = 0.01 kWh/m^2, and every model converts with this single
# factor (previously two models multiplied by 10 and four not at all).
LEY_MWH_CM2_TO_KWH_M2 = 0.01


def calculate_ley(fit_function, params, t_end, t_start=0):
    """Integral of fit_function(t, *params) from t_start to t_end, in kWh/m^2."""
    integral, _ = quad(fit_function, t_start, t_end, args=tuple(params))
    return integral * LEY_MWH_CM2_TO_KWH_M2


# extrapolates the fitted curve by default 10 times the measurement time
def extrapolate(times, fit_results, time_limit=None):
    if time_limit:
        time_extrapolate = np.linspace(times[0], time_limit, 1000)  #
    else:
        time_extrapolate = np.linspace(times[0], 10 * times[-1], 1000)
    pce_extrapolate = fit_results.eval(params=fit_results.params, t=time_extrapolate)
    return time_extrapolate, pce_extrapolate


def find_tS(times, fit_results):
    """Stabilization time of a model with a burn-in dip: the time of the highest point after
    the fitted curve's minimum, searched ONLY inside the measured window. Returns
    (tS, PCE_tS). A curve with no dip (its minimum is the last point, e.g. a monotonic decay)
    has nothing to stabilize from, so tS is 0 and PCE_tS the starting value, like the other
    monotonic models. The old search ran over a 10x extrapolation, so a decaying fit always
    reported ten times the measurement length."""
    grid = np.linspace(times[0], times[-1], 1000)
    fitted = fit_results.eval(params=fit_results.params, t=grid)
    min_idx = int(np.argmin(fitted))
    if min_idx >= len(grid) - 1:
        return 0.0, float(fitted[0])
    tS_idx = min_idx + int(np.argmax(fitted[min_idx:]))
    return float(grid[tS_idx]), float(fitted[tS_idx])


# Every T80/T95/Ts80/Ts95-style figure of merit in this module follows the
# same policy (Khenkin et al., "Consensus statement for stability assessment
# and reporting for perovskite photovoltaics based on ISOS procedures",
# Nature Energy 2020, DOI: 10.1038/s41560-019-0529-5):
#   1. If the REAL measured curve already reaches the threshold, report that
#      real, non-extrapolated time.
#   2. Otherwise, report the time at which the FITTED model - extrapolated
#      beyond the measurement - is predicted to reach it.
#   3. ...but only up to EXTRAPOLATION_HORIZON_FACTOR times the measured
#      duration (matching extrapolate()'s own existing window). Beyond that,
#      or for a model that is flat/improving and will never reach the
#      threshold at all, report NaN rather than an arbitrarily distant,
#      scientifically unreliable time - the ISOS consensus statement itself
#      cautions against extrapolating stability lifetimes far past the
#      measured duration.
EXTRAPOLATION_HORIZON_FACTOR = 10


def initial_reference(power):
    """Reference ("100%") power for T80/T95: mean of the 50 highest raw
    measured values (or fewer, for a shorter curve) - robust to a single
    noisy first sample being used as the literal t=0 value."""
    n = min(50, len(power))
    return float(np.mean(np.partition(power, -n)[-n:]))


def _sustained_crossing_index(times, power, threshold, search_from=None):
    """Index of the first measured point from which the curve stays at or below `threshold`,
    or None if it never does.

    "Stays" is judged on a rolling-median smoothed copy, over a run of at least
    max(3, n/100) points (or to the end of the data). So a single dropout point, noise around
    the threshold, or a start that ramps up from low values is not a crossing: without this,
    one zero point gave T80 = 1.25 h for a curve whose real T80 was 71 h, and a ramp-up start
    gave T80 = 0. Without `search_from` only points after the curve's (smoothed) peak count;
    with it (Ts80/Ts95, relative to the post-burn-in time) only points from that time on."""
    n = len(power)
    valid = np.isfinite(power)
    if n == 0 or not valid.any():
        return None
    window = min(max(3, (n // 50) | 1), 21)
    smooth = pd.Series(power).rolling(window, center=True, min_periods=1).median().to_numpy()
    if search_from is not None:
        candidates = np.flatnonzero(times >= search_from)
        if len(candidates) == 0:
            return None
        start = int(candidates[0])
    else:
        start = int(np.nanargmax(smooth))
    below = np.where(np.isfinite(smooth), smooth <= threshold, False)
    # run[i]: how many consecutive points from i on are below the threshold
    run = np.zeros(n + 1, dtype=int)
    for i in range(n - 1, -1, -1):
        run[i] = run[i + 1] + 1 if below[i] else 0
    hold = max(3, n // 100)
    for i in range(start, n):
        if below[i] and run[i] >= min(hold, n - i) and (run[i] >= 2 or n - i == 1):
            return i
    return None


def crossing_time(
    times, power, reference, target_fraction, model_at, closed_form=None, search_from=None
):
    """Time at which a fit reaches `target_fraction * reference`, per the
    real-else-extrapolated-else-NaN policy documented above `find_tS`.

    model_at(t): evaluates the fitted model at any t (including beyond the
    real measurement) - used to test the extrapolation horizon and, when
    `closed_form` is not given, to numerically root-find the crossing itself.
    closed_form(threshold) -> t: optional analytic solution for models with
    one (Linear, Exponential, Stretched Exponential); omit it for models with
    no elementary closed form (Biexponential, Logistic+Exponential,
    ERFC+Linear), which are solved via bounded root-finding on `model_at`
    instead - exact to numerical tolerance, not an approximation.
    search_from: only consider real measured points at or after this time
    when checking whether the threshold was already reached - used for
    Ts80/Ts95, which are relative to the post-burn-in stabilization time, so
    a transient dip before stabilizing shouldn't count as "reached".
    """
    threshold = target_fraction * reference
    times = np.asarray(times, dtype=float)
    power = np.asarray(power, dtype=float)
    start_time = search_from
    reached_idx = _sustained_crossing_index(times, power, threshold, start_time)
    if reached_idx is not None:
        return float(times[reached_idx])

    t_last = times[-1]
    horizon = EXTRAPOLATION_HORIZON_FACTOR * t_last
    if model_at(horizon) > threshold:
        return float("nan")  # flat/improving trend, or too slow to matter within the horizon

    if closed_form is not None:
        t = closed_form(threshold)
        if t is None or not np.isfinite(t):
            return float("nan")
        return float(min(t, horizon))

    f_last = model_at(t_last) - threshold
    if f_last <= 0:
        return float(t_last)  # fit already at/below threshold right at the measurement's edge
    return float(cast(float, brentq(lambda t: model_at(t) - threshold, t_last, horizon)))


def pce_after_1000h(times, power, model_at):
    """PCE (%) at t=1000h, per the same real-else-extrapolated-else-NaN
    policy. This app fits power density directly as a stand-in for PCE (%) -
    the two are numerically identical under standard 1-sun/100 mW/cm^2
    illumination, the same assumption already implicit in every other figure
    of merit this module computes (T80/T95/... are likewise computed
    directly on power density, never converted).
    """
    if times[-1] >= 1000:
        return float(np.interp(1000.0, times, power))
    if EXTRAPOLATION_HORIZON_FACTOR * times[-1] < 1000:
        return float("nan")
    return float(model_at(1000.0))


def ley_after_1000h(times, power, model_at):
    """Lifetime energy yield (kWh/m^2) accumulated over the first 1000 h, with the same
    real-else-extrapolated-else-NaN policy as pce_after_1000h: integrate the measured curve
    when it reaches 1000 h, else integrate the fitted model if 1000 h lies within the
    extrapolation horizon, else NaN."""
    times = np.asarray(times, dtype=float)
    power = np.asarray(power, dtype=float)
    if times[-1] >= 1000:
        valid = np.isfinite(times) & np.isfinite(power)
        grid = np.concatenate([times[valid & (times < 1000)], [1000.0]])
        values = np.interp(grid, times[valid], power[valid])
        integrate = getattr(np, "trapezoid", None) or np.trapz
        return float(integrate(values, grid)) * LEY_MWH_CM2_TO_KWH_M2
    if EXTRAPOLATION_HORIZON_FACTOR * times[-1] < 1000:
        return float("nan")
    # a model that decays below zero (Linear) cannot give back negative energy
    integral, _ = quad(lambda t: max(float(model_at(t)), 0.0), float(times[0]), 1000.0, limit=200)
    return float(integral) * LEY_MWH_CM2_TO_KWH_M2


available_fit_model_list = [
    fit_model(
        name="Stretched Exponential",
        parfunc=stretched_exponential_params,
        abbreviated_name="Stretched Exp",
        columns=[
            "A",
            "tau",
            "beta",
            "R2",
            "T80",
            "T95",
            "Ts80",
            "Ts95",
            "tS",
            "PCE_after_1000_h",
            "LEY",
            "LEY_1000h",
        ],
        n_params=3,
        default_guess=stretched_exponential_defaults,
        description=r"PCE(t) = A \cdot e^{-(t/\tau)^\beta}",
    ),
    fit_model(
        name="Linear",
        parfunc=linear_params,
        abbreviated_name="Linear",
        columns=[
            "slope",
            "intercept",
            "R2",
            "T80",
            "T95",
            "Ts80",
            "Ts95",
            "tS",
            "PCE_after_1000_h",
            "LEY",
            "LEY_1000h",
        ],
        n_params=2,
        default_guess=linear_defaults,
        description=r"PCE(t) = \text{slope} \cdot t + \text{intercept}",
    ),
    fit_model(
        name="Exponential",
        parfunc=exponential_params,
        abbreviated_name="Exponential",
        columns=[
            "amplitude",
            "decay",
            "R2",
            "T80",
            "T95",
            "Ts80",
            "Ts95",
            "tS",
            "PCE_after_1000_h",
            "LEY",
            "LEY_1000h",
        ],
        n_params=2,
        default_guess=exponential_defaults,
        description=r"PCE(t) = A \cdot e^{-t/\tau}",
    ),
    fit_model(
        name="Biexponential",
        parfunc=biexponential_params,
        abbreviated_name="Biexponential",
        columns=[
            "A1",
            "tau1",
            "A2",
            "tau2",
            "R2",
            "T80",
            "T95",
            "Ts80",
            "Ts95",
            "tS",
            "PCE_after_1000_h",
            "LEY",
            "LEY_1000h",
        ],
        n_params=4,
        default_guess=biexponential_defaults,
        description=r"PCE(t) = A_1 \cdot e^{-t/\tau_1} + A_2 \cdot e^{-t/\tau_2}",
    ),
    fit_model(
        name="Logistic + Exponential",
        parfunc=logistic_params,
        abbreviated_name="Logistic+Exp",
        columns=[
            "A",
            "tau",
            "L",
            "k",
            "x0",
            "R2",
            "T80",
            "T95",
            "Ts80",
            "Ts95",
            "tS",
            "PCE_after_1000_h",
            "LEY",
            "LEY_1000h",
        ],
        n_params=5,
        default_guess=logistic_defaults,
        description=r"PCE(t) = A \cdot e^{-t/\tau} + \frac{L}{1 + e^{-k(t - x_0)}}",
    ),
    fit_model(
        name="ERFC + Linear",
        parfunc=erfc_params,
        abbreviated_name="ERFC+Linear",
        columns=[
            "PCE0",
            "k",
            "t0",
            "b",
            "R2",
            "T80",
            "T80_linear",
            "T95",
            "Ts80",
            "Ts95",
            "tS",
            "PCE_after_1000_h",
            "LEY",
            "LEY_1000h",
        ],
        n_params=4,
        default_guess=erfc_defaults,
        description=r"PCE(t) = \frac{1}{2}\,\mathrm{erfc}\!\left(\frac{t-t_0}{b}\right)(PCE_0 - k \cdot t)",
    ),
]
