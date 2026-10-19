"""Prefill from NOMAD (issue #31): one row per sample of an upload, with its Nomad ID and every
Experiment Info column process_specs maps to the sample or its substrate. No network: the
NOMAD calls are replaced by fixtures."""

import importlib.util
from pathlib import Path

import nomad_prefill
import pytest
from experiment_excel_builder import ExperimentExcelBuilder
from nomad_prefill import PrefillSample

INFO_ONLY = [{"process": "Experiment Info", "config": {}}]
WITH_CLEANING = [*INFO_ONLY, {"process": "Cleaning O2-Plasma", "config": {"solvents": 1}}]
INK_RECYCLING = [
    *INFO_ONLY,
    {"process": "Ink Recycling", "config": {"solvents": 1, "solutes": 1, "precursors": 1}},
]

# What NOMAD holds for a fully described sample (the field names of HySprint_Sample and
# HySprint_Substrate that process_specs' Experiment Info paths read).
FULL_SUBSTRATE = {
    "substrate": "Soda Lime Glass",
    "substrate_dimension": "2.5 cm x 2.5 cm",
    "solar_cell_area": 0.5,
    "number_of_pixels": 6,
    "pixel_area": 0.16,
    "conducting_material": ["ITO", "Ag"],
    "substrate_properties": [{"layer_sheet_resistance": 15, "layer_transmission": 90}],
}
FULL_EXPECTED = {
    "Sample dimension": "2.5 cm x 2.5 cm",
    "Sample area [cm^2]": 0.5,
    "Number of pixels": 6,
    "Pixel area [cm^2]": 0.16,
    "Substrate material": "Soda Lime Glass",
    "Substrate conductive layer": "ITO",
    "Sheet Resistance [Ohms/square]": 15,
    "Transmission [%]": 90,
    "Number of junctions": 2,
}
SAMPLES = [
    PrefillSample("HZB_A_1_1_C-1", dict(FULL_EXPECTED)),
    PrefillSample("HZB_A_1_1_C-2"),
]


def _source(lab_id="HZB_A_1", sample=None, substrate=None):
    return {"sample": {"lab_id": lab_id, **(sample or {})}, "substrate": substrate or {}}


def _sheet(sequence, is_testing, samples):
    rows = None if samples is None else [s.as_row() for s in samples]
    builder = ExperimentExcelBuilder(sequence, is_testing=is_testing, samples=rows)
    builder.build_excel()
    return builder.workbook["Experiment Data"]


def _column(ws, header):
    return next(c.column for c in ws[2] if c.value == header)


# =============================================================================
# nomad_prefill: what is taken from NOMAD
# =============================================================================


def test_every_mapped_experiment_info_column_is_taken():
    source = _source(sample={"number_of_junctions": 2}, substrate=FULL_SUBSTRATE)
    assert nomad_prefill.info_fields(source) == FULL_EXPECTED


def test_the_field_list_comes_from_process_specs():
    """Columns without an archive path are never filled from NOMAD."""
    assert set(FULL_EXPECTED) == set(nomad_prefill.INFO_FIELD_PATHS)
    for key in ("Date", "Project_Name", "Batch", "Subbatch", "Sample", "Variation", "Notes"):
        assert key not in nomad_prefill.INFO_FIELD_PATHS


def test_the_first_path_with_a_value_wins():
    substrate = {
        "layer_sheet_resistance": 12,
        "substrate_properties": [{"layer_sheet_resistance": 99}],
    }
    fields = nomad_prefill.info_fields(_source(substrate=substrate))
    assert fields["Sheet Resistance [Ohms/square]"] == 12


@pytest.mark.parametrize(
    "substrate",
    [
        {"conducting_material": []},
        {"conducting_material": "ITO"},  # not a list: index 0 is not taken from a string
        {"substrate": ""},
        {"substrate": "   "},
        {"number_of_pixels": True},
        {"substrate_dimension": {"value": 1}},
        {"substrate_properties": []},
    ],
)
def test_missing_empty_or_odd_values_are_left_out(substrate):
    assert nomad_prefill.info_fields(_source(substrate=substrate)) == {}


def test_zero_is_a_value():
    fields = nomad_prefill.info_fields(_source(sample={"number_of_junctions": 0}))
    assert fields == {"Number of junctions": 0}


def test_a_confirmed_unit_factor_is_applied(monkeypatch):
    monkeypatch.setattr(nomad_prefill, "INFO_MULTIPLIERS", {"Sample area [cm^2]": 100})
    fields = nomad_prefill.info_fields(_source(substrate={"solar_cell_area": 0.5}))
    assert fields["Sample area [cm^2]"] == 50


