from hysprint_utils import batch_selection, process_specs


def _solvent_keys(process_type, field_paths):
    return {k for k in field_paths[process_type] if k.startswith("Solvent ") and k.endswith("name")}


def test_indexed_autofill_range_follows_the_gui_maximum():
    """solvents/solutes allow 20 in the GUI, so a 6th..20th must autofill, not just 5."""
    paths = process_specs.build_field_paths()
    keys = _solvent_keys("Spin Coating", paths)
    assert "Solvent 5 name" in keys and "Solvent 6 name" in keys and "Solvent 20 name" in keys
    assert "Solvent 21 name" not in keys


def test_indexed_group_without_a_numeric_control_keeps_the_old_default():
    spec = {"meta": {"numeric_config": []}}
    assert process_specs._group_mapping_end(spec, "anything") == 5


def test_spinsteps_range_is_its_own_gui_maximum():
    spec = process_specs.PROCESSES["Spin Coating"]
    assert process_specs._group_mapping_end(spec, "spinsteps") == 5


def test_explicit_mapping_range_still_wins():
    paths = process_specs.build_field_paths()
    # Co-Evaporation declares (1, 10) on its material entries.
    assert "Material name 10" in paths["Co-Evaporation"]
    assert "Material name 11" not in paths["Co-Evaporation"]


def test_inkjet_defaults_have_no_phantom_annealing_key():
    defaults = process_specs.build_default_config_by_process_type()["Inkjet Printing"]
    assert "annealing" not in defaults
    assert defaults == {"solvents": 1, "solutes": 1, "gavd": False}


def test_batch_selection_hides_parent_batches_and_scales(monkeypatch):
    captured = {}

    class _W:
        def __init__(self, *a, **k):
            captured.setdefault("options", k.get("options"))
            self.layout = None
            self.value = ""

        def observe(self, *a, **k):
            pass

        def on_click(self, *a, **k):
            pass

    monkeypatch.setattr(batch_selection.widgets, "SelectMultiple", _W)
    monkeypatch.setattr(batch_selection.widgets, "Text", _W)
    monkeypatch.setattr(batch_selection.widgets, "VBox", lambda *a, **k: None)
    monkeypatch.setattr(batch_selection.widgets, "HBox", lambda *a, **k: None)
    monkeypatch.setattr(batch_selection.WidgetFactory, "create_button", lambda **k: _W())
    ids = ["HZB_A", "HZB_A_1", "HZB_A_2", "HZB_B_1"] + [f"HZB_X{n}_1" for n in range(5000)]
    monkeypatch.setattr(batch_selection, "get_batch_ids", lambda url, token: ids)
    batch_selection.create_batch_selection("u", "t", lambda w: None)
    options = list(captured["options"])
    # A sub-batch is hidden when its parent batch exists (HZB_A_1 under HZB_A), as before.
    assert "HZB_A_1" not in options and "HZB_A_2" not in options
    assert {"HZB_A", "HZB_B_1"} <= set(options)
    assert len(options) == 5000 + 2


def test_batch_selection_survives_an_unreachable_nomad():
    """No network or no valid token: the app still starts (demo mode stays reachable), the
    selector stays children[1] and the panel says why the list is empty."""
    import requests

    from hysprint_utils import batch_selection

    def fail(url, token):
        raise requests.ConnectionError("proxy unreachable")

    original = batch_selection.get_batch_ids
    batch_selection.get_batch_ids = fail
    try:
        box = batch_selection.create_batch_selection("u", "t", lambda w: None)
    finally:
        batch_selection.get_batch_ids = original
    assert list(box.children[1].options) == []
    assert "Could not load the batch list" in box.children[-1].value


def _panel(monkeypatch, **kwargs):
    ids = ["HZB_10", "HZB_2", "HZB_2_1", "Other_1", "HZB_1"]
    monkeypatch.setattr(batch_selection, "get_batch_ids", lambda url, token: ids)
    return batch_selection.create_batch_selection("u", "t", lambda w: None, **kwargs)


