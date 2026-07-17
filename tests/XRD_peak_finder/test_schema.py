"""test_schema.py — XRDRow Pydantic model validation."""

import numpy as np
import pytest
from pydantic import ValidationError

from data_manager import XRDRow


def test_valid_row_passes():
    row = XRDRow(
        sample_id="S001",
        variation="ref",
        name="m1",
        angle=[10.0, 20.0],
        intensity=[100.0, 200.0],
    )
    assert row.sample_id == "S001"
    assert row.angle == [10.0, 20.0]


def test_optional_fields_default_to_none():
    row = XRDRow(sample_id="S001")
    assert row.angle is None
    assert row.intensity is None


def test_numpy_array_coercion():
    row = XRDRow(
        sample_id="S001",
        angle=np.array([10.0, 20.0, 30.0]),
        intensity=np.array([100.0, 500.0, 2000.0]),
    )
    assert isinstance(row.angle, list)
    assert isinstance(row.intensity, list)


def test_invalid_angle_type_raises():
    with pytest.raises(ValidationError):
        XRDRow(sample_id="S001", angle="not-a-list")


def test_meas_index_defaults_to_zero():
    row = XRDRow(sample_id="S001")
    assert row.meas_index == 0
