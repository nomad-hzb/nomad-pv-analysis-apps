"""Downloads: one script that hands the file over as a Blob (no base64 in an onclick), with the
file name passed as JSON."""

import base64
import importlib.util
import re
from pathlib import Path

_GUI_PATH = Path(__file__).parents[2] / "apps" / "JV-Analysis" / "gui_components.py"


def _save_ui(monkeypatch):
    """A SaveUI whose display() records what it shows (an Output widget captures nothing
    without a kernel)."""
    spec = importlib.util.spec_from_file_location("gui_jv_downloads", _GUI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shown = []
    monkeypatch.setattr(module, "display", shown.append)
    monkeypatch.setattr(module, "clear_output", shown.clear)
    save_ui = module.SaveUI()
    save_ui.shown = shown
    return save_ui


def _script(save_ui):
    (html,) = save_ui.shown
    return html.data


def test_download_is_a_blob_script_with_a_json_file_name(monkeypatch):
    save_ui = _save_ui(monkeypatch)
    content = b"PK\x03\x04 zip bytes"
    save_ui.trigger_download(content, "plots_2026'11\".zip", "application/zip")
    script = _script(save_ui)

    assert "onclick" not in script and "data:application" not in script
    assert "new Blob" in script and "URL.createObjectURL" in script
    assert 'a.download = "plots_2026\'11\\".zip";' in script
    assert '{type: "application/zip"}' in script
    (b64,) = re.findall(r"atob\('([A-Za-z0-9+/=]*)'\)", script)
    assert base64.b64decode(b64) == content


def test_text_content_is_encoded_and_a_new_download_replaces_the_old_script(monkeypatch):
    save_ui = _save_ui(monkeypatch)
    save_ui.trigger_download("first", "a.csv", "text/csv")
    save_ui.trigger_download("ä,b\n1,2", "b.csv", "text/csv")
    script = _script(save_ui)
    (b64,) = re.findall(r"atob\('([A-Za-z0-9+/=]*)'\)", script)
    assert base64.b64decode(b64).decode() == "ä,b\n1,2"
    assert '"b.csv"' in script
