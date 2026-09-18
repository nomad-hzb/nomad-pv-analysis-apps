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
                    "vacuumquenching": True,
                },
            },
        ],
        is_testing=True,
    )
    builder.build_excel()

    ws = builder.workbook["Experiment Data"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row if cell.value is not None]

    assert any("Gas quenching duration [s]" in str(v) for v in all_values)
    assert any("Vacuum quenching pressure [bar]" in str(v) for v in all_values)
