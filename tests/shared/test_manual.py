from hysprint_utils.manual import manual_panel, read_manual


def test_manual_is_found_next_to_the_app_file(tmp_path):
    (tmp_path / "manual.md").write_text("# Hello", encoding="utf-8")
    assert read_manual(tmp_path / "app.py") == "# Hello"
    assert read_manual(tmp_path / "other" / "app.py") is None


def test_panel_renders_only_when_opened(tmp_path):
    (tmp_path / "manual.md").write_text("# Hello", encoding="utf-8")
    panel = manual_panel(tmp_path / "app.py")
    toggle, out = panel.children
    assert out.outputs == () or not out.outputs
    toggle.value = True  # does not raise without a frontend
    toggle.value = False