def test_samples_are_sorted_and_sources_without_lab_id_skipped():
    sources = [
        _source("HZB_B_1", substrate={"substrate": "FTO glass"}),
        {"sample": {}, "substrate": {"substrate": "ignored"}},
        {"sample": None, "substrate": {}},
        _source("HZB_A_1"),
    ]
    assert nomad_prefill.samples_from_sources(sources) == [
        PrefillSample("HZB_A_1"),
        PrefillSample("HZB_B_1", {"Substrate material": "FTO glass"}),
    ]


@pytest.mark.parametrize(
    "lab_id, parts",
    [
        ("HZB_FiNa_1_1_C-1", ("FiNa", "1", "1", "1")),
        ("HZB_Green Ink_6_2_C-14", ("Green Ink", "6", "2", "14")),
        ("HZB_IJP_Green_Ink_6_A_C-3", ("IJP_Green_Ink", "6", "A", "3")),  # project with "_"
        ("HZB_P_B-2_S-1_C-x7", ("P", "B-2", "S-1", "x7")),
    ],
)
def test_a_formula_lab_id_is_read_back_into_its_columns(lab_id, parts):
    parsed = nomad_prefill.parse_lab_id(lab_id)
    assert tuple(parsed[key] for key in nomad_prefill.LAB_ID_COLUMNS) == parts
    # the parts rebuild exactly the same ID, as the sheet's Nomad ID formula would
    project, batch, subbatch, sample = parts
    assert f"HZB_{project}_{batch}_{subbatch}_C-{sample}" == lab_id


@pytest.mark.parametrize(
    "lab_id",
    [
        "HZB_A_1",  # no _C- part
        "KIT_FiNa_1_1_C-1",  # another prefix
        "HZB_FiNa_1_C-1",  # no subbatch
        "HZB__1_1_C-1",  # empty project
        "HZB_FiNa_1_1_C-",  # empty sample
        "HZB_FiNa_1_1_C-1_extra",
        "sample 12",
    ],
)
def test_a_lab_id_not_made_by_the_formula_fills_no_columns(lab_id):
    assert nomad_prefill.parse_lab_id(lab_id) == {}


def test_samples_get_the_columns_of_their_lab_id():
    [sample] = nomad_prefill.samples_from_sources(
        [_source("HZB_FiNa_3_2_C-7", substrate={"substrate": "Glass"})]
    )
    assert sample.fields == {
        "Project_Name": "FiNa",
        "Batch": "3",
        "Subbatch": "2",
        "Sample": "7",
        "Substrate material": "Glass",
    }
    assert nomad_prefill.filled_columns([sample]) == [
        "Project_Name",
        "Batch",
        "Subbatch",
        "Sample",
        "Nomad ID",
        "Substrate material",
    ]


def test_parsed_lab_id_columns_land_in_the_sheet():
    [sample] = nomad_prefill.samples_from_sources([_source("HZB_FiNa_3_2_C-7")])
    ws = _sheet(INFO_ONLY, False, [sample])
    row = {header: ws.cell(3, _column(ws, header)).value for header in nomad_prefill.LAB_ID_COLUMNS}
    assert row == {"Project_Name": "FiNa", "Batch": "3", "Subbatch": "2", "Sample": "7"}
    assert ws.cell(3, _column(ws, "Nomad ID")).value == "HZB_FiNa_3_2_C-7"


def test_ink_recycling_variant_gets_the_lab_id_columns_too():
    [sample] = nomad_prefill.samples_from_sources([_source("HZB_FiNa_3_2_C-7")])
    ws = _sheet(INK_RECYCLING, False, [sample])
    assert ws.cell(3, _column(ws, "Batch")).value == "3"


def test_a_row_starts_with_the_nomad_id():
    sample = PrefillSample("HZB_A_1", {"Substrate material": "Glass"})
    assert sample.as_row() == {"Nomad ID": "HZB_A_1", "Substrate material": "Glass"}


def test_filled_columns_lists_what_any_sample_has_in_sheet_order():
    samples = [
        PrefillSample("a", {"Number of junctions": 1}),
        PrefillSample("b", {"Substrate material": "Glass"}),
    ]
    assert nomad_prefill.filled_columns(samples) == [
        "Nomad ID",
        "Substrate material",
        "Number of junctions",
    ]


