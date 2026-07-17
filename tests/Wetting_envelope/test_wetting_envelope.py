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
    assert "180" in msg


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
