# MPPT_Analysis fitting: how it works

Quick-reference for anyone who needs to know exactly what this app computes,
where, and why. Written after issue [#26](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues/26)
unified the figures of merit across every model — read this before changing
any fitting math.

## Where things live

| What | File | Symbol |
|---|---|---|
| The 6 fit models (equations, defaults, per-model math) | `fitting_tools.py` | `available_fit_model_list` (bottom of file) |
| Shared crossing-time policy (T80/T95/Ts80/Ts95) | `fitting_tools.py` | `crossing_time()` |
| PCE-after-1000h policy | `fitting_tools.py` | `pce_after_1000h()` |
| Reference ("100%") power for T80/T95 | `fitting_tools.py` | `initial_reference()` |
| Burn-in stabilization-time detection (Biexponential/Logistic+Exp only) | `fitting_tools.py` | `find_tS()` |
| Per-curve fit orchestration (slicing, NaN handling, calling a model) | `fitting_tools.py` | `fit_curve()` |
| Writing a fit's results back into NOMAD | `data_manager.py` | `DataManager.write_fit_results_to_nomad()` |
| Which fitting_tools.py column names map to which NOMAD schema fields | `data_manager.py` | `_ISOS_METRIC_ALIASES`, `_DEDICATED_FIELD_COLUMNS`, `_LEFTOVER_PARAM_UNITS` |
| Curve Fitting tab UI (model picker, Auto Fit / Fit With These Values, "Add fit results to NOMAD" button) | `gui_components.py` | `_create_write_to_nomad_section()` and surrounding fitting-tab code |
| NOMAD's own schema for the fields this app writes to | `nomad-baseclasses` (separate repo) | `src/baseclasses/solar_energy/mpp_tracking.py`, class `StabilityFiguresOfMerit` |

## The 6 models

Each is a `fit_model` instance in `fitting_tools.py`'s `available_fit_model_list`,
pairing an equation with a `parfunc` that fits it and computes every figure
of merit below.

| Model | Equation | `parfunc` |
|---|---|---|
| Stretched Exponential | `PCE(t) = A·e^(-(t/τ)^β)` | `stretched_exponential_params()` |
| Linear | `PCE(t) = slope·t + intercept` | `linear_params()` |
| Exponential | `PCE(t) = A·e^(-t/τ)` | `exponential_params()` |
| Biexponential | `PCE(t) = A₁·e^(-t/τ₁) + A₂·e^(-t/τ₂)` | `biexponential_params()` |
| Logistic + Exponential | `PCE(t) = A·e^(-t/τ) + L/(1+e^(-k(t-x₀)))` | `logistic_params()` |
| ERFC + Linear | `PCE(t) = ½·erfc((t-t₀)/b)·(PCE₀ - k·t)` | `erfc_params()` |

All 6 fit **power density** (mW/cm²) directly, not a separately-tracked "PCE
(%)" quantity. This app treats the two as numerically interchangeable, which
is only exactly true under standard 1-sun (100 mW/cm²) illumination — an
assumption baked into every figure of merit below, not just `PCE_after_1000_h`.

## The figures of merit (every model computes all of these)

Per direct product decision on issue #26: every model computes the *same*
full set, not a hand-picked subset. In fitting order, each `parfunc` returns:

- The model's own free parameters (e.g. `A`, `tau`, `beta`) — written to
  NOMAD's generic `fit_parameters` bag (see `_LEFTOVER_PARAM_UNITS` in
  `data_manager.py`).
- `R2` — goodness of fit (`result.rsquared` from lmfit).
- `T80` / `T95` — time to degrade to 80%/95% of the **initial** reference
  power (`initial_reference()` — mean of the 50 highest raw measured
  values).
- `Ts80` / `Ts95` — same concept, relative to a **stabilized** (post-burn-in)
  reference instead of the initial one. For a purely monotonic decay
  (Stretched Exponential, Linear, Exponential, ERFC+Linear) there is no
  burn-in dip to stabilize from, so these are defined to equal T80/T95. For
  Biexponential and Logistic+Exponential (which can have a genuine dip-then-
  recover shape), the stabilized reference comes from `find_tS()`'s real
  peak-after-dip detection.
- `tS` (`initial_stabilization_time` in NOMAD) — when the burn-in transient
  is considered over. `0.0` for the monotonic-decay models (see above);
  for Biexponential it's a closed-form constant from the faster of its two
  decay constants (`-tau_fast * ln(0.01)`); for Logistic+Exponential it's
  `find_tS()`'s real detected peak.
