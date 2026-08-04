import io

import data_manager
import openpyxl
import pytest
from data_manager import (
    LABOR_ROLES,
    CostReference,
    LCCDataManager,
    MaterialRow,
    ProcessStepRow,
    cost_per_sample,
    discover_entry_types,
    effective_cost_range,
    extract_material_rows,
    extract_process_step_rows,
    fetch_process_entries,
    fetch_samples_per_batch,
    flatten_entry,
    load_default_cost_reference,
    parse_cost_reference_workbook,
)
from excel_export import (
    CAPITAL_HEADERS,
    LABOR_HEADERS,
    MATERIALS_HEADERS,
    PROCESSES_HEADERS,
    build_cost_reference_template,
    build_cost_reference_template_from_data,
    build_workbook,
)

# ---------------------------------------------------------------------------
# flatten_entry
# ---------------------------------------------------------------------------


def test_flatten_entry_nested_dict():
    flat = flatten_entry({"annealing": {"temperature": 120, "time": 30}})
    assert flat == {"annealing.temperature": 120, "annealing.time": 30}


def test_flatten_entry_single_item_list_unwrapped():
    flat = flatten_entry({"layer": [{"layer_material_name": "PbI2"}]})
    assert flat == {"layer.layer_material_name": "PbI2"}


def test_flatten_entry_multi_item_list_indexed():
    flat = flatten_entry({"recipe_steps": [{"time": 30}, {"time": 45}]})
    assert flat == {"recipe_steps.1.time": 30, "recipe_steps.2.time": 45}


def test_flatten_entry_empty_list_dropped():
    flat = flatten_entry({"layer": []})
    assert flat == {}


# ---------------------------------------------------------------------------
# extract_process_step_rows
# ---------------------------------------------------------------------------


def test_extract_process_step_rows_single_step_with_top_level_time():
    process_data = {
        "name": "ALD process",
        "positon_in_experimental_plan": 2,
        "location": "HyALD",
        "time": 1800,
        "rate": 0.1,
    }
    rows = extract_process_step_rows(process_data, "HySprint_ALD", "Batch1", 4, ["S1", "S2"])
    assert len(rows) == 1
    row = rows[0]
    assert row.step_index == 0
    assert row.duration_value == 1800
    assert row.rate_value == 0.1
    assert row.num_samples_covered == 4
    assert row.position_in_plan == 2
    assert row.location == "HyALD"


def test_extract_process_step_rows_expands_recipe_steps():
    process_data = {
        "positon_in_experimental_plan": 1,
        "recipe_steps": [
            {"time": 30, "speed": 1000},
            {"time": 45, "speed": 2000},
        ],
    }
    rows = extract_process_step_rows(process_data, "HySprint_SpinCoating", "Batch1", 1, ["S1"])
    # No fields exist outside recipe_steps here, so there is no separate
    # base (step_index 0) row - just the two expanded recipe_steps rows.
    assert len(rows) == 2
    assert all(row.step_label == "recipe_steps" for row in rows)
    assert {row.duration_value for row in rows} == {30, 45}
    assert {row.rate_value for row in rows} == {1000, 2000}


def test_extract_process_step_rows_skips_non_step_lists():
    """solute/solvent lists must not be treated as process steps - they
    belong on the Materials sheet instead."""
    process_data = {
        "positon_in_experimental_plan": 1,
        "solution": [
            {
                "solution_details": {
                    "solute": [
                        {"chemical_2": {"name": "PbI2"}, "concentration_mol": 1.4},
                        {"chemical_2": {"name": "MAI"}, "concentration_mol": 1.4},
                    ]
                }
            }
        ],
    }
    rows = extract_process_step_rows(process_data, "HySprint_SpinCoating", "Batch1", 1, ["S1"])
    assert all(not row.step_label.startswith("solution") for row in rows)


def test_extract_process_step_rows_missing_location_defaults_empty():
    process_data = {"positon_in_experimental_plan": 1, "method": "Cleaning"}
    rows = extract_process_step_rows(process_data, "HySprint_Cleaning", "Batch1", 1, ["S1"])
    assert rows[0].location == ""


# ---------------------------------------------------------------------------
# extract_material_rows
# ---------------------------------------------------------------------------


