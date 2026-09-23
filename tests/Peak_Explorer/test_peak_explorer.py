"""Tests for Peak_Explorer: fitting, derived values, units, loading, export, GUI handlers.

All data is synthetic, generated from lmfit's own line shapes, so every expected value is
known exactly.
"""

import json
import re
import warnings
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from lmfit.lineshapes import gaussian, lorentzian, skewed_gaussian, skewed_voigt, voigt

# Not imported from conftest: with several apps' tests in one run, "from conftest import"
# resolves to whichever app's conftest was loaded last (see CLAUDE.md, Known gaps).
APP_DIR = Path(__file__).parent.parent.parent / "apps" / "Peak_Explorer"


def BUG(reason):  # noqa: N802
    """A confirmed bug, reported but not fixed yet. strict: the test fails once it is fixed,
    so the marker cannot outlive the bug."""
    return pytest.mark.xfail(strict=True, reason=f"Bug: {reason}")


# =============================================================================
# Helpers
# =============================================================================


PEAK_TYPES = ["Gaussian", "Lorentzian", "Voigt", "Skewed Gaussian", "Skewed Voigt"]

_SHAPES = {
    "Gaussian": lambda x, v: gaussian(x, v["amplitude"], v["center"], v["sigma"]),
    "Lorentzian": lambda x, v: lorentzian(x, v["amplitude"], v["center"], v["sigma"]),
    "Voigt": lambda x, v: voigt(x, v["amplitude"], v["center"], v["sigma"], v["gamma"]),
    "Skewed Gaussian": lambda x, v: skewed_gaussian(
        x, v["amplitude"], v["center"], v["sigma"], v["gamma"]
    ),
    "Skewed Voigt": lambda x, v: skewed_voigt(
        x, v["amplitude"], v["center"], v["sigma"], v["gamma"], v["skew"]
    ),
}


def _curve_max(peak_type, values):
    """Maximum of a peak with these parameter values, on a very fine grid: an
    independent check of the height, not using the app's own height functions."""
    width = values["sigma"] + abs(values.get("gamma", 0.0))
    x = np.linspace(values["center"] - 30 * width, values["center"] + 30 * width, 600_001)
    return float(_SHAPES[peak_type](x, values).max())


def _fit_params(peaks, background="None", center_bound=50):
    return {
        "background_model": background,
        "poly_degree": 2,
        "center_bound": center_bound,
        "peak_models": peaks,
    }


def _batch(fe, x, data, peaks, sequential=True, background="None", center_bound=50):
    engine = fe.FittingEngine()
    engine.create_fit_parameters(peaks, background_model=background, center_bound=center_bound)
    results = engine.fit_all_spectra(
        x, data, np.arange(len(data), dtype=float), use_smart_init=sequential
    )
    return engine, results


