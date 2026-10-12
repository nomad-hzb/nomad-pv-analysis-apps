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