def test_extract_material_rows_solution_solute_and_solvent():
    process_data = {
        "solution": [
            {
                "solution_details": {
                    "solute": [{"chemical_2": {"name": "PbI2"}, "concentration_mol": 1.4}],
                    "solvent": [{"chemical_2": {"name": "DMF"}, "chemical_volume": 500}],
                }
            }
        ]
    }
    rows = extract_material_rows(process_data, "HySprint_SpinCoating", "Batch1", 2, ["S1", "S2"])
    names_roles = {(row.material_name, row.role) for row in rows}
    assert names_roles == {("PbI2", "solute"), ("DMF", "solvent")}

    pbi2 = next(row for row in rows if row.material_name == "PbI2")
    assert pbi2.molar_mass_g_per_mol == pytest.approx(461.01)
    assert pbi2.price_per_gram_est is not None
    assert pbi2.cas_number == "10101-63-0"  # from the static table, NOMAD didn't have one
    assert pbi2.num_samples_covered == 2


def test_extract_material_rows_unknown_chemical_has_no_reference():
    process_data = {"layer": [{"layer_material_name": "SomeNovelCompound"}]}
    rows = extract_material_rows(process_data, "HySprint_Evaporation", "Batch1", 1, ["S1"])
    assert len(rows) == 1
    assert rows[0].molar_mass_g_per_mol is None
    assert rows[0].price_per_gram_est is None
    assert rows[0].cas_number is None


def test_extract_material_rows_evaporant():
    process_data = {"organic_evaporation": [{"chemical_2": {"name": "C60"}, "thickness": 20}]}
    rows = extract_material_rows(process_data, "HySprint_Evaporation", "Batch1", 1, ["S1"])
    assert len(rows) == 1
    assert rows[0].role == "evaporant"
    assert rows[0].quantity_value == 20


def test_extract_material_rows_prefers_real_nomad_cas_over_static_table():
    """A real cas_number actually populated on NOMAD's chemical_2 reference
    is authoritative and must win over the static guess table."""
    process_data = {
        "solution": [
            {
                "solution_details": {
                    "solute": [
                        {
                            "chemical_2": {"name": "PbI2", "cas_number": "REAL-CAS-FROM-NOMAD"},
                            "concentration_mol": 1.0,
                        }
                    ]
                }
            }
        ]
    }
    rows = extract_material_rows(process_data, "HySprint_SpinCoating", "Batch1", 1, ["S1"])
    assert rows[0].cas_number == "REAL-CAS-FROM-NOMAD"


# ---------------------------------------------------------------------------
# Cost math
# ---------------------------------------------------------------------------


def test_effective_cost_range_falls_back_to_est():
    assert effective_cost_range(None, 5.0, None) == (5.0, 5.0, 5.0)


def test_effective_cost_range_keeps_explicit_bounds():
    assert effective_cost_range(1.0, 5.0, 9.0) == (1.0, 5.0, 9.0)


def test_cost_per_sample_divides_by_samples_covered():
    assert cost_per_sample(16.0, 16) == pytest.approx(1.0)


def test_cost_per_sample_none_when_cost_missing():
    assert cost_per_sample(None, 4) is None


def test_cost_per_sample_none_when_no_samples():
    assert cost_per_sample(10.0, 0) is None


# ---------------------------------------------------------------------------
# NOMAD fetch functions (mocked)
# ---------------------------------------------------------------------------


def test_fetch_samples_per_batch(mocker):
    mock_get_ids = mocker.patch("hysprint_utils.api_calls.get_ids_in_batch")
    mock_get_ids.side_effect = lambda url, token, batch_ids: [
        f"{batch_ids[0]}_S1",
        f"{batch_ids[0]}_S2",
    ]

    result = fetch_samples_per_batch("http://x", "tok", ["Batch1", "Batch2"])

    assert result == {
        "Batch1": ["Batch1_S1", "Batch1_S2"],
        "Batch2": ["Batch2_S1", "Batch2_S2"],
    }
    assert mock_get_ids.call_count == 2


def test_fetch_samples_per_batch_skips_batch_that_raises_assertion_error(mocker):
    """hysprint_utils.api_calls.get_ids_in_batch asserts exactly one batch
    record comes back - confirmed against live data that at least one real
    batch fails this. A single bad batch must not crash the whole scan."""
    mock_get_ids = mocker.patch("hysprint_utils.api_calls.get_ids_in_batch")

    def side_effect(url, token, batch_ids):
        if batch_ids == ["BadBatch"]:
            raise AssertionError
        return [f"{batch_ids[0]}_S1"]

    mock_get_ids.side_effect = side_effect

    result = fetch_samples_per_batch("http://x", "tok", ["GoodBatch", "BadBatch"])

    assert result == {"GoodBatch": ["GoodBatch_S1"]}


