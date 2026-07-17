from config import FieldSpec
from data_manager import DataManager
from schema import get_nested_field


class FakeClient:
    """Stands in for NomadClient.post_query -- never hits the real API."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.token = None
        self.api_url = "http://mock"
        self.calls = []

    def post_query(self, payload):
        self.calls.append(payload)
        return self.pages.pop(0)


def _manager_with(pages):
    dm = DataManager(api_url="http://mock", token=None)
    dm.client = FakeClient(pages)
    return dm


def test_field_spec_output_name_with_and_without_unit():
    plain = FieldSpec(path="a.b", name="Efficiency")
    with_unit = FieldSpec(path="a.b", name="Band gap", unit_label="eV")

    assert plain.output_name() == "Efficiency"
    assert with_unit.output_name() == "Band gap (eV)"


def test_get_nested_field_resolves_dotted_path():
    entry = {"results": {"properties": {"efficiency": 18.2}}}

    assert get_nested_field(entry, "results.properties.efficiency") == 18.2
    assert get_nested_field(entry, "results.properties.missing") is None
    assert get_nested_field(entry, "not.present.at.all") is None


def test_add_field_and_remove_field():
    dm = _manager_with([])
    spec = dm.make_field("results.properties.efficiency", "Efficiency")

    warning = dm.add_field(spec)
    assert warning is None
    assert dm.field_columns() == ["Efficiency"]

    duplicate_warning = dm.add_field(spec)
    assert duplicate_warning is not None

    dm.remove_field("Efficiency")
    assert dm.field_columns() == []


def test_run_builds_dataframe_from_paginated_entries():
    dm = _manager_with(
        [
            {
                "data": [
                    {"entry_id": "1", "results": {"properties": {"efficiency": 18.2}}},
                    {"entry_id": "2", "results": {"properties": {"efficiency": 20.5}}},
                ],
                "pagination": {"total": 2, "next_page_after_value": None},
            }
        ]
    )
    dm.add_field(dm.make_field("results.properties.efficiency", "Efficiency"))

    df = dm.run()

    assert list(df["entry_id"]) == ["1", "2"]
    assert list(df["Efficiency"]) == [18.2, 20.5]


def test_run_empty_result_returns_empty_dataframe():
    dm = _manager_with([{"data": [], "pagination": {"total": 0}}])
    dm.add_field(dm.make_field("results.properties.efficiency", "Efficiency"))

    df = dm.run()

    assert df.empty


def test_validate_reports_hits_and_coverage():
    dm = _manager_with(
        [
            {
                "data": [
                    {"entry_id": "1", "results": {"properties": {"efficiency": 18.2}}},
                    {"entry_id": "2", "results": {}},
                ],
                "pagination": {"total": 2},
            }
        ]
    )

    exists, coverage = dm.validate("results.properties.efficiency")

    assert exists is True
    assert coverage == 0.5