def _write_h5(path, cfg, n_t=20, n_w=30, trailing_nan_time=False):
    """Synthetic H5 with every dataset any mode reads. Raw data is (time, wavelength);
    binned data is stored (wavelength, time), as the loader transposes it."""
    rng = np.random.default_rng(0)
    t = np.arange(n_t, dtype=float)
    if trailing_nan_time:
        t[-1] = np.nan
    wl = np.linspace(400, 800, n_w)
    q = np.linspace(0.5, 2.5, n_w)
    raw = 1.0 + rng.random((n_t, n_w))
    trans = np.full((n_t, n_w), 0.8)
    trans[n_t // 2 :] *= 0.5
    paths = cfg.H5_PATHS
    extent = np.array([0.0, n_t - 1.0, 400.0, 800.0])
    content = {
        "pl_raw": {"timestamps": t, "data": raw, "wavelengths": wl},
        "transmission_raw": {"timestamps": t, "data": trans, "wavelengths": wl},
        "pl_binned": {"extent": extent, "data": raw.T},
        "transmission_binned": {"extent": extent, "data": trans.T},
        "giwaxs": {"timestamps": t, "data": raw, "wavelengths": q[None, :]},
        "giwaxs_diamond": {"timestamps": t, "data": raw, "wavelengths": q[None, :]},
    }
    with h5py.File(path, "w") as f:
        for mode, datasets in content.items():
            for key, values in datasets.items():
                if paths[mode][key] not in f:  # several modes share datasets
                    f[paths[mode][key]] = values
        f[paths["giwaxs"]["timestamps"]].attrs["units"] = "min"
    return t, wl


# =============================================================================
# Fitting
# =============================================================================


@pytest.mark.parametrize(
    "peak_type, shape, truth, start",
    [
        (
            "Gaussian",
            lambda x: gaussian(x, 1000, 603, 11),
            {"center": 603, "sigma": 11},
            {"sigma": 8},
        ),
        (
            "Lorentzian",
            lambda x: lorentzian(x, 1000, 603, 11),
            {"center": 603, "sigma": 11},
            {"sigma": 8},
        ),
        (
            "Voigt",
            lambda x: voigt(x, 1000, 603, 5, 15),
            {"center": 603, "sigma": 5, "gamma": 15},
            {"sigma": 8, "gamma": 0.0},
        ),
        (
            "Skewed Gaussian",
            lambda x: skewed_gaussian(x, 1000, 603, 11, 3),
            {"center": 603, "sigma": 11, "gamma": 3},
            {"sigma": 8, "gamma": 0.0},
        ),
        (
            "Skewed Voigt",
            lambda x: skewed_voigt(x, 1000, 603, 5, 10, 2),
            {"center": 603, "sigma": 5, "gamma": 10, "skew": 2},
            {"sigma": 8, "gamma": 0.0},
        ),
    ],
)
def test_each_peak_type_recovers_its_parameters(fe, x_nm, peak_type, shape, truth, start):
    peak = {"type": peak_type, "center": 600, "height": 30, **start}
    result = fe.FittingModels().fit_spectrum(x_nm, shape(x_nm), _fit_params([peak]))
    for name, expected in truth.items():
        assert result.params[f"p0_{name}"].value == pytest.approx(expected, rel=1e-3, abs=1e-3)


def test_voigt_gamma_is_fitted_not_frozen_at_its_start_value(fe, x_nm):
    """lmfit ties Voigt gamma to sigma; the app sets a start value, which must not leave it
    fixed (the bug: gamma stayed at 8.000 while sigma compensated)."""
    peak = {"type": "Voigt", "center": 600, "height": 30, "sigma": 8, "gamma": 8}
    result = fe.FittingModels().fit_spectrum(
        x_nm, voigt(x_nm, 1000, 600, 5, 15), _fit_params([peak])
    )
    assert result.params["p0_gamma"].vary
    assert result.params["p0_gamma"].value == pytest.approx(15, rel=1e-3)


def test_voigt_fit_on_gaussian_data_does_not_stall_at_gamma_bound(fe, x_nm):
    """A gamma start on its lower bound gave lmfit no gradient and froze the whole fit."""
    y = gaussian(x_nm, 1000, 600, 10) + np.random.default_rng(0).normal(0, 0.3, x_nm.size)
    peak = {"type": "Voigt", "center": 600, "height": 30, "sigma": 8, "gamma": 0.0}
    result = fe.FittingModels().fit_spectrum(x_nm, y, _fit_params([peak]))
    assert result.params["p0_sigma"].value == pytest.approx(10, rel=0.01)  # stalled: 8.000
    assert result.rsquared > 0.99  # stalled: 0.85


def test_fix_gamma_checkbox_still_freezes_gamma(fe, x_nm):
    peak = {"type": "Voigt", "center": 600, "height": 30, "sigma": 8, "gamma": 8, "fix_gamma": True}
    result = fe.FittingModels().fit_spectrum(
        x_nm, voigt(x_nm, 1000, 600, 5, 15), _fit_params([peak])
    )
    assert not result.params["p0_gamma"].vary
    assert result.params["p0_gamma"].value == 8


def test_one_sided_user_bound_is_respected(fe, x_nm):
    peak = {"type": "Gaussian", "center": 600, "height": 30, "sigma": 8, "center_max": 610}
    _, params = fe.FittingModels().create_composite_model(_fit_params([peak]))
    assert params["p0_center"].max == 610
    assert params["p0_center"].min == pytest.approx(550)  # auto: center - center_bound


def test_center_bound_none_falls_back_to_default(fe, cfg):
    engine = fe.FittingEngine()
    engine.create_fit_parameters(
        [{"type": "Gaussian", "center": 600, "height": 1, "sigma": 5}], center_bound=None
    )
    assert engine.fit_params["center_bound"] == cfg.DEFAULT_CENTER_BOUND


def test_fit_ignores_nan_and_inf_points(fe, x_nm):
    y = gaussian(x_nm, 1000, 600, 10)
    y[[10, 200, 400]] = np.nan
    y[[300, 500]] = np.inf
    peak = {"type": "Gaussian", "center": 600, "height": 30, "sigma": 8}
    result = fe.FittingModels().fit_spectrum(x_nm, y, _fit_params([peak]))
    assert len(result.fit_x) == x_nm.size - 5
    assert result.params["p0_center"].value == pytest.approx(600, abs=1e-3)


def test_batch_fit_with_different_valid_range_per_frame(fe, x_nm):
    """Each frame padded with NaN differently, as for per-frame x ranges."""
    centers = [560, 580, 600, 620]
    data = np.array([gaussian(x_nm, 1000, c, 12) + 1 for c in centers])
    data[1, :100] = np.nan
    data[2, -150:] = np.nan
    data[3, :50] = np.nan
    data[3, [300, 301, 450]] = np.inf
    _, results = _batch(
        fe, x_nm, data, [{"type": "Gaussian", "center": 590, "height": 30, "sigma": 10}]
    )
    for i, c in enumerate(centers):
        assert results[i]["success"]
        assert len(results[i]["fit_x"]) == np.isfinite(data[i]).sum()
        assert results[i]["parameters"]["p0_center"]["value"] == pytest.approx(c, abs=0.01)


def test_all_nan_frame_fails_cleanly(fe, x_nm):
    data = np.array([gaussian(x_nm, 1000, 600, 12), np.full(x_nm.size, np.nan)])
    _, results = _batch(
        fe, x_nm, data, [{"type": "Gaussian", "center": 600, "height": 30, "sigma": 10}]
    )
    assert results[0]["success"]
    assert not results[1]["success"]
    assert "finite" in results[1]["error"]


def test_sequential_and_parallel_agree(fe, x_nm, app_modules_importable):
    data = np.array([gaussian(x_nm, 1000, 590 + 5 * k, 12) for k in range(4)])
    peaks = [{"type": "Lorentzian", "center": 595, "height": 30, "sigma": 10}]
    _, seq = _batch(fe, x_nm, data, peaks, sequential=True)
    _, par = _batch(fe, x_nm, data, peaks, sequential=False)
    for i in range(4):
        assert par[i]["success"]
        for name in ("p0_center", "p0_sigma", "p0_amplitude"):
            assert par[i]["parameters"][name]["value"] == pytest.approx(
                seq[i]["parameters"][name]["value"], rel=1e-4
            )


@pytest.mark.parametrize("peak_type", PEAK_TYPES)
def test_sequential_seed_starts_from_previous_height(fe, x_nm, peak_type):
    """The next frame starts at the previous fitted height, unconverted, and its area at
    the matching value (an old amplitude->height->amplitude round trip restarted
    Lorentzians at 1.25x the previous amplitude)."""
    models = fe.FittingModels()
    peak = {"type": peak_type, "center": 600, "height": 30, "sigma": 8, "gamma": 1.0}
    fit_params = _fit_params([peak])
    previous = {
        "index": 0,
        "time": 0.0,
        "parameters": {
            "p0_height": {"value": 42.0},
            "p0_sigma": {"value": 10.0},
            "p0_center": {"value": 601.0},
        },
    }
    _, params = models.create_composite_model(models._apply_smart_init(fit_params, previous))
    assert params["p0_height"].value == pytest.approx(42.0)
    assert params["p0_center"].value == pytest.approx(601.0)
    values = {name[3:]: p.value for name, p in params.items() if name.startswith("p0_")}
    assert _curve_max(peak_type, values) == pytest.approx(42.0, rel=1e-6)


def test_batch_settings_are_the_batch_fits_not_a_later_single_fit(fe, x_nm):
    data = np.array([gaussian(x_nm, 1000, 600, 12) + 0.05 * x_nm for _ in range(2)])
    engine = fe.FittingEngine()
    engine.create_fit_parameters(
        [{"type": "Gaussian", "center": 600, "height": 30, "sigma": 10}],
        background_model="Linear",
        center_bound=30,
    )
    mask = (x_nm >= 500) & (x_nm <= 700)
    engine.fit_all_spectra(x_nm[mask], data[:, mask], np.arange(2.0), use_smart_init=True)
    engine.create_fit_parameters(
        [{"type": "Lorentzian", "center": 600, "height": 30, "sigma": 10}],
        background_model="None",
        center_bound=None,
    )
    engine.fit_current_spectrum(x_nm, data[0])
    assert engine.batch_settings == {
        "background_model": "Linear",
        "poly_degree": 2,
        "center_bound": 30,
        "fit_x_min": 500.0,
        "fit_x_max": 700.0,
    }


# =============================================================================
# Derived peak values
# =============================================================================


def test_skewed_shape_reduces_to_exact_gaussian_at_zero_skew(fe):
    r = fe.skewed_peak_shape(
        "Skewed Gaussian", {"amplitude": 1000, "center": 600, "sigma": 10, "gamma": 0.0}
    )
    assert r["position"] == pytest.approx(600, abs=1e-6)
    assert r["height"] == pytest.approx(1000 / (10 * np.sqrt(2 * np.pi)), rel=1e-6)
    assert r["fwhm"] == pytest.approx(2 * np.sqrt(2 * np.log(2)) * 10, rel=1e-4)


@pytest.mark.parametrize(
    "peak_type, values",
    [
        ("Skewed Gaussian", {"amplitude": 1000, "center": 600, "sigma": 10, "gamma": 3}),
        ("Skewed Gaussian", {"amplitude": 1000, "center": 600, "sigma": 10, "gamma": -8}),
        ("Skewed Gaussian", {"amplitude": 5, "center": 1.8, "sigma": 0.05, "gamma": 2}),
        ("Skewed Voigt", {"amplitude": 1000, "center": 600, "sigma": 5, "gamma": 10, "skew": 2}),
        ("Skewed Voigt", {"amplitude": 1000, "center": 600, "sigma": 5, "gamma": 1, "skew": -5}),
    ],
)
def test_skewed_shape_matches_brute_force(fe, peak_type, values):
    x = np.linspace(
        values["center"] - 60 * values["sigma"], values["center"] + 60 * values["sigma"], 2_000_001
    )
    if peak_type == "Skewed Gaussian":
        y = skewed_gaussian(
            x, values["amplitude"], values["center"], values["sigma"], values["gamma"]
        )
    else:
        y = skewed_voigt(
            x,
            values["amplitude"],
            values["center"],
            values["sigma"],
            values["gamma"],
            values["skew"],
        )
    above = x[y >= y.max() / 2]
    r = fe.skewed_peak_shape(peak_type, values)
    step = 1e-3 * values["sigma"]
    assert r["position"] == pytest.approx(x[np.argmax(y)], abs=step)
    assert r["height"] == pytest.approx(y.max(), rel=1e-4)
    assert r["fwhm"] == pytest.approx(above.max() - above.min(), abs=step)


def test_skewed_batch_results_carry_position_height_fwhm(fe, x_nm):
    data = np.array([skewed_gaussian(x_nm, 1000, 560, 12, 3)])
    _, results = _batch(
        fe,
        x_nm,
        data,
        [{"type": "Skewed Gaussian", "center": 565, "height": 40, "sigma": 10, "gamma": 0.0}],
    )
    params = results[0]["parameters"]
    assert params["p0_center"]["value"] == pytest.approx(560, abs=1e-3)
    assert params["p0_position"]["value"] == pytest.approx(565.68, abs=0.01)
    assert params["p0_position"]["stderr"] is None
    assert {"p0_height", "p0_fwhm"} <= params.keys()


def test_area_is_integral_and_width_10pct_matches_definition(fe, ex, x_nm):
    data = np.array([gaussian(x_nm, 700, 600, 9)])
    _, results = _batch(
        fe, x_nm, data, [{"type": "Gaussian", "center": 600, "height": 30, "sigma": 8}]
    )
    df, _ = ex.ResultExporter()._create_peak_parameters_dataframe(results)
    assert df["p0_area"][0] == pytest.approx(np.trapezoid(data[0], x_nm), rel=1e-4)
    assert df["p0_width_10pct"][0] == pytest.approx(2 * np.sqrt(2 * np.log(10)) * 9, rel=1e-3)
    assert "p0_amplitude" not in df.columns


# =============================================================================
# Units, metadata, export
# =============================================================================


@pytest.mark.parametrize(
    "param, model, expected",
    [
        ("center", "Gaussian", "nm"),
        ("position", "Skewed Gaussian", "nm"),
        ("area", "Voigt", "-"),
        ("amplitude", "Lorentzian", "-"),
        ("height", "Gaussian", "-"),
        ("gamma", "Voigt", "nm"),
        ("gamma", "Skewed Voigt", "nm"),
        ("gamma", "Skewed Gaussian", "-"),
        ("skew", "Skewed Voigt", "-"),
        ("c2", "Polynomial", None),
    ],
)
def test_parameter_unit(ex, param, model, expected):
    assert ex.parameter_unit(param, model, "nm") == expected


def test_app_version_is_read_from_pyproject(cfg):
    text = (APP_DIR / "pyproject.toml").read_text(encoding="utf-8")
    assert cfg.APP_VERSION == re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def test_h5_export_writes_metadata_and_units(fe, ex, x_nm, tmp_path):
    data = np.array([voigt(x_nm, 1000, 520, 5, 8) + skewed_gaussian(x_nm, 800, 680, 12, 2)])
    peaks = [
        {"type": "Voigt", "center": 520, "height": 30, "sigma": 6, "gamma": 0.0, "name": "V"},
        {
            "type": "Skewed Gaussian",
            "center": 680,
            "height": 30,
            "sigma": 10,
            "gamma": 0.0,
            "name": "S",
        },
    ]
    engine, results = _batch(fe, x_nm, data, peaks)
    path = tmp_path / "fit.h5"
    h5py.File(path, "w").close()
    ex.ResultExporter().export_to_isa_h5(
        results, str(path), wavelength_unit="nm", fit_settings=engine.batch_settings
    )
    with h5py.File(path, "r") as f:
        (group,) = f["fitting_results"].values()
        attrs = dict(group.attrs)
        units = {name: group[name].attrs.get("unit") for name in group}
    assert attrs["peak_explorer_version"] == _version_from_pyproject()
    assert attrs["x_unit"] == "nm"
    assert attrs["fit_mode"] == "sequential"
    assert [p["name"] for p in json.loads(attrs["peak_models"])] == ["V", "S"]
    assert attrs["background_model"] == "None"
    assert attrs["center_bound"] == 50
    assert units["p0_gamma"] == "nm" and units["p1_gamma"] == "-"
    assert units["p0_area"] == "-" and units["p1_position"] == "nm"
    assert units["p0_height"] == "-"


def _version_from_pyproject():
    text = (APP_DIR / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def test_excel_and_csv_exports_write_their_files(fe, ex, x_nm, tmp_path):
    pytest.importorskip("openpyxl")
    data = np.array([gaussian(x_nm, 1000, 600, 12) for _ in range(3)])
    _, results = _batch(
        fe, x_nm, data, [{"type": "Gaussian", "center": 600, "height": 30, "sigma": 10}]
    )
    exporter = ex.ResultExporter()
    xlsx = exporter.export_to_excel(results, np.arange(3.0), filename=str(tmp_path / "r.xlsx"))
    assert set(pd.read_excel(xlsx, sheet_name=None)) == {
        "Peak_Parameters",
        "Standard_Errors",
        "Fitting_Quality",
    }
    out = exporter.export_to_csv(results, output_dir=str(tmp_path / "csv"))
    quality = pd.read_csv(f"{out}/fitting_quality.csv")
    assert len(pd.read_csv(f"{out}/peak_parameters.csv")) == 3
    assert (quality["RMSE"] < 1e-3).all()


@BUG("export_to_json writes Infinity for unbounded parameter limits")
def test_json_export_is_valid_json(fe, ex, x_nm, tmp_path):
    """JSON has no Infinity/NaN; other tools reject a file that contains them."""
    data = np.array([gaussian(x_nm, 1000, 600, 12)])
    _, results = _batch(
        fe, x_nm, data, [{"type": "Gaussian", "center": 600, "height": 30, "sigma": 10}]
    )
    path = tmp_path / "r.json"
    ex.ResultExporter().export_to_json(results, filename=str(path))

    def reject(constant):
        raise ValueError(f"not valid JSON: {constant}")

    json.loads(path.read_text(), parse_constant=reject)


# =============================================================================
# Loading: CSV / TXT
# =============================================================================

PL_FILE = (
    "Sample,ABC-123\n"
    "Integration time,100 ms\n"
    "Wavelength (nm),10.0,10.5,11.0\n"
    "500,1,2,3\n"
    "501,4,5,6\n"
    "502,7,8,9\n"
)


def test_csv_pl_format(dm):
    loader = dm.CSVDataLoader()
    data, wl, t, unit = loader.load_data(PL_FILE.encode())
    assert unit == "nm"
    np.testing.assert_allclose(wl, [500, 501, 502])
    np.testing.assert_allclose(t, [0.0, 0.5, 1.0])  # normalised to start at 0
    np.testing.assert_allclose(data, [[1, 4, 7], [2, 5, 8], [3, 6, 9]])  # time x wavelength
    assert loader.get_header_info() == {"Sample": "ABC-123", "Integration time": "100 ms"}


def test_csv_simple_format(dm):
    content = ",500,501,502\n0.0,1,2,3\n0.5,4,5,6\n"
    data, wl, t = dm.CSVDataLoader().load_data(content.encode())
    np.testing.assert_allclose(wl, [500, 501, 502])
    np.testing.assert_allclose(t, [0.0, 0.5])
    np.testing.assert_allclose(data, [[1, 2, 3], [4, 5, 6]])


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig"])
def test_csv_with_bom_and_crlf(dm, encoding):
    content = PL_FILE.replace("\n", "\r\n").encode(encoding)
    data, wl, t, _ = dm.CSVDataLoader().load_data(content)
    assert data.shape == (3, 3)
    np.testing.assert_allclose(t, [0.0, 0.5, 1.0])


@BUG("any line with 'wavelength' in the first 50 is taken as the header row")
def test_csv_metadata_mentioning_wavelength_is_not_taken_as_header(dm):
    """PL files often carry e.g. 'Excitation wavelength' in their metadata block."""
    content = "Excitation wavelength,405 nm\n" + PL_FILE
    data, wl, t, _ = dm.CSVDataLoader().load_data(content.encode())
    np.testing.assert_allclose(wl, [500, 501, 502])
    assert data.shape == (3, 3)


@BUG("an empty timestamp list raises IndexError from a debug f-string")
def test_csv_header_without_timestamps_raises_a_clear_error(dm):
    content = "Wavelength (nm)\n500,1\n501,2\n"
    with pytest.raises(ValueError):
        dm.CSVDataLoader().load_data(content.encode())


@pytest.mark.xfail(strict=True, reason="Known TODO: CSV/TXT loading replaces NaN/inf with 0")
def test_csv_keeps_missing_values_as_nan(dm):
    content = PL_FILE.replace("501,4,5,6", "501,4,,nan")
    data, *_ = dm.CSVDataLoader().load_data(content.encode())
    assert np.isnan(data[1, 1]) and np.isnan(data[2, 1])


# =============================================================================
# Loading: H5
# =============================================================================


@pytest.mark.parametrize(
    "mode",
    [
        "pl_raw",
        "pl_binned",
        "giwaxs",
        "giwaxs_diamond",
        "transmission_raw",
        "transmission_binned",
        "absorbance_raw",
        "absorbance_binned",
    ],
)
def test_every_h5_mode_loads_consistent_shapes(dm, cfg, tmp_path, mode):
    path = tmp_path / "d.h5"
    _write_h5(path, cfg)
    data, y, t, unit, time_unit, _ = dm.H5DataLoader().load_h5_data(mode, str(path))
    assert data.shape == (len(t), len(y))
    assert unit == ("1/Å" if "giwaxs" in mode else "nm")


def test_giwaxs_time_unit_comes_from_the_attribute(dm, cfg, tmp_path):
    path = tmp_path / "d.h5"
    _write_h5(path, cfg)
    # Both GIWAXS modes read the same timestamps dataset
    assert dm.H5DataLoader().load_h5_data("giwaxs", str(path))[4] == "min"
    assert dm.H5DataLoader().load_h5_data("giwaxs_diamond", str(path))[4] == "min"


def test_absorbance_is_minus_log_of_transmission_over_reference(dm, cfg, tmp_path):
    path = tmp_path / "d.h5"
    _write_h5(path, cfg)
    data, *_ = dm.H5DataLoader().load_h5_data("absorbance_raw", str(path))
    assert np.allclose(data[0], 0.0)
    assert np.allclose(data[-1], np.log(2))


def test_absorbance_reference_ignores_nan(dm, cfg, tmp_path):
    path = tmp_path / "d.h5"
    _write_h5(path, cfg)
    with h5py.File(path, "a") as f:
        ds = f[cfg.H5_PATHS["transmission_raw"]["data"]]
        values = ds[()]
        values[3, 1] = np.nan
        ds[...] = values
    data, *_ = dm.H5DataLoader().load_h5_data("absorbance_raw", str(path))
    assert np.isfinite(data[-1, 1])


@pytest.mark.parametrize("mode", ["pl_raw", "giwaxs", "giwaxs_diamond", "absorbance_raw"])
def test_trailing_nan_timestamp_drops_its_data_row_too(dm, cfg, tmp_path, mode):
    """Real beamline logging ends with a NaN time entry, and the data has a row for it."""
    path = tmp_path / "d.h5"
    _write_h5(path, cfg, trailing_nan_time=True)
    with h5py.File(path, "r") as f:
        stored = f[cfg.H5_PATHS[mode.replace("absorbance", "transmission")]["data"]][()]
    data, y, t, *_ = dm.H5DataLoader().load_h5_data(mode, str(path))
    assert not np.isnan(t).any()
    assert len(t) == stored.shape[0] - 1
    assert data.shape[0] == len(t)
    if mode != "absorbance_raw":  # absorbance is derived, not the stored values
        np.testing.assert_array_equal(data, stored[:-1])


def test_data_info_intensity_range_ignores_nan_and_inf(dm):
    """The heatmap colour range comes from here; absorbance data (values ~0 to 2) with a
    single NaN or inf must not fall back to the 0 to 1000 default."""
    manager = dm.DataManager()
    manager.data_matrix = np.array([[0.1, 0.5, np.nan], [0.2, np.inf, 1.5]])
    manager.wavelengths = np.array([500.0, 501.0, 502.0])
    manager.timestamps = np.array([0.0, 1.0])
    assert manager.get_data_info()["intensity_range"] == (0.1, 1.5)


def test_data_info_intensity_range_without_finite_values_uses_default(dm):
    manager = dm.DataManager()
    manager.data_matrix = np.full((2, 3), np.nan)
    manager.wavelengths = np.array([500.0, 501.0, 502.0])
    manager.timestamps = np.array([0.0, 1.0])
    assert manager.get_data_info()["intensity_range"] == (0.0, 1000.0)


def test_nm_ev_round_trip_restores_data(dm):
    manager = dm.DataManager()
    wl = np.linspace(400, 800, 50)
    data = np.random.default_rng(0).random((3, 50))
    manager.data_matrix, manager.wavelengths, manager.timestamps = (
        data.copy(),
        wl.copy(),
        np.arange(3.0),
    )
    manager.convert_wavelength_to_energy()
    assert np.all(np.diff(manager.wavelengths) > 0)
    np.testing.assert_allclose(manager.wavelengths[0], 1239.8 / 800)
    manager.convert_energy_to_wavelength()
    np.testing.assert_allclose(manager.wavelengths, wl)
    np.testing.assert_allclose(manager.data_matrix, data)


# =============================================================================
# GUI handlers, headless
# =============================================================================


def _two_peaks(x, noise=0.3, seed=1):
    """Heights about 33 and 27, both well above the default prominence threshold
    (2 x std of the spectrum), which depends on how much baseline the spectrum has."""
    rng = np.random.default_rng(seed)
    return (
        gaussian(x, 1000, 520, 12) + gaussian(x, 1200, 680, 18) + 2 + rng.normal(0, noise, x.size)
    )


def _detected_centers(application):
    return sorted(float(m._widgets["center"].value) for m in application.peak_models)


def _prepare_detection(application):
    for key in ("peak_height_threshold", "peak_prominence"):
        application.widgets[key].value = 0


def test_auto_detect_finds_peaks_despite_nan_and_inf(app, x_nm):
    y = _two_peaks(x_nm)
    y[:60], y[-90:], y[[300, 301]] = np.nan, np.nan, np.nan
    y[400] = np.inf
    application = app([y], x_nm)
    _prepare_detection(application)
    application.on_auto_detect_peaks(None)
    # Detection returns the highest data point, which noise moves by a nm or two
    assert _detected_centers(application) == pytest.approx([520, 680], abs=3)


def test_auto_detect_on_all_nan_spectrum_finds_nothing(app, x_nm):
    application = app([np.full(x_nm.size, np.nan)], x_nm)
    _prepare_detection(application)
    application.on_auto_detect_peaks(None)
    assert application.peak_models == []


def test_manual_background_ignores_nan_frames(app, x_nm):
    frames = np.array([np.full(x_nm.size, 2.0), np.full(x_nm.size, 4.0), _two_peaks(x_nm)])
    frames[0, :10] = np.nan
    application = app(frames, x_nm)
    application.widgets["background_method"].value = "Manual"
    application.widgets["bg_manual_start"].value = 0
    application.widgets["bg_manual_num"].value = 2
    application.on_background_apply(None)
    assert application.background_applied
    assert np.isfinite(application.background_model).all()
    assert application.background_model[0] == pytest.approx(4.0)  # frame 1 only
    assert application.background_model[20] == pytest.approx(3.0)  # mean of both


def test_background_apply_then_remove_restores_the_data(app, x_nm):
    frames = np.array([_two_peaks(x_nm, seed=s) for s in range(3)])
    application = app(frames, x_nm)
    application.widgets["background_method"].value = "Linear"
    application.widgets["bg_linear_slope"].value = 0.01
    application.widgets["bg_linear_intercept"].value = 1.0
    application.on_background_apply(None)
    assert not np.allclose(application.data_manager.data_matrix, frames)
    application.on_background_remove(None)
    np.testing.assert_allclose(application.data_manager.data_matrix, frames)


@BUG("the stored original data is not reversed by the nm/eV conversion")
def test_background_remove_after_ev_conversion_keeps_axis_order(app, x_nm):
    """Removing a background restores the stored original; after nm -> eV the axis is
    reversed, so the restored data has to be in eV order too."""
    frames = np.array([_two_peaks(x_nm, seed=s) for s in range(2)])
    application = app(frames, x_nm)
    application.widgets["background_method"].value = "Linear"
    application.widgets["bg_linear_slope"].value = 0.0
    application.widgets["bg_linear_intercept"].value = 1.0
    application.on_background_apply(None)
    application.on_convert_energy(None)
    application.on_background_remove(None)
    np.testing.assert_allclose(application.data_manager.data_matrix, frames[:, ::-1])


@BUG("np.polyfit on a spectrum with NaN returns NaN coefficients")
def test_background_autofit_ignores_nan(app, x_nm):
    y = 0.02 * x_nm + 3.0
    y[[5, 100, 700]] = np.nan
    application = app([y], x_nm)
    application.widgets["background_method"].value = "Linear"
    application.on_background_autofit(None)
    assert application.widgets["bg_linear_slope"].value == pytest.approx(0.02)
    assert application.widgets["bg_linear_intercept"].value == pytest.approx(3.0)


def test_fit_visualisation_raw_trace_matches_its_x_axis(fe, pm, x_nm):
    data = np.array([gaussian(x_nm, 1000, 600, 12) + 1])
    data[0, [100, 350]] = np.nan
    engine, results = _batch(
        fe, x_nm, data, [{"type": "Gaussian", "center": 600, "height": 30, "sigma": 10}]
    )
    fig = pm.PlotManager().create_fit_vis_plot(results[0], engine.fit_wavelengths, data[0])
    assert all(len(trace.x) == len(trace.y) for trace in fig.data)


def test_gui_builds_with_all_widgets_in_the_layout(gl):
    application = gl.PLAnalysisApp()
    _, main = application.gui_layouts.create_main_layout()

    def walk(widget):
        yield widget
        for child in getattr(widget, "children", ()) or ():
            yield from walk(child)

    in_tree = {id(w) for w in walk(main)}
    for key in ("center_bound_input", "fit_sequential_checkbox", "save_h5_btn"):
        assert id(application.widgets[key]) in in_tree


@pytest.mark.parametrize(
    "span, step, decimals",
    [(2.0, 0.001, 3), (1.5, 0.001, 3), (5000.0, 1.0, 0), (60000.0, 10.0, 0), (0.02, 1e-5, 5)],
)
def test_colour_slider_step_follows_the_data_range(gl, span, step, decimals):
    assert gl._slider_step(span) == (pytest.approx(step), decimals)


def test_colour_slider_after_loading_absorbance_with_nan_and_inf(app, x_nm):
    """Absorbance (~0 to 2) with one NaN and one inf: the colour range must be the data's,
    fine enough to adjust, and not the 0 to 1000 fallback."""
    absorbance = np.linspace(0.05, 1.85, x_nm.size)[None, :].repeat(3, axis=0)
    absorbance[0, 10] = np.nan
    absorbance[1, 20] = np.inf
    application = app(absorbance, x_nm)
    application.update_ui_after_data_load()
    slider = application.widgets["colorbar_range_slider"]
    assert slider.value == pytest.approx((0.05, 1.85))
    assert slider.step == pytest.approx(0.001)
    assert slider.readout_format == ".3f"


def test_widgets_get_no_arguments_they_ignore(gl):
    """ipywidgets ignores unknown arguments with only a DeprecationWarning; that is how
    min/max on plain IntText fields and invalid style/layout keys went unnoticed."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        application = gl.PLAnalysisApp()
        application.add_peak_model(
            peak_info={"type": "Polynomial", "center": 600, "height": 1, "sigma": 5}
        )
    ignored = [str(w.message) for w in caught if "unrecognized arguments" in str(w.message)]
    assert ignored == []


@pytest.mark.parametrize(
    "key, too_low, too_high, low, high",
    [("bg_poly_degree", 0, 50, 1, 10), ("peak_distance", 0, 10**6, 1, 10000)],
)
def test_number_fields_keep_values_in_range(gl, key, too_low, too_high, low, high):
    field = gl.PLAnalysisApp().widgets[key]
    field.value = too_low
    assert field.value == low
    field.value = too_high
    assert field.value == high


def test_polynomial_peak_degree_field_is_bounded(gl):
    application = gl.PLAnalysisApp()
    application.add_peak_model(
        peak_info={"type": "Polynomial", "center": 600, "height": 1, "sigma": 5}
    )
    degree = application.peak_models[-1]._widgets["poly_degree"]
    degree.value = 9
    assert degree.value == 5


def test_debug_panel_scrolls(gl):
    assert gl.debug_output.layout.overflow == "auto"


def test_peak_detection_fields_explain_themselves(gl):
    widgets = gl.PLAnalysisApp().widgets
    for key in ("auto_detect_btn", "peak_height_threshold", "peak_prominence", "peak_distance"):
        assert widgets[key].tooltip, key
    assert "data points" in widgets["peak_distance"].tooltip
    for key in ("peak_height_threshold", "peak_prominence"):
        assert "0 = automatic" in widgets[key].tooltip


# =============================================================================
# Height: fitted directly, "Fix height", height bounds, "Update from Fit"
# =============================================================================

_TRUE = {
    "Gaussian": {"amplitude": 1000, "center": 600, "sigma": 12},
    "Lorentzian": {"amplitude": 1000, "center": 600, "sigma": 12},
    "Voigt": {"amplitude": 1000, "center": 600, "sigma": 6, "gamma": 8},
    "Skewed Gaussian": {"amplitude": 1000, "center": 600, "sigma": 12, "gamma": 3},
    "Skewed Voigt": {"amplitude": 1000, "center": 600, "sigma": 6, "gamma": 8, "skew": 2},
}


def _start_peak(peak_type, **extra):
    gamma = 3.0 if "Voigt" in peak_type else 0.0
    return {"type": peak_type, "center": 600, "height": 30, "sigma": 8, "gamma": gamma, **extra}


def _fit_one(fe, x, peak_type, noise=0.0, **extra):
    y = _SHAPES[peak_type](x, _TRUE[peak_type])
    if noise:
        y = y + np.random.default_rng(0).normal(0, noise, x.size)
    return fe.FittingModels().fit_spectrum(x, y, _fit_params([_start_peak(peak_type, **extra)]))


def _values(result):
    return {name[3:]: p.value for name, p in result.params.items() if name.startswith("p0_")}


@pytest.mark.parametrize("peak_type", PEAK_TYPES)
def test_fitted_height_is_the_peak_maximum(fe, x_nm, peak_type):
    result = _fit_one(fe, x_nm, peak_type)
    expected = _curve_max(peak_type, _TRUE[peak_type])
    assert result.params["p0_height"].value == pytest.approx(expected, rel=1e-4)


@pytest.mark.parametrize("peak_type", PEAK_TYPES)
def test_fix_height_keeps_the_typed_height(fe, x_nm, peak_type):
    """ "Fix" freezes the value in the field above it. It used to freeze the area, so the
    height still moved with the width: 26.9 to 43.2 instead of the typed 30."""
    result = _fit_one(fe, x_nm, peak_type, fix_height=True)
    assert not result.params["p0_height"].vary
    assert result.params["p0_height"].value == 30
    assert _curve_max(peak_type, _values(result)) == pytest.approx(30, rel=1e-5)


@pytest.mark.parametrize("peak_type", PEAK_TYPES)
def test_height_bounds_apply_to_the_height(fe, x_nm, peak_type):
    """Every true height here is above 20, so the fit ends on the bound."""
    result = _fit_one(fe, x_nm, peak_type, height_max=20.0)
    assert result.params["p0_height"].value <= 20.0 + 1e-9
    assert _curve_max(peak_type, _values(result)) <= 20.0 * (1 + 1e-5)


@pytest.mark.parametrize("peak_type", PEAK_TYPES)
def test_height_has_an_error_bar_on_noisy_data(fe, x_nm, peak_type):
    result = _fit_one(fe, x_nm, peak_type, noise=0.3)
    assert result.params["p0_height"].stderr is not None
    assert 0 < result.params["p0_height"].stderr < 1


@pytest.mark.parametrize("peak_type", ["Lorentzian", "Skewed Voigt"])
def test_update_from_fit_writes_the_real_height(app, x_nm, peak_type):
    """The Height field used to get a Gaussian-formula height for every peak type."""
    application = app([_SHAPES[peak_type](x_nm, _TRUE[peak_type])], x_nm)
    application.clear_peak_models()
    application.add_peak_model(peak_info=_start_peak(peak_type))
    application.on_fit_current(None)  # fills the fields itself when R2 > 0.5
    height_field = application.peak_models[0]._widgets["height"].value
    assert height_field == pytest.approx(_curve_max(peak_type, _TRUE[peak_type]), abs=2e-3)


def test_every_fix_checkbox_explains_what_it_fixes(gl):
    application = gl.PLAnalysisApp()
    application.add_peak_model(peak_info=_start_peak("Voigt"))
    fields = application.peak_models[-1]._widgets
    for key in ("fix_center", "fix_height", "fix_sigma", "fix_gamma"):
        assert "value above" in fields[key].tooltip, key
