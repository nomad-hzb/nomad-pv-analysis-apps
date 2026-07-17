"""Pydantic model validation tests."""
import numpy as np
import pytest
from pydantic import ValidationError
from data_manager import TRPLRow


def test_valid_row_passes():
    row = TRPLRow(
        sample_id="S001",
        variation="ref",
        name="meas_1",
        counts=[1000.0, 800.0, 600.0],
        time=[0.0, 1e-9, 2e-9],
        ns_per_bin=1.0,
    )
    assert row.sample_id == "S001"
    assert row.ns_per_bin == 1.0


def test_optional_fields_default_to_none():
    row = TRPLRow(sample_id="S001")
    assert row.counts is None
    assert row.time is None
    assert row.ns_per_bin is None
    assert row.repetition_rate is None
    assert row.noise is None
    assert row.n0s is None


def test_numpy_array_coercion():
    """Validator must convert numpy arrays to plain Python lists."""
    row = TRPLRow(
        sample_id="S001",
        counts=np.array([1000.0, 800.0, 600.0]),
        time=np.array([0.0, 1e-9, 2e-9]),
    )
    assert isinstance(row.counts, list)
    assert isinstance(row.time, list)


def test_invalid_ns_per_bin_raises():
    with pytest.raises(ValidationError):
        TRPLRow(sample_id="S001", ns_per_bin="not-a-float")


def test_data_file_optional():
    row = TRPLRow(sample_id="S001")
    assert row.data_file is None