def test_batch_selection_without_a_filter_has_no_button(monkeypatch):
    box = _panel(monkeypatch)
    assert len(box.children) == 3
    assert box.children[2].description == "Load Data"


def test_show_only_filter_sits_under_the_list_and_toggles(monkeypatch):
    """Every app gets the same "Show <technique> only" button: under the list, above Load
    Data, as wide as the list. Search works within the shown list; a second click shows all."""
    box = _panel(monkeypatch, filter_label="TRPL", filter_function=lambda: ["HZB_10", "HZB_1"])
    search, selector, filter_row, load = box.children
    button, status = filter_row.children
    assert button.description == "Show TRPL only"
    assert button.layout.width == selector.layout.width == batch_selection.PANEL_WIDTH
    assert load.description == "Load Data"
    assert list(selector.options) == ["HZB_1", "HZB_2", "HZB_10", "Other_1"]

    button.click()
    assert list(selector.options) == ["HZB_1", "HZB_10"]
    assert button.description == "Show all batches" and not button.disabled
    assert "2 of 4 batches have TRPL data" in status.value
    search.value = "10"
    assert list(selector.options) == ["HZB_10"]

    button.click()
    assert button.description == "Show TRPL only" and status.value == ""
    assert list(selector.options) == ["HZB_10"]  # the search still applies, now to all
    search.value = ""
    assert list(selector.options) == ["HZB_1", "HZB_2", "HZB_10", "Other_1"]


def test_show_only_filter_failure_keeps_the_full_list(monkeypatch):
    def fail():
        raise RuntimeError("500")

    box = _panel(monkeypatch, filter_label="NMR", filter_function=fail)
    selector = box.children[1]
    button, status = box.children[2].children
    button.click()
    assert len(selector.options) == 4
    assert button.description == "Show NMR only" and not button.disabled
    assert "Could not ask NOMAD" in status.value and "RuntimeError" in status.value


def test_show_only_filter_queries_the_entry_type_by_default(monkeypatch):
    calls = []

    def fake(url, token, entry_type):
        calls.append((url, token, entry_type))
        return ["HZB_2"]

    monkeypatch.setattr(batch_selection, "get_all_batches_wth_data", fake)
    box = _panel(monkeypatch, filter_label="EQE", filter_entry_type="HySprint_EQEmeasurement")
    box.children[2].children[0].click()
    assert calls == [("u", "t", "HySprint_EQEmeasurement")]
    assert list(box.children[1].options) == ["HZB_2"]


def test_single_choice_batch_list_starts_empty(monkeypatch):
    """multiple=False (File_Uploader: one batch at a time) gives a widgets.Select with nothing
    preselected; the default stays a SelectMultiple."""
    import ipywidgets as widgets

    single = _panel(monkeypatch, multiple=False).children[1]
    assert type(single) is widgets.Select and single.value is None
    assert type(_panel(monkeypatch).children[1]) is widgets.SelectMultiple


def test_show_only_filter_remembers_the_batches_it_found(monkeypatch):
    calls = []

    def find():
        calls.append(1)
        return ["HZB_10", "HZB_1"]

    box = _panel(monkeypatch, filter_label="MPPT", filter_function=find)
    selector = box.children[1]
    button, status = box.children[2].children
    button.click()  # asks NOMAD
    button.click()  # all batches
    button.click()  # the remembered result, no new question
    assert calls == [1]
    assert list(selector.options) == ["HZB_1", "HZB_10"]
    assert button.description == "Show all batches" and "2 of 4" in status.value


def test_a_failed_filter_is_asked_again_and_shows_the_http_status(monkeypatch):
    import requests

    answers = []

    def find():
        answers.append(1)
        if len(answers) == 1:
            response = requests.Response()
            response.status_code = 502
            raise requests.HTTPError("bad gateway", response=response)
        return ["HZB_2"]

    box = _panel(monkeypatch, filter_label="JV", filter_function=find)
    button, status = box.children[2].children
    button.click()
    assert "(HTTP 502)" in status.value and button.description == "Show JV only"
    button.click()
    assert list(box.children[1].options) == ["HZB_2"] and len(answers) == 2