def test_upload_choices_tell_duplicate_names_apart_and_fall_back_to_the_id():
    uploads = [
        {"upload_id": "id1", "upload_name": "Batch 7"},
        {"upload_id": "id2", "upload_name": "Batch 7"},
        {"upload_id": "id3"},
        {"upload_id": "id4", "upload_name": "Other"},
    ]
    assert nomad_prefill.upload_choices(uploads) == [
        ("Batch 7 (id1)", "id1"),
        ("Batch 7 (id2)", "id2"),
        ("id3", "id3"),
        ("Other", "id4"),
    ]


def test_fetch_samples_uses_the_shared_query(monkeypatch):
    calls = []

    def fake(url, token, upload_id):
        calls.append((url, token, upload_id))
        return [_source("HZB_A_1", substrate={"substrate": "ITO glass"})]

    monkeypatch.setattr(nomad_prefill, "get_samples_with_substrates", fake)
    samples = nomad_prefill.fetch_samples_in_upload("https://oasis/api", "tok", "up1")
    assert calls == [("https://oasis/api", "tok", "up1")]
    assert samples == [PrefillSample("HZB_A_1", {"Substrate material": "ITO glass"})]


def test_connect_uses_the_container_token(monkeypatch):
    monkeypatch.setenv("NOMAD_CLIENT_ACCESS_TOKEN", "abc")
    url, token = nomad_prefill.connect()
    assert token == "abc"
    assert url == nomad_prefill.URL_BASE + nomad_prefill.API_ENDPOINT