def test_fetch_process_entries_keeps_full_samples_list_and_filters_unpositioned(mocker):
    entry_id_response = mocker.Mock()
    entry_id_response.json.return_value = {"data": [{"entry_id": "e1"}]}
    entry_id_response.raise_for_status.return_value = None

    process_response = mocker.Mock()
    process_response.json.return_value = {
        "data": [
            {
                "archive": {
                    "data": {
                        "positon_in_experimental_plan": 2,
                        "samples": [{"lab_id": "S1"}, {"lab_id": "S2"}, {"lab_id": "S3"}],
                    },
                    "metadata": {"entry_type": "HySprint_Evaporation"},
                }
            },
            {
                "archive": {
                    "data": {"positon_in_experimental_plan": 1, "samples": [{"lab_id": "S1"}]},
                    "metadata": {"entry_type": "HySprint_SpinCoating"},
                }
            },
            {
                # Missing positon_in_experimental_plan - not a real processing
                # step, must be filtered out (same rule as get_processing_steps).
                "archive": {"data": {"samples": [{"lab_id": "S1"}]}, "metadata": {}}
            },
        ]
    }
    process_response.raise_for_status.return_value = None

    mock_post = mocker.patch("requests.post", side_effect=[entry_id_response, process_response])

    entries = fetch_process_entries("http://x", "tok", ["S1", "S2", "S3"])

    assert mock_post.call_count == 2
    assert [entry_type for _data, entry_type in entries] == [
        "HySprint_SpinCoating",
        "HySprint_Evaporation",
    ]
    evaporation_data = entries[1][0]
    assert len(evaporation_data["samples"]) == 3


def test_discover_entry_types_excludes_structural_types(mocker):
    entry_id_response = mocker.Mock()
    entry_id_response.json.return_value = {"data": [{"entry_id": "e1"}]}
    entry_id_response.raise_for_status.return_value = None

    aggregation_response = mocker.Mock()
    aggregation_response.json.return_value = {
        "aggregations": {
            "entry_type_agg": {
                "terms": {
                    "data": [
                        {"value": "HySprint_JVmeasurement"},
                        {"value": "HySprint_Evaporation"},
                        {"value": "HySprint_Batch"},
                        {"value": "HySprint_Sample"},
                    ]
                }
            }
        }
    }
    aggregation_response.raise_for_status.return_value = None

    mocker.patch("requests.post", side_effect=[entry_id_response, aggregation_response])

    result = discover_entry_types("http://x", "tok", ["S1"])

    assert result == ["HySprint_Evaporation", "HySprint_JVmeasurement"]


def test_discover_entry_types_no_entries_returns_empty(mocker):
    entry_id_response = mocker.Mock()
    entry_id_response.json.return_value = {"data": []}
    entry_id_response.raise_for_status.return_value = None
    mocker.patch("requests.post", return_value=entry_id_response)

    assert discover_entry_types("http://x", "tok", ["S1"]) == []


# ---------------------------------------------------------------------------
# LCCDataManager.load_batches (integration over the extraction pipeline)
# ---------------------------------------------------------------------------


def test_load_batches_populates_rows_and_batch_sample_counts(mocker):
    # Patched via the already-imported module object, not by string name -
    # "data_manager" is re-registered in sys.modules by every app's own
    # conftest.py under this repo's test-loading convention, so a
    # string-based mocker.patch("data_manager....") can silently resolve to
    # a different app's module when the full multi-app suite runs.
    mocker.patch.object(
        data_manager,
        "fetch_samples_per_batch",
        return_value={"Batch1": ["S1", "S2"]},
    )
    mocker.patch.object(
        data_manager,
        "fetch_process_entries",
        return_value=[
            (
                {
                    "positon_in_experimental_plan": 1,
                    "location": "HyVapBox",
                    "time": 60,
                    "samples": [{"lab_id": "S1"}, {"lab_id": "S2"}],
                    "layer": [{"layer_material_name": "PbI2"}],
                },
                "HySprint_Evaporation",
            )
        ],
    )

    manager = LCCDataManager()
    manager.load_batches("http://x", "tok", ["Batch1"])

    assert manager.batch_sample_counts == {"Batch1": 2}
    assert manager.all_sample_ids == ["S1", "S2"]
    assert len(manager.process_rows) == 1
    assert manager.process_rows[0].num_samples_covered == 2
    assert manager.process_rows[0].location == "HyVapBox"
    assert len(manager.material_rows) == 1
    assert manager.material_rows[0].material_name == "PbI2"
    assert manager.has_data is True


