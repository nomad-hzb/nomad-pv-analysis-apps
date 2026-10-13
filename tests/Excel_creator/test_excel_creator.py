import pytest
from experiment_excel_builder import ExperimentExcelBuilder

PROCESS_SEQUENCE = [
    {"process": "Experiment Info", "config": {}},
    {"process": "Cleaning O2-Plasma", "config": {}},
]


def test_build_excel_creates_expected_sheets():
    builder = ExperimentExcelBuilder(PROCESS_SEQUENCE, is_testing=True)
    builder.build_excel()

    assert builder.workbook.sheetnames == [
        "Experiment Data",
        "Data Entry Guide",
        "How to Cite",
    ]


def test_build_excel_writes_process_steps_to_experiment_sheet():
    builder = ExperimentExcelBuilder(PROCESS_SEQUENCE, is_testing=True)
    builder.build_excel()

    ws = builder.workbook["Experiment Data"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row if cell.value is not None]

    assert any("Experiment Info" in str(v) for v in all_values)
    assert any("Cleaning O2-Plasma" in str(v) for v in all_values)


def test_build_excel_empty_process_sequence_still_creates_sheets():
    builder = ExperimentExcelBuilder([], is_testing=True)
    builder.build_excel()

    assert builder.workbook.sheetnames == [
        "Experiment Data",
        "Data Entry Guide",
        "How to Cite",
    ]


def test_build_excel_unknown_process_falls_back_to_default_steps():
    builder = ExperimentExcelBuilder(
        [{"process": "Not A Real Process", "config": {}}], is_testing=True
    )
    builder.build_excel()

    ws = builder.workbook["Experiment Data"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row if cell.value is not None]

    assert any("Undefined Process" in str(v) for v in all_values)


def test_save_writes_workbook_to_disk(tmp_path):
    builder = ExperimentExcelBuilder(PROCESS_SEQUENCE, is_testing=True)
    builder.build_excel()

    out_file = tmp_path / "test_experiment.xlsx"
    builder.save(str(out_file))

    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_build_excel_screen_printing_writes_expected_columns():
    builder = ExperimentExcelBuilder(
        [
            {"process": "Experiment Info", "config": {}},
            {"process": "Screen Printing", "config": {"solvents": 1, "solutes": 1}},
        ],
        is_testing=True,
    )
    builder.build_excel()

    ws = builder.workbook["Experiment Data"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row if cell.value is not None]

    for expected in [
        "Layer type",
        "Solvent 1 name",
        "Solute 1 name",
        "Annealing temperature [°C]",
        "Mesh material",
        "Mesh count [meshes/cm]",
        "Emulsion material",
        "Squeegee shape",
        "Printing speed [mm/s]",
        "Printing method",
        "Snap-off distance [mm]",
    ]:
        assert any(expected in str(v) for v in all_values), expected


def test_build_excel_screen_printing_quenching_toggle():
    builder = ExperimentExcelBuilder(
        [
            {
                "process": "Screen Printing",
                "config": {
                    "solvents": 0,
                    "solutes": 0,
                    "gasquenching": True,
                    "airknifequenching": True,
                },
            },
        ],
        is_testing=True,
    )
    builder.build_excel()

    ws = builder.workbook["Experiment Data"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row if cell.value is not None]

    assert any("Gas quenching duration [s]" in str(v) for v in all_values)
    assert any("Air knife angle [°]" in str(v) for v in all_values)
    assert any("Bead volume [mm/s]" in str(v) for v in all_values)
    assert any("Drying speed [cm/min]" in str(v) for v in all_values)
    # Vacuum Quenching is not a Screen Printing option (removed per explicit decision -
    # not needed for this process, unlike Spin Coating/Blade Coating).
    assert not any("Vacuum quenching pressure [bar]" in str(v) for v in all_values)


def test_build_excel_screen_printing_air_knife_quenching_off_by_default():
    builder = ExperimentExcelBuilder(
        [{"process": "Screen Printing", "config": {"solvents": 0, "solutes": 0}}],
        is_testing=True,
    )
    builder.build_excel()

    ws = builder.workbook["Experiment Data"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row if cell.value is not None]

    assert not any("Air knife angle [°]" in str(v) for v in all_values)


# --- guide sheet generated from process_specs, family lists, config reset (S9) ------------


