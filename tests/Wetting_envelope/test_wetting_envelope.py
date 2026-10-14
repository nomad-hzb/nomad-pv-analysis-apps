import plotly.graph_objects as go
import pytest
from data_manager import Material, Solvent, WettingCalculator, WettingDataManager
from plot_manager import WettingPlotManager


def test_add_material_populates_manager():
    dm = WettingDataManager()
    ok, msg = dm.add_material(name="PTFE", polar=0.0, dispersive=18.0, theta=10.0)

    assert ok is True
    assert "PTFE" in msg
    assert dm.has_data is True
    assert len(dm.materials) == 1
    assert dm.materials[0].name == "PTFE"
    assert dm.materials[0].dispersive == pytest.approx(18.0)


def test_add_solvent_populates_manager():
    dm = WettingDataManager()
    ok, _ = dm.add_solvent(name="Water", polar=51.0, dispersive=21.8)

    assert ok is True
    assert len(dm.solvents) == 1
    assert dm.solvents[0].polar == pytest.approx(51.0)


def test_add_material_invalid_theta_handled_gracefully():
    dm = WettingDataManager()
    ok, msg = dm.add_material(name="Bad", polar=1.0, dispersive=1.0, theta=200.0)

    assert ok is False
    assert dm.has_data is False
    assert len(dm.materials) == 0
    assert "179" in msg


def test_remove_material_and_clear():
    dm = WettingDataManager()
    dm.add_material(name="PTFE", polar=0.0, dispersive=18.0)
    dm.add_solvent(name="Water", polar=51.0, dispersive=21.8)

    dm.remove_material(0)
    assert dm.materials == []

    dm.add_material(name="PTFE", polar=0.0, dispersive=18.0)
    dm.clear()
    assert dm.materials == []
    assert dm.solvents == []


def test_envelope_xy_returns_matching_length_arrays():
    material = Material(name="PTFE", polar=0.0, dispersive=18.0, theta=0.0)
    x, y = WettingCalculator.envelope_xy(material)

    assert len(x) == WettingCalculator.N_POINTS
    assert len(y) == WettingCalculator.N_POINTS


def test_wetting_envelope_returns_figure_with_expected_traces():
    materials = [Material(name="PTFE", polar=0.0, dispersive=18.0, theta=0.0)]
    solvents = [Solvent(name="Water", polar=51.0, dispersive=21.8)]

    fig = WettingPlotManager.wetting_envelope(
        materials=materials, solvents=solvents, title="Test Plot"
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2
    assert fig.data[0].mode == "lines"
    assert fig.data[0].name == "PTFE"
    assert fig.data[1].mode == "markers"
    assert fig.data[1].name == "Water"
    assert fig.data[1].x[0] == pytest.approx(21.8)
    assert fig.data[1].y[0] == pytest.approx(51.0)
    assert fig.layout.title.text == "Test Plot"


def test_wetting_envelope_empty_input_returns_empty_figure():
    fig = WettingPlotManager.wetting_envelope(materials=[], solvents=[])

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


# ---------------------------------------------------------------------------
# 6.11: physics (a point on the envelope has the material's contact angle), presets, theta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theta", [0.0, 30.0, 60.0, 120.0])
@pytest.mark.parametrize(("polar", "dispersive"), [(5.43, 40.0), (0.0, 18.0), (62.0, 22.0)])
def test_every_envelope_point_gives_back_the_materials_contact_angle(polar, dispersive, theta):
    """Invert OWRK for a liquid on the curve: gamma_L (1 + cos theta) = 2 (sqrt(gs_d gl_d) +
    sqrt(gs_p gl_p)). The old free exponent only agreed at theta = 0."""
    import numpy as np

    material = Material(name="m", polar=polar, dispersive=dispersive, theta=theta)
    x, y = WettingCalculator.envelope_xy(material)
    keep = (x + y) > 0
    x, y = x[keep][1:-1], y[keep][1:-1]  # liquids with a real polar and dispersive part
    cos_theta = 2 * (np.sqrt(dispersive * x) + np.sqrt(polar * y)) / (x + y) - 1
    assert np.degrees(np.arccos(np.clip(cos_theta, -1, 1))) == pytest.approx(theta, abs=1e-3)


def test_theta_180_is_rejected_instead_of_giving_an_infinite_curve():
    dm = WettingDataManager()
    ok, msg = dm.add_material(name="x", polar=1.0, dispersive=1.0, theta=180.0)
    assert ok is False and "179" in msg
    ok, _ = dm.add_material(name="x", polar=1.0, dispersive=1.0, theta=179.0)
    assert ok is True


def test_preset_files_load_and_every_sourced_solvent_adds_up_to_its_total():
    from data_manager import PRESET_MATERIALS, PRESET_SOLVENTS

    assert len(PRESET_MATERIALS) >= 8 and len(PRESET_SOLVENTS) >= 10
    sourced = [s for s in PRESET_SOLVENTS if s["source"]]
    assert {s["name"] for s in sourced} >= {"Water", "Ethanol", "Ethylene glycol", "Chloroform"}
    for solvent in sourced:
        assert solvent["reference_url"], solvent["name"]
        total = solvent["polar"] + solvent["dispersive"]
        assert total == pytest.approx(solvent["literature_total"], abs=0.5), solvent["name"]


def test_preset_note_says_where_values_come_from_and_flags_sums_that_do_not_match():
    from data_manager import solvent_preset_note

    assert "Zdziennicka" in solvent_preset_note("Ethanol")
    assert "do not add up" not in solvent_preset_note("Ethanol")
    assert "do not add up" in solvent_preset_note("Acetone")
    assert "do not add up" in solvent_preset_note("Isopropanol (IPA)")
    assert solvent_preset_note("nothing") == ""


def test_a_missing_preset_file_gives_no_presets_and_a_reason_instead_of_a_crash():
    import data_manager as dm_module

    before = list(dm_module.PRESET_LOAD_ERRORS)
    assert dm_module.load_presets("does_not_exist.csv") == []
    assert len(dm_module.PRESET_LOAD_ERRORS) == len(before) + 1
    del dm_module.PRESET_LOAD_ERRORS[len(before) :]