def test_connect_without_a_token_raises(monkeypatch):
    monkeypatch.delenv("NOMAD_CLIENT_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError, match="NOMAD_CLIENT_ACCESS_TOKEN"):
        nomad_prefill.connect()


# =============================================================================
# The sheet
# =============================================================================


@pytest.mark.parametrize("is_testing, first_row", [(False, 3), (True, 4)])
def test_samples_fill_their_columns_below_the_example_row(is_testing, first_row):
    ws = _sheet(WITH_CLEANING, is_testing, SAMPLES)
    nomad_col = _column(ws, "Nomad ID")
    assert ws.cell(first_row, nomad_col).value == "HZB_A_1_1_C-1"
    for header, value in FULL_EXPECTED.items():
        assert ws.cell(first_row, _column(ws, header)).value == value, header
    assert ws.cell(first_row + 1, nomad_col).value == "HZB_A_1_1_C-2"
    # a sample NOMAD knows nothing more about leaves the other columns empty
    assert ws.cell(first_row + 1, _column(ws, "Substrate material")).value is None
    # the row after the samples keeps its formula
    assert str(ws.cell(first_row + 2, nomad_col).value).startswith("=IF(")


def test_columns_nomad_has_no_value_for_stay_empty():
    ws = _sheet(INFO_ONLY, False, SAMPLES)
    for header in ("Date", "Project_Name", "Batch", "Subbatch", "Sample", "Variation", "Notes"):
        assert ws.cell(3, _column(ws, header)).value is None, header


def test_the_example_row_stays_a_complete_example():
    ws = _sheet(WITH_CLEANING, True, SAMPLES)
    assert ws.cell(3, _column(ws, "Substrate material")).value == "Soda Lime Glass"
    assert ws.cell(3, _column(ws, "Sample dimension")).value == "1 cm x 1 cm"
    assert str(ws.cell(3, _column(ws, "Nomad ID")).value).startswith("=IF(")
    assert ws.cell(3, _column(ws, "Project_Name")).value == "FiNa"


def test_ink_recycling_variant_writes_nothing_into_another_process():
    """That variant of Experiment Info has only seven columns. A fixed column letter (L for
    the substrate, as in the CE-AME copy) would land inside the Ink Recycling columns."""
    ws = _sheet(INK_RECYCLING, False, SAMPLES)
    assert ws.cell(3, _column(ws, "Nomad ID")).value == "HZB_A_1_1_C-1"
    written = {c.value for row in ws.iter_rows(min_row=3) for c in row if c.value is not None}
    assert not written & {v for v in FULL_EXPECTED.values() if isinstance(v, str)}


def test_samples_are_written_beyond_the_formula_rows():
    many = [PrefillSample(f"S{i:04d}") for i in range(600)]
    ws = _sheet(INFO_ONLY, False, many)
    assert ws.cell(602, _column(ws, "Nomad ID")).value == "S0599"


def test_an_unknown_header_in_a_row_is_ignored():
    builder = ExperimentExcelBuilder(
        INFO_ONLY, is_testing=False, samples=[{"Nomad ID": "X", "Not a column": "?"}]
    )
    builder.build_excel()
    ws = builder.workbook["Experiment Data"]
    assert ws.cell(3, _column(ws, "Nomad ID")).value == "X"
    assert "?" not in [c.value for row in ws.iter_rows() for c in row]


@pytest.mark.parametrize("samples", [None, []])
def test_without_samples_the_sheet_is_unchanged(samples):
    plain = ExperimentExcelBuilder(WITH_CLEANING, is_testing=True)
    plain.build_excel()
    ws = _sheet(WITH_CLEANING, True, samples)
    expected = plain.workbook["Experiment Data"]
    assert [[c.value for c in row] for row in ws.iter_rows()] == [
        [c.value for c in row] for row in expected.iter_rows()
    ]


def test_samples_without_an_experiment_info_step_raise():
    with pytest.raises(ValueError, match="Nomad ID"):
        _sheet([{"process": "Annealing", "config": {}}], False, SAMPLES)


# =============================================================================
# The app: hidden panel, loading, generating
# =============================================================================


def _app_module():
    path = Path(__file__).parents[2] / "apps" / "Excel_creator" / "voila_experiment_app.py"
    spec = importlib.util.spec_from_file_location("voila_experiment_app_ec_prefill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPLOADS = [{"upload_id": "up1", "upload_name": "Batch 7"}, {"upload_id": "up2"}]


@pytest.fixture
def fake_nomad(monkeypatch):
    """Replaces every NOMAD call of nomad_prefill; records what was called."""
    calls = []

    def connect():
        calls.append("connect")
        return "https://oasis/api", "tok"

    def fetch_uploads(url, token):
        calls.append("uploads")
        return UPLOADS

    def fetch_samples(url, token, upload_id):
        calls.append(("samples", upload_id))
        return list(SAMPLES)

    monkeypatch.setattr(nomad_prefill, "connect", connect)
    monkeypatch.setattr(nomad_prefill, "fetch_uploads", fetch_uploads)
    monkeypatch.setattr(nomad_prefill, "fetch_samples_in_upload", fetch_samples)
    return calls


def _generated_sheet(module, app, monkeypatch):
    built = []
    real = module.ExperimentExcelBuilder

    def recording(*args, **kwargs):
        builder = real(*args, **kwargs)
        built.append(builder)
        return builder

    monkeypatch.setattr(module, "ExperimentExcelBuilder", recording)
    app._on_generate_excel(None)
    [builder] = built
    return builder.workbook["Experiment Data"]


def test_the_prefill_panel_is_hidden_and_nothing_is_fetched_at_start(fake_nomad):
    app = _app_module().MinimalistExperimentBuilder()
    assert app.prefill_panel.layout.display == "none"
    assert fake_nomad == []


def test_the_example_row_is_on_by_default_and_off_while_prefilling(fake_nomad):
    """A prefilled file is meant to be uploaded, and an example row left in it becomes a
    sample; normal use keeps the example row."""
    app = _app_module().MinimalistExperimentBuilder()
    assert app.is_testing_checkbox.value is True
    app.prefill_toggle.value = True
    assert app.is_testing_checkbox.value is False
    app.prefill_toggle.value = False
    assert app.is_testing_checkbox.value is True


def test_closing_the_panel_restores_an_unticked_example_row(fake_nomad):
    app = _app_module().MinimalistExperimentBuilder()
    app.is_testing_checkbox.value = False
    app.prefill_toggle.value = True
    app.is_testing_checkbox.value = True  # the user may still tick it while prefilling
    app.prefill_toggle.value = False
    assert app.is_testing_checkbox.value is False


def test_the_panel_says_where_to_upload_and_what_is_kept():
    app = _app_module().MinimalistExperimentBuilder()
    assert app.prefill_note in app.prefill_panel.children
    assert "same upload" in app.prefill_note.value
    assert "kept as they are" in app.prefill_note.value


def test_opening_the_panel_loads_the_uploads_once(fake_nomad):
    app = _app_module().MinimalistExperimentBuilder()
    app.prefill_toggle.value = True
    assert app.prefill_panel.layout.display != "none"
    assert list(app.prefill_upload_dropdown.options) == [
        (app.PREFILL_PLACEHOLDER, None),
        ("Batch 7", "up1"),
        ("up2", "up2"),
    ]
    assert app.prefill_upload_dropdown.value is None
    app.prefill_toggle.value = False
    app.prefill_toggle.value = True
    assert fake_nomad == ["connect", "uploads"]


def test_choosing_an_upload_loads_its_samples_and_names_the_columns(fake_nomad):
    app = _app_module().MinimalistExperimentBuilder()
    app.prefill_toggle.value = True
    app.prefill_upload_dropdown.value = "up1"
    assert fake_nomad[-1] == ("samples", "up1")
    assert app.prefill_samples == SAMPLES
    assert "2 samples" in app.prefill_info.value
    assert "Substrate conductive layer" in app.prefill_info.value


def test_generate_prefills_while_the_panel_is_open(fake_nomad, monkeypatch):
    module = _app_module()
    app = module.MinimalistExperimentBuilder()
    app.is_testing_checkbox.value = False
    app.prefill_toggle.value = True
    app.prefill_upload_dropdown.value = "up1"
    ws = _generated_sheet(module, app, monkeypatch)
    assert ws.cell(3, _column(ws, "Nomad ID")).value == "HZB_A_1_1_C-1"
    assert ws.cell(3, _column(ws, "Number of pixels")).value == 6
    assert app.download_area.value


def test_closing_the_panel_turns_the_prefill_off(fake_nomad, monkeypatch):
    module = _app_module()
    app = module.MinimalistExperimentBuilder()
    app.is_testing_checkbox.value = False
    app.prefill_toggle.value = True
    app.prefill_upload_dropdown.value = "up1"
    app.prefill_toggle.value = False
    ws = _generated_sheet(module, app, monkeypatch)
    assert str(ws.cell(3, _column(ws, "Nomad ID")).value).startswith("=IF(")


def test_a_failed_upload_list_is_shown_and_retried_on_the_next_opening(fake_nomad, monkeypatch):
    def no_token():
        raise ValueError("Token not found")

    working_connect = nomad_prefill.connect  # the fake_nomad one
    monkeypatch.setattr(nomad_prefill, "connect", no_token)
    app = _app_module().MinimalistExperimentBuilder()
    app.prefill_toggle.value = True
    assert "Token not found" in app.prefill_info.value
    assert list(app.prefill_upload_dropdown.options) == [(app.PREFILL_PLACEHOLDER, None)]
    monkeypatch.setattr(nomad_prefill, "connect", working_connect)
    app.prefill_toggle.value = False
    app.prefill_toggle.value = True
    assert len(app.prefill_upload_dropdown.options) == 3


def test_a_failed_sample_query_is_shown_and_nothing_is_prefilled(fake_nomad, monkeypatch):
    def broken(url, token, upload_id):
        raise RuntimeError("HTTP 500")

    app = _app_module().MinimalistExperimentBuilder()
    app.prefill_toggle.value = True
    monkeypatch.setattr(nomad_prefill, "fetch_samples_in_upload", broken)
    app.prefill_upload_dropdown.value = "up1"
    assert "HTTP 500" in app.prefill_info.value
    assert app.prefill_samples == []


def test_going_back_to_the_placeholder_clears_the_samples(fake_nomad):
    app = _app_module().MinimalistExperimentBuilder()
    app.prefill_toggle.value = True
    app.prefill_upload_dropdown.value = "up1"
    app.prefill_upload_dropdown.value = None
    assert app.prefill_samples == []
    assert app._samples_to_prefill() == []


def test_sample_names_are_escaped_in_the_info_line(fake_nomad, monkeypatch):
    monkeypatch.setattr(
        nomad_prefill,
        "fetch_samples_in_upload",
        lambda url, token, upload_id: [PrefillSample("<b>x</b>")],
    )
    app = _app_module().MinimalistExperimentBuilder()
    app.prefill_toggle.value = True
    app.prefill_upload_dropdown.value = "up1"
    assert "<b>x</b>" not in app.prefill_info.value
    assert "&lt;b&gt;x&lt;/b&gt;" in app.prefill_info.value


def test_no_linter_comment_is_shown_in_the_page_or_the_readme(monkeypatch):
    """'# noqa: E501' sat inside the HTML strings and was printed in the header, in the
    download box and in every generated README."""
    module = _app_module()
    app = module.MinimalistExperimentBuilder()
    shown = []
    monkeypatch.setattr(module, "display", shown.append)
    app.display()

    def html_values(widget):
        if hasattr(widget, "value") and isinstance(widget.value, str):
            yield widget.value
        for child in getattr(widget, "children", ()) or ():
            yield from html_values(child)

    texts = [*html_values(shown[0])]
    texts.append(app._create_download_link(b"PK", "x.xlsx"))
    texts.append(app._create_readme_download_link("# r", "README.md"))
    texts.append(app._generate_readme())
    assert texts and not [t for t in texts if "noqa" in t]
