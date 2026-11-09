"""The download package starts downloading by itself: no link holding the zip as base64."""

import importlib.util
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as widgets
import pandas as pd

_GUI_PATH = Path(__file__).parents[2] / "apps" / "MPPT_Analysis" / "gui_components.py"


def _gui_module():
    spec = importlib.util.spec_from_file_location("gui_mppt_download", _GUI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_is_started_as_a_download_with_a_summary(monkeypatch):
    gui = _gui_module()
    started = []

    def fake_start(output, *args, **kwargs):
        started.append((output, args, kwargs))

    monkeypatch.setattr(gui, "start_download", fake_start)
    app_state = SimpleNamespace(
        has_curves_data=lambda: False,
        fitted_curves_data=None,
        has_selected_samples=lambda: False,
        has_fit_results=lambda: True,
        get_fit_results_count=lambda: 3,
    )
    fake = SimpleNamespace(
        app_state=app_state,
        _DOWNLOAD_STAGES=gui.GUIComponents._DOWNLOAD_STAGES,
        _add_statistical_summary_sheet=lambda writer: pd.DataFrame({"a": [1]}).to_excel(
            writer, sheet_name="Statistical_Summary"
        ),
        _add_plots_to_zip=lambda zip_file, plots_format: 0,
        _add_histograms_to_zip=lambda zip_file, plots_format: None,
        _add_readme_to_zip=lambda zip_file, counter, plots_format: None,
    )
    link = widgets.Output()
    gui.GUIComponents._create_download_package(
        fake, "html", True, True, link, widgets.Output(), widgets.IntProgress()
    )
    ((output, (content, filename, mime_type), kwargs),) = started
    assert output is link and mime_type == "application/zip"
    assert filename.startswith("MPPT_Analysis_Results_") and filename.endswith(".zip")
    assert zipfile.ZipFile(io.BytesIO(content)).namelist() == ["MPPT_Analysis_Results.xlsx"]
    assert "3 fitted curves" in kwargs["note"] and "base64" not in kwargs["note"]