def _guide_values():
    builder = ExperimentExcelBuilder(
        [{"process": "Experiment Info", "config": {}}], is_testing=True
    )
    builder.build_excel()
    ws = builder.workbook["Data Entry Guide"]
    return [[c.value for c in row] for row in ws.iter_rows()]


def test_guide_lists_every_catalogue_column_of_the_processes_it_documents():
    from hysprint_utils.process_specs import PROCESSES

    first_column = {row[0] for row in _guide_values() if row and row[0]}
    for process_name in ("Experiment Info", "Spin Coating", "Evaporation", "ALD", "Sputtering"):
        for label in PROCESSES[process_name]["fields"]:
            assert label in first_column, f"{process_name}: {label}"


def test_guide_units_follow_the_real_columns():
    """The hand-kept guide said the sample holder width is in cm; the column is [mm]."""
    rows = {row[0]: row for row in _guide_values() if row and row[0]}
    assert rows["Sample holder width [mm]"][3] == "mm"
    assert "Sample Holder width" not in rows
    assert "Room relative humidity" not in rows  # a label the sheet never had


def test_process_family_lists_come_from_the_catalogue():
    from hysprint_utils.process_specs import process_family

    assert {
        p
        for p in (
            "Spin Coating",
            "Dip Coating",
            "Slot Die Coating",
            "Inkjet Printing",
            "Blade Coating",
            "Screen Printing",
        )
        if process_family(p) == "coating"
    } == {
        "Spin Coating",
        "Dip Coating",
        "Slot Die Coating",
        "Inkjet Printing",
        "Blade Coating",
        "Screen Printing",
    }
    assert process_family("Cleaning O2-Plasma") == process_family("Cleaning UV-Ozone") == "cleaning"
    assert process_family("Evaporation") is None


