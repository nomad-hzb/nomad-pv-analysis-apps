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
