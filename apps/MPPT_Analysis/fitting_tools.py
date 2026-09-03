import lmfit
import numpy as np
import pandas as pd
from scipy.integrate import quad
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
    guess = stretched_exponential_defaults(power, times)
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

    # calculate additional parameters, such as t80 and lifetime energy production
    time_extrapolate, pce_extrapolate = extrapolate(times, result)
    T80 = find_T80(time_extrapolate, pce_extrapolate)
    T80_capped = min(T80, times[-1])
    lifetime_energy = calculate_ley(stretched_exponential, result.best_values.values(), T80_capped)

    # put all relevant parameters into a list, if errors were calculated return parameters as uncertainties.ufloats, otherwise as normal floats
    if result.errorbars:
        result_values = [
            result.uvars["A"],
            result.uvars["tau"],
            result.uvars["beta"],
            result.rsquared,
            T80_capped,
            lifetime_energy,
        ]
    else:
        result_values = [
            result.best_values["A"],
            result.best_values["tau"],
            result.best_values["beta"],
            result.rsquared,
            T80_capped,
            lifetime_energy,
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

    t80 = intercept * 0.2 / -slope
    t80_capped = min(t80, times[-1])
    lifetime_energy = 0.5 * slope * t80_capped**2 + intercept * t80_capped

    if result.errorbars:
        result_values = [
            result.uvars["slope"],
            result.uvars["intercept"],
            result.rsquared,
            t80_capped,
            lifetime_energy,
        ]
    else:
        result_values = [
            result.best_values["slope"],
            result.best_values["intercept"],
            result.rsquared,
            t80_capped,
            lifetime_energy,
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

    t80 = -decay * np.log(0.8)
    t80_capped = min(t80, times[-1])
    lifetime_energy = (
        amplitude * decay * (1 - np.exp(-t80_capped / decay))
    )  # explicit solution to integral

    if result.errorbars:
        result_values = [
            result.uvars["amplitude"],
            result.uvars["decay"],
            result.rsquared,
            t80_capped,
            lifetime_energy,
        ]
    else:
        result_values = [
            result.best_values["amplitude"],
            result.uvars["decay"],
            result.rsquared,
            t80_capped,
            lifetime_energy,
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
    guess = biexponential_defaults(power, times)
    guess.update(initial_values or {})
    initial_params = biexp_model.make_params(
        **{_BIEXP_DISPLAY_TO_LMFIT[name]: value for name, value in guess.items()}
    )
    # both decays are denominators in exp(-t/tau) - see stretched_exponential_params.
    initial_params["exp1_decay"].set(min=1e-6)
    initial_params["exp2_decay"].set(min=1e-6)
    result = biexp_model.fit(power, initial_params, x=times)

    tau_min = min(
        result.best_values["exp1_decay"], result.best_values["exp2_decay"]
    )  # faster decay
    tau_max = max(
        result.best_values["exp1_decay"], result.best_values["exp2_decay"]
    )  # slower decay
    tS = -tau_min * np.log(0.01)  # Use the fast decay for tS / burn-in-time
    Ts80 = -tau_max * np.log(0.8)  # Use slow decay for Ts80
    tS_capped = min(tS, times[-1])
    Ts80_capped = min(Ts80, times[-1])
    lifetime_energy = result.best_values["exp1_amplitude"] * result.best_values["exp1_decay"] * (
        1 - np.exp(-Ts80_capped / result.best_values["exp1_decay"])
    ) + result.best_values["exp2_amplitude"] * result.best_values["exp2_decay"] * (
        1 - np.exp(-Ts80_capped / result.best_values["exp2_decay"])
    )  # explicit solution for integral

    if result.errorbars:
        result_values = [
            result.uvars["exp1_amplitude"],
            result.uvars["exp1_decay"],
            result.uvars["exp2_amplitude"],
            result.uvars["exp2_decay"],
            result.rsquared,
            tS_capped,
            Ts80_capped,
            lifetime_energy,
        ]
    else:
        result_values = [
            result.best_values["exp1_amplitude"],
            result.best_values["exp1_decay"],
            result.best_values["exp2_amplitude"],
            result.best_values["exp2_decay"],
            result.rsquared,
            tS_capped,
            Ts80_capped,
            lifetime_energy,
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
    guess = logistic_defaults(power, times)
    guess.update(initial_values or {})
    initial_params = log_exp_model.make_params(**guess)
    # tau: denominator in exp(-t/tau), see stretched_exponential_params. k: divides
    # both L and the T80/lifetime-energy formulas below, so it can't be zero either.
    initial_params["tau"].set(min=1e-6)
    initial_params["k"].set(min=1e-6)
    result = log_exp_model.fit(power, initial_params, t=times)

    tS, time_extrapolate, pce_extrapolate = find_tS(times, result)
    PCE_tS = pce_extrapolate[np.where(time_extrapolate == tS)[0][0]]
    Ts80, _ = find_Ts80(pce_extrapolate, time_extrapolate, tS, PCE_tS)
    tS_capped = min(tS, times[-1])
    Ts80_capped = min(Ts80, times[-1])

    A = result.best_values["A"]
    tau = result.best_values["tau"]
    L = result.best_values["L"]
    k = result.best_values["k"]
    x0 = result.best_values["x0"]

    lifetime_energy = (
        A * tau * (1 - np.exp(-Ts80_capped / tau))  # exponential part
        + L
        / k
        * (
            np.log(1 + np.exp(k * (Ts80_capped - x0))) - np.log(1 + np.exp(-k * x0))
        )  # logistic part
    )

    # for some reason does not calculate errors
    if result.errorbars:
        result_values = [
            result.uvars["A"],
            result.uvars["tau"],
            result.uvars["L"],
            result.uvars["k"],
            result.uvars["x0"],
            result.rsquared,
            tS_capped,
            Ts80_capped,
            lifetime_energy,
        ]
    else:
        result_values = [A, tau, L, k, x0, result.rsquared, tS_capped, Ts80_capped, lifetime_energy]
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
    guess = erfc_defaults(power, times)
    guess.update(initial_values or {})
    initial_params = erfc_model.make_params(**guess)
    # b is a denominator inside erfc((t-t0)/b) - the same div-by-zero/NaN
    # risk as tau elsewhere; the default guess already avoids 0 but the
    # optimizer is still free to wander back to it without this bound.
    initial_params["b"].set(min=1e-6)
    result = erfc_model.fit(power, initial_params, t=times)

    PCE0 = result.best_values["PCE0"]
    k = result.best_values["k"]
    index_t80 = np.nonzero(np.diff(np.sign(result.best_fit - 0.8 * PCE0)))[
        0
    ]  # find the first index where the power falls below 80% of initial value
    if index_t80.size > 0:
        T80_composite = times[index_t80[0]]
    else:
        T80_composite = times[-1]
    T80_composite_capped = min(T80_composite, times[-1])
    # Calculate T80* from the linear part (PCE0 - k*t = 0.8*PCE0)
    T80_linear = (0.2 * PCE0) / k if k != 0 else None
    lifetime_energy = calculate_ley(erfc_linear, result.best_values.values(), T80_composite_capped)

    if result.errorbars:
        result_values = [
            result.uvars["PCE0"],
            result.uvars["k"],
            result.uvars["t0"],
            result.uvars["b"],
            result.rsquared,
            T80_composite_capped,
            T80_linear,
            lifetime_energy,
        ]
    else:
        result_values = [
            result.best_values["PCE0"],
            result.best_values["k"],
            result.best_values["t0"],
            result.best_values["b"],
            result.rsquared,
            T80_composite_capped,
            T80_linear,
            lifetime_energy,
        ]
    return result_values, result.best_fit, result


# ------------------------
# Utility Functions
# ------------------------


# lifetime energy from fitted function, output is in kWh/m^2 when input function uses the default W/cm^2 over hours
def calculate_ley(fit_function, params, t_end, t_start=0):
    integral, _ = quad(fit_function, t_start, t_end, args=tuple(params))
    ley = integral * 10
    return ley


# extrapolates the fitted curve by default 10 times the measurement time
def extrapolate(times, fit_results, time_limit=None):
    if time_limit:
        time_extrapolate = np.linspace(times[0], time_limit, 1000)  #
    else:
        time_extrapolate = np.linspace(times[0], 10 * times[-1], 1000)
    pce_extrapolate = fit_results.eval(params=fit_results.params, t=time_extrapolate)
    return time_extrapolate, pce_extrapolate


# finds the first time where the power falls below the given fraction, by default the average of the 50 highest power values is taken as reference
def find_T80(times, power, reference_power=None, target_decay=0.8):
    if not reference_power:
        reference = np.mean(np.partition(power, -50)[-50:])
    else:
        reference = reference_power
    t80_index = np.argmax(
        power <= reference * target_decay
    )  # argmax returns the first value for which the expression is true
    return times[t80_index]


# finds the global minimum, then finds the global maximum after that, fitted function is extrapolated to 10 times the measurement time
# exact motivation unknown
def find_tS(times, fit_results):
    time_extrapolate = np.linspace(times[0], 10 * times[-1], 1000)
    pce_extrapolate = fit_results.eval(params=fit_results.params, t=time_extrapolate)

    min_idx = np.argmin(pce_extrapolate)
    tS_idx = min_idx + np.argmax(pce_extrapolate[min_idx:])
    tS = time_extrapolate[tS_idx]

    return tS, time_extrapolate, pce_extrapolate


def find_Ts80(pce_extrapolate, time_extrapolate, tS, PCE_tS):
    Ts80_value = 0.8 * PCE_tS
    tS_idx = np.where(time_extrapolate == tS)[0][0]
    Ts80_idx = np.where(pce_extrapolate[tS_idx:] <= Ts80_value)[0]

    if len(Ts80_idx) == 0:
        Ts80 = time_extrapolate[-1]
    else:
        Ts80_idx = tS_idx + Ts80_idx[0]
        Ts80 = time_extrapolate[Ts80_idx]

    return Ts80, time_extrapolate


available_fit_model_list = [
    fit_model(
        name="Stretched Exponential",
        parfunc=stretched_exponential_params,
        abbreviated_name="Stretched Exp",
        columns=["A", "tau", "beta", "R2", "T80", "LEY"],
        n_params=3,
        default_guess=stretched_exponential_defaults,
        description=r"PCE(t) = A \cdot e^{-(t/\tau)^\beta}",
    ),
    fit_model(
        name="Linear",
        parfunc=linear_params,
        abbreviated_name="Linear",
        columns=["slope", "intercept", "R2", "t80", "LEY"],
        n_params=2,
        default_guess=linear_defaults,
        description=r"PCE(t) = \text{slope} \cdot t + \text{intercept}",
    ),
    fit_model(
        name="Exponential",
        parfunc=exponential_params,
        abbreviated_name="Exponential",
        columns=["amplitude", "decay", "R2", "t80", "LEY"],
        n_params=2,
        default_guess=exponential_defaults,
        description=r"PCE(t) = A \cdot e^{-t/\tau}",
    ),
    fit_model(
        name="Biexponential",
        parfunc=biexponential_params,
        abbreviated_name="Biexponential",
        columns=["A1", "tau1", "A2", "tau2", "R2", "tS", "Ts80", "LEY"],
        n_params=4,
        default_guess=biexponential_defaults,
        description=r"PCE(t) = A_1 \cdot e^{-t/\tau_1} + A_2 \cdot e^{-t/\tau_2}",
    ),
    fit_model(
        name="Logistic + Exponential",
        parfunc=logistic_params,
        abbreviated_name="Logistic+Exp",
        columns=["A", "tau", "L", "k", "x0", "R2", "tS", "Ts80", "LEY"],
        n_params=5,
        default_guess=logistic_defaults,
        description=r"PCE(t) = A \cdot e^{-t/\tau} + \frac{L}{1 + e^{-k(t - x_0)}}",
    ),
    fit_model(
        name="ERFC + Linear",
        parfunc=erfc_params,
        abbreviated_name="ERFC+Linear",
        columns=["PCE0", "k", "t0", "b", "R2", "T80", "T80_linear", "LEY"],
        n_params=4,
        default_guess=erfc_defaults,
        description=r"PCE(t) = \frac{1}{2}\,\mathrm{erfc}\!\left(\frac{t-t_0}{b}\right)(PCE_0 - k \cdot t)",
    ),
]