def _app_without_widgets():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[2] / "apps" / "Excel_creator" / "voila_experiment_app.py"
    spec = importlib.util.spec_from_file_location("voila_experiment_app_ec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = object.__new__(module.MinimalistExperimentBuilder)
    app._update_process_display = lambda: None
    return app


def test_changing_to_co_evaporation_gets_its_default_config():
    """The hand-kept reset list left Co-Evaporation without config, so the sheet had no
    "Material name n" columns although the control showed 'Materials: 1'."""
    app = _app_without_widgets()
    app.current_sequence = [{"process": "Spin Coating", "config": {"solvents": 1}}]
    app._update_process_type(0, "Co-Evaporation")
    assert app.current_sequence[0]["config"] == {"materials": 2}

    builder = ExperimentExcelBuilder(
        [{"process": "Experiment Info", "config": {}}, app.current_sequence[0]], is_testing=True
    )
    builder.build_excel()
    ws = builder.workbook["Experiment Data"]
    values = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert any("Material name 2" in v for v in values)


def test_changing_to_a_process_without_config_drops_it():
    app = _app_without_widgets()
    app.current_sequence = [{"process": "Spin Coating", "config": {"solvents": 1}}]
    app._update_process_type(0, "Evaporation")
    assert "config" not in app.current_sequence[0]


def test_shipped_templates_only_use_config_keys_the_catalogue_knows():
    """Inert keys (vacuumquenching on Blade, annealing on Inkjet, ...) were silently ignored,
    so a template did not produce what its config claimed."""
    import json
    from pathlib import Path

    from hysprint_utils.process_specs import ATMOSPHERIC_CONFIG_KEY, PROCESSES

    path = (
        Path(__file__).parents[2]
        / "apps"
        / "Excel_creator"
        / "templates"
        / "process_templates.json"
    )
    templates = json.loads(path.read_text(encoding="utf-8"))["templates"]
    unknown = []
    for name, template in templates.items():
        for step in template["process_sequence"]:
            meta = PROCESSES.get(step["process"], {}).get("meta")
            if meta is None:
                continue  # a process name the catalogue does not have is a separate defect (6.3)
            known = {k for k, *_ in meta.get("numeric_config", [])}
            known |= {k for k, *_ in meta.get("boolean_config", [])} | {ATMOSPHERIC_CONFIG_KEY}
            unknown += [
                (name, step["process"], k) for k in step.get("config", {}) if k not in known
            ]
    assert unknown == []


# ---------------------------------------------------------------------------
# 6.3: shown config == generated config, template validation, no destructive fallback,
# visible errors, Ink Recycling headers, Nomad ID formula
# ---------------------------------------------------------------------------


def _app_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[2] / "apps" / "Excel_creator" / "voila_experiment_app.py"
    spec = importlib.util.spec_from_file_location("voila_experiment_app_ec2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sheet_values(sequence, is_testing=True):
    builder = ExperimentExcelBuilder(sequence, is_testing=is_testing)
    builder.build_excel()
    ws = builder.workbook["Experiment Data"]
    return ws, [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]


def test_a_template_step_without_spinsteps_shows_and_generates_one_step():
    """The control showed "Steps: 1" (its minimum) but the sheet had no rotation columns."""
    module = _app_module()
    app = module.MinimalistExperimentBuilder()
    step = {"process": "Spin Coating", "config": {"solvents": 1, "solutes": 1}}
    app._create_process_row(1, step)
    assert step["config"]["spinsteps"] == 1
    _ws, values = _sheet_values([{"process": "Experiment Info", "config": {}}, step])
    assert any("Rotation speed" in v for v in values)


def test_every_shipped_template_is_valid_and_renders_its_rows():
    module = _app_module()
    app = module.MinimalistExperimentBuilder()
    assert len(app.templates) >= 8  # none of the shipped templates was skipped
    for key, template in app.templates.items():
        assert module.validate_template(template) == [], key
        app.current_sequence = [dict(step) for step in template["process_sequence"]]
        app._update_process_display()  # raised a TraitError for the unknown "Seq-Evaporation"


def test_validate_template_names_the_problem():
    module = _app_module()
    bad = {"name": "x", "process_sequence": [{"process": "Seq-Evaporation"}]}
    assert "Seq-Evaporation" in module.validate_template(bad)[0]
    assert module.validate_template({"process_sequence": [{"process": "Spin Coating"}]}) == [
        "it has no name"
    ]


def test_an_unreadable_templates_file_is_not_overwritten(tmp_path):
    module = _app_module()
    path = tmp_path / "process_templates.json"
    path.write_text("{ this is not json", encoding="utf-8")
    app = module.MinimalistExperimentBuilder(templates_file=path)
    assert path.read_text(encoding="utf-8") == "{ this is not json"
    assert app.templates  # the built-in templates are used in memory
    assert "Empty Template" in app.template_dropdown.options


def test_an_invalid_template_is_left_out_and_the_others_survive(tmp_path):
    import json

    module = _app_module()
    path = tmp_path / "process_templates.json"
    templates = {
        "good": {"name": "Good", "process_sequence": [{"process": "Experiment Info"}]},
        "broken": {"process_sequence": [{"process": "Experiment Info"}]},
    }
    path.write_text(json.dumps({"templates": templates}), encoding="utf-8")
    app = module.MinimalistExperimentBuilder(templates_file=path)
    assert list(app.templates) == ["good"]
    assert json.loads(path.read_text(encoding="utf-8"))["templates"] == templates


def test_a_failed_generation_shows_the_error_and_offers_no_download(monkeypatch, capsys):
    module = _app_module()
    app = module.MinimalistExperimentBuilder()

    class Broken:
        def __init__(self, *args, **kwargs):
            raise ValueError("no columns")

    monkeypatch.setattr(module, "ExperimentExcelBuilder", Broken)
    app._on_generate_excel(None)
    assert app.download_area.value == ""
    assert "no columns" in capsys.readouterr().out


@pytest.mark.parametrize("solvents", [0, 1, 3])
def test_ink_recycling_has_one_datetime_and_operator_column(solvents):
    sequence = [
        {"process": "Experiment Info", "config": {}},
        {
            "process": "Ink Recycling",
            "config": {"solvents": solvents, "solutes": 1, "precursors": 1},
        },
    ]
    ws, _values = _sheet_values(sequence)
    headers = [c.value for c in ws[2] if c.value]
    assert headers.count("Datetime") == 1  # one per process, not one per solvent
    assert headers.count("Operator") == 1


def test_the_nomad_id_formula_is_written_to_every_data_row():
    ws, _ = _sheet_values(PROCESS_SEQUENCE, is_testing=False)
    for row in (3, 4, 50):
        assert str(ws[f"F{row}"].value).startswith(f'=IF(B{row}="","",CONCATENATE("HZB_"')