- `PCE_after_1000_h` — the PCE (%) at t=1000h, via `pce_after_1000h()`.
- `LEY` (`lifetime_energy_yield`) — time-integral of the fitted curve up to
  T80 (`calculate_ley()`), combining power output and durability into one
  number. Per the NOMAD schema's own definition, this always integrates up
  to **T80** (not Ts80), even for Biexponential/Logistic+Exponential.

### The real-else-extrapolated-else-NaN policy

Every T80/T95/Ts80/Ts95 value follows the same rule, implemented once in
`crossing_time()` (see its docstring, right above `find_tS()` in
`fitting_tools.py`) and reused by every model instead of being duplicated:

1. **If the real measured curve already reaches the threshold**, report
   that real, non-extrapolated time.
2. **Otherwise**, report the time at which the *fitted model* — evaluated
   beyond the real measurement — is predicted to reach it.
3. **...but only up to `EXTRAPOLATION_HORIZON_FACTOR` (= 10) times the
   measured duration.** Beyond that horizon, or for a model that is
   flat/improving and will never reach the threshold at all, the result is
   `NaN` — not an arbitrarily distant, scientifically unreliable time. This
   directly follows the ISOS consensus statement's own caution against
   extrapolating stability lifetimes far past the measured duration (see
   References below). `PCE_after_1000_h` follows the identical horizon rule
   in `pce_after_1000h()`: a real interpolated reading if the measurement
   covers 1000h, an extrapolated one if 1000h falls within the 10x horizon,
   `NaN` otherwise.

**How the crossing itself is found**, once extrapolation is needed, depends
on whether the model's equation is invertible:

- **Closed form** (exact algebra, `closed_form` argument to `crossing_time`):
  Stretched Exponential, Linear, Exponential. These solve directly for `t`.
- **Bounded numerical root-finding** (`scipy.optimize.brentq`, no `closed_form`
  argument): Biexponential, Logistic+Exponential, ERFC+Linear. No elementary
  closed form exists for a sum of two exponentials, an exponential-plus-
  logistic sum, or an erfc-enveloped linear term — each is solved exactly
  (to numerical tolerance) on its own equation instead of an approximation.
  Note: ERFC+Linear's curve is suppressed toward 0 by the `erfc` envelope
  itself as t→∞ regardless of the linear term's sign — it is *not*
  "dominated by the linear part at large t", a easy but wrong first guess.

A `NaN` from `crossing_time`/`pce_after_1000h` is never written to NOMAD as
a value — `data_manager._has_value()` treats `NaN` the same as "not
computed" and the write-back sends `{"action": "remove"}` for that field
instead, so a stale value from a previous fit (with a different model)
never lingers.

## Writing results back to NOMAD

`DataManager.write_fit_results_to_nomad()` POSTs one archive-edit request
per accepted curve fit, via `hysprint_utils.api_calls.edit_entry()`. Two
things worth knowing if you touch this:

- **Archive-edit paths use `/` as the separator** (e.g.
  `data/results/0/fit_method`), not `.` — confirmed by testing directly
  against a real NOMAD Oasis entry (see issue
  [#24](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues/24)/PR
  [#25](https://github.com/nomad-hzb/nomad-pv-analysis-apps/pull/25)). The
  whole `changes` list for one curve is sent in a single request; if *any*
  path in it is invalid, NOMAD rejects the entire request, not just that
  one field.
- On success, the outcome includes a `nomad_url` (`_entry_gui_url()`)
  linking directly to that entry's fitted results in the NOMAD GUI, built
  from `self.url` (already `URL_BASE + API_ENDPOINT`) plus the entry's
  `upload_id`/`entry_id` — rendered as a clickable link by
  `gui_components.py`.

## References

- Khenkin et al., "Consensus statement for stability assessment and
  reporting for perovskite photovoltaics based on ISOS procedures",
  *Nature Energy* 5, 35-49 (2020). DOI:
  [10.1038/s41560-019-0529-5](https://doi.org/10.1038/s41560-019-0529-5) —
  defines T80/T95/Ts80/Ts95 and the PCE-after-1000h alternative; also cited
  inline next to `_ISOS_METRIC_ALIASES` in `data_manager.py`.
- `nomad-baseclasses`' `StabilityFiguresOfMerit` class
  (`src/baseclasses/solar_energy/mpp_tracking.py`) is the authoritative
  schema for every field this app writes — check it directly if a field
  name/unit here ever looks stale relative to what's actually deployed.