# ---------------------------------------------------------------------------
# excel_export.build_workbook
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_data_manager():
    manager = LCCDataManager()
    manager.batch_sample_counts = {"Batch1": 2}
    manager.all_sample_ids = ["S1", "S2"]
    manager.process_rows = [
        ProcessStepRow(
            batch_id="Batch1",
            process_type="HySprint_Evaporation",
            location="HyVapBox",
            position_in_plan=1,
            step_index=0,
            step_label="HySprint_Evaporation",
            duration_value=60,
            duration_unit="as provided by NOMAD",
            num_samples_covered=2,
            sample_ids=["S1", "S2"],
        )
    ]
    manager.material_rows = [
        MaterialRow(
            batch_id="Batch1",
            process_type="HySprint_Evaporation",
            material_name="PbI2",
            role="layer",
            cas_number="10101-63-0",
            molar_mass_g_per_mol=461.01,
            price_per_gram_est=3.0,
            num_samples_covered=2,
            sample_ids=["S1", "S2"],
        )
    ]
    return manager


def test_build_workbook_sheet_names(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    assert workbook.sheetnames == [
        "Guide",
        "Processes",
        "Materials",
        "Labor",
        "Capital_Overhead_Disposal",
        "Summary",
    ]


def test_build_workbook_headers_match(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    assert [c.value for c in workbook["Processes"][1]] == PROCESSES_HEADERS
    assert [c.value for c in workbook["Materials"][1]] == MATERIALS_HEADERS
    assert [c.value for c in workbook["Labor"][1]] == LABOR_HEADERS
    assert [c.value for c in workbook["Capital_Overhead_Disposal"][1]] == CAPITAL_HEADERS


def test_build_workbook_processes_sheet_has_no_cost_columns(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    headers = [c.value for c in workbook["Processes"][1]]
    assert "Cost_Est" not in headers
    assert "Verified" not in headers
    assert "Location" in headers


def test_build_workbook_processes_row_has_location(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    ws = workbook["Processes"]
    location_col = PROCESSES_HEADERS.index("Location") + 1
    assert ws.cell(row=2, column=location_col).value == "HyVapBox"


def test_build_workbook_labor_sheet_has_four_role_rows_per_batch(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    ws = workbook["Labor"]
    role_col = LABOR_HEADERS.index("Role") + 1
    roles = [ws.cell(row=r, column=role_col).value for r in range(2, ws.max_row + 1)]
    assert roles == LABOR_ROLES


def test_build_workbook_materials_verified_column_defaults_to_boolean_false(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    verified_col = MATERIALS_HEADERS.index("Verified") + 1
    assert workbook["Materials"].cell(row=2, column=verified_col).value is False


def test_build_workbook_has_verified_dropdown_validation(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    validations = workbook["Materials"].data_validations.dataValidation
    assert any(dv.formula1 == '"TRUE,FALSE"' for dv in validations)


def test_build_workbook_capital_overhead_disposal_location_dropdown(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    validations = workbook["Capital_Overhead_Disposal"].data_validations.dataValidation
    assert any("HyVapBox" in (dv.formula1 or "") for dv in validations)


def test_build_workbook_effective_cost_formula_present(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    col = MATERIALS_HEADERS.index("Effective_Cost_Low") + 1
    cell = workbook["Materials"].cell(row=2, column=col)
    assert isinstance(cell.value, str)
    assert cell.value.startswith("=")


def test_build_workbook_round_trips_through_bytes(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    reloaded = openpyxl.load_workbook(buffer)
    assert reloaded.sheetnames == workbook.sheetnames
    assert reloaded["Summary"].cell(row=2, column=1).value == "Batch1"


def test_capital_overhead_disposal_seeds_from_real_location_and_materials(sample_data_manager):
    workbook = build_workbook(sample_data_manager)
    ws = workbook["Capital_Overhead_Disposal"]
    item_col = CAPITAL_HEADERS.index("Item") + 1
    items = [ws.cell(row=r, column=item_col).value for r in range(2, ws.max_row + 1)]
    assert "Cleanroom / lab rent" in items
    assert "Equipment depreciation - HyVapBox" in items
    assert "Disposal - PbI2" in items


# ---------------------------------------------------------------------------
# Cost reference carry-forward (per-batch export)
# ---------------------------------------------------------------------------


def test_build_workbook_carries_forward_material_price(sample_data_manager):
    reference = CostReference(
        material_prices={
            "PbI2": {
                "cas_number": "10101-63-0",
                "price_per_gram_est": 7.25,
                "verified": True,
                "notes": "confirmed",
            }
        }
    )
    workbook = build_workbook(sample_data_manager, cost_reference=reference)
    ws = workbook["Materials"]

    price_col = MATERIALS_HEADERS.index("Price_per_Gram_Est") + 1
    verified_col = MATERIALS_HEADERS.index("Verified") + 1
    notes_col = MATERIALS_HEADERS.index("Notes") + 1
    assert ws.cell(row=2, column=price_col).value == 7.25
    assert ws.cell(row=2, column=verified_col).value is True
    assert ws.cell(row=2, column=notes_col).value == "confirmed"


def test_build_workbook_carries_forward_labor_rate(sample_data_manager):
    reference = CostReference(
        labor_rates={"PhD Researcher": {"hourly_rate_est": 45.0, "verified": True}}
    )
    workbook = build_workbook(sample_data_manager, cost_reference=reference)
    ws = workbook["Labor"]

    rate_col = LABOR_HEADERS.index("Hourly_Rate_Est") + 1
    verified_col = LABOR_HEADERS.index("Verified") + 1
    assert ws.cell(row=2, column=rate_col).value == 45.0  # first role row = PhD Researcher
    assert ws.cell(row=2, column=verified_col).value is True


def test_build_workbook_carries_forward_overhead_cost(sample_data_manager):
    reference = CostReference(
        overhead_costs={
            "Cleanroom / lab rent": {
                "cost_low": None,
                "cost_est": 15.0,
                "cost_high": None,
                "verified": True,
                "notes": "",
            }
        }
    )
    workbook = build_workbook(sample_data_manager, cost_reference=reference)
    ws = workbook["Capital_Overhead_Disposal"]

    item_col = CAPITAL_HEADERS.index("Item") + 1
    cost_est_col = CAPITAL_HEADERS.index("Cost_Est") + 1
    verified_col = CAPITAL_HEADERS.index("Verified") + 1
    row_values = {ws.cell(row=r, column=item_col).value: r for r in range(2, ws.max_row + 1)}
    rent_row = row_values["Cleanroom / lab rent"]
    assert ws.cell(row=rent_row, column=cost_est_col).value == 15.0
    assert ws.cell(row=rent_row, column=verified_col).value is True


def test_build_workbook_unknown_material_not_carried_forward(sample_data_manager):
    reference = CostReference(material_prices={"SomethingElse": {"price_per_gram_est": 9.0}})
    workbook = build_workbook(sample_data_manager, cost_reference=reference)
    ws = workbook["Materials"]

    price_col = MATERIALS_HEADERS.index("Price_per_Gram_Est") + 1
    verified_col = MATERIALS_HEADERS.index("Verified") + 1
    # Falls back to the static CHEMICAL_REFERENCE default for PbI2, not the
    # unrelated reference entry, and stays unverified.
    assert ws.cell(row=2, column=price_col).value == pytest.approx(3.0)
    assert ws.cell(row=2, column=verified_col).value is False


# ---------------------------------------------------------------------------
# Cost reference template builders (admin single source of truth)
# ---------------------------------------------------------------------------


def test_build_cost_reference_template_sheet_names():
    workbook = build_cost_reference_template()
    assert workbook.sheetnames == [
        "Guide",
        "Materials",
        "Processes",
        "Labor",
        "Capital_Overhead_Disposal",
    ]


def test_build_cost_reference_template_materials_seeded_with_cas_and_price():
    workbook = build_cost_reference_template()
    ws = workbook["Materials"]
    names = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert "PbI2" in names
    pbi2_row = next(r for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=1).value == "PbI2")
    assert ws.cell(row=pbi2_row, column=2).value == "10101-63-0"  # CAS_Number
    assert ws.cell(row=pbi2_row, column=3).value == pytest.approx(3.0)  # Price
    assert ws.cell(row=pbi2_row, column=4).value == 1  # Grams_on_Bottle


def test_build_cost_reference_template_labor_has_four_fixed_roles():
    workbook = build_cost_reference_template()
    ws = workbook["Labor"]
    roles = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert roles == LABOR_ROLES


def test_build_cost_reference_template_capital_seeded_with_all_known_locations():
    workbook = build_cost_reference_template()
    ws = workbook["Capital_Overhead_Disposal"]
    items = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert "Cleanroom / lab rent" in items
    assert "Equipment depreciation - HyVapBox" in items
    assert "Equipment depreciation - HyWeighBox" in items


def test_build_cost_reference_template_from_data_uses_real_names(sample_data_manager):
    workbook = build_cost_reference_template_from_data(sample_data_manager)

    materials_ws = workbook["Materials"]
    names = {materials_ws.cell(row=r, column=1).value for r in range(2, materials_ws.max_row + 1)}
    assert "PbI2" in names  # real, from the loaded batch
    assert "MAI" in names  # static-only fallback, not seen in data but still offered

    processes_ws = workbook["Processes"]
    process_rows = {
        (processes_ws.cell(row=r, column=1).value, processes_ws.cell(row=r, column=2).value)
        for r in range(2, processes_ws.max_row + 1)
    }
    assert ("HySprint_Evaporation", "HySprint_Evaporation") in process_rows

    capital_ws = workbook["Capital_Overhead_Disposal"]
    items = {capital_ws.cell(row=r, column=1).value for r in range(2, capital_ws.max_row + 1)}
    assert "Equipment depreciation - HyVapBox" in items  # from KNOWN_LOCATIONS, not batch data


def test_build_cost_reference_template_from_data_includes_extra_schema_types(sample_data_manager):
    workbook = build_cost_reference_template_from_data(
        sample_data_manager, extra_schema_types=["HySprint_JVmeasurement"]
    )
    processes_ws = workbook["Processes"]
    process_types = {
        processes_ws.cell(row=r, column=1).value for r in range(2, processes_ws.max_row + 1)
    }
    assert "HySprint_JVmeasurement" in process_types


def test_reference_template_round_trips_through_parser(sample_data_manager):
    """The lean admin template must be readable by the same parser used for
    full per-batch exports - both share header names, not fixed positions."""
    workbook = build_cost_reference_template_from_data(sample_data_manager)
    buffer = io.BytesIO()
    workbook.save(buffer)

    reference = parse_cost_reference_workbook(buffer.getvalue())

    assert "PbI2" in reference.material_prices
    assert reference.material_prices["PbI2"]["cas_number"] == "10101-63-0"
    assert set(reference.labor_rates) == set(LABOR_ROLES)
    assert "Cleanroom / lab rent" in reference.overhead_costs


# ---------------------------------------------------------------------------
# Automatic single-source-of-truth cost reference file
# ---------------------------------------------------------------------------


def test_load_default_cost_reference_missing_file_returns_none(tmp_path):
    missing_path = tmp_path / "does_not_exist.xlsx"
    assert load_default_cost_reference(path=missing_path) is None


def test_load_default_cost_reference_reads_existing_file(tmp_path):
    workbook = build_cost_reference_template()
    file_path = tmp_path / "cost_reference.xlsx"
    workbook.save(file_path)

    reference = load_default_cost_reference(path=file_path)

    assert reference is not None
    assert "PbI2" in reference.material_prices
    assert reference.material_prices["PbI2"]["price_per_gram_est"] == pytest.approx(3.0)


def test_load_default_cost_reference_corrupt_file_returns_none(tmp_path):
    file_path = tmp_path / "cost_reference.xlsx"
    file_path.write_bytes(b"not a real xlsx file")

    assert load_default_cost_reference(path=file_path) is None


def test_parse_cost_reference_workbook_computes_price_per_gram_from_bottle(sample_data_manager):
    workbook = build_cost_reference_template()
    materials_ws = workbook["Materials"]
    # Simulate an admin who bought a 250g bottle for 500.
    row = next(
        r
        for r in range(2, materials_ws.max_row + 1)
        if materials_ws.cell(row=r, column=1).value == "PbI2"
    )
    materials_ws.cell(row=row, column=3, value=500.0)  # Price
    materials_ws.cell(row=row, column=4, value=250.0)  # Grams_on_Bottle

    buffer = io.BytesIO()
    workbook.save(buffer)
    reference = parse_cost_reference_workbook(buffer.getvalue())

    assert reference.material_prices["PbI2"]["price_per_gram_est"] == pytest.approx(2.0)
