"""
SEM Crystal Counter App
=======================
Thin assembly layer. Import and call app.display() from the notebook.
"""

from __future__ import annotations

import logging
from pathlib import Path

import data_manager as dm_module
import gui_components as gui
import ipywidgets as widgets
from IPython.display import display as ipydisplay

from hysprint_utils.auth_manager import AuthenticationManager
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.manual import manual_panel

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "SEM_crystal_counter" / "fixtures" / "demo_images.json"


class SEMApp:
    """Top-level app: images from NOMAD or upload -> automatic analysis -> review."""

    def __init__(self, url_base: str, api_endpoint: str, token: str) -> None:
        self._auth = AuthenticationManager(url_base, api_endpoint)
        self._auth.authenticate_with_token(token)
        self._url = self._auth.api_client.get_api_url()
        self._token = self._auth.current_token
        self._dm = dm_module.SemDataManager(url=self._url, token=self._token)

        self._load_out = widgets.Output()
        self._demo_btn = widgets.Button(
            description="Load demo data", button_style="warning", icon="database"
        )
        self._demo_btn.on_click(self._on_demo_load)
        self._upload_panel = gui.UploadPanel(self._on_upload)
        self._sources = widgets.Tab(children=[self._nomad_panel(), self._upload_panel.widget])
        self._sources.titles = ("From NOMAD", "Upload TIFFs")

        self._cross = gui.CrossSectionPanel(self._dm)
        self._analysis = gui.AnalysisPanel(self._dm, on_refresh=self._cross.refresh)
        self._review = gui.ReviewPanel(self._dm, on_changed=self._analysis.refresh)
        self._main = widgets.Tab(
            children=[self._analysis.widget, self._cross.widget, self._review.widget]
        )
        self._main.titles = ("Results", "Cross-sections", "Review and correct")
        self._clear_btn = widgets.Button(description="Remove all images", icon="trash")
        self._clear_btn.on_click(self._on_clear)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def display(self) -> None:
        ipydisplay(manual_panel(__file__))
        ipydisplay(widgets.HBox([self._demo_btn, self._clear_btn]))
        ipydisplay(self._sources)
        ipydisplay(self._load_out)
        ipydisplay(self._main)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _nomad_panel(self) -> widgets.Widget:
        """The batch selector, or the reason it is unavailable. Upload and demo do not need
        NOMAD, so a failing batch query (expired token, no connection) must not stop them."""
        try:
            return gui.BatchFilterPanel(self._url, self._token, self._on_batch_load).widget
        except Exception as exc:
            logger.warning("NOMAD batch list unavailable: %s", exc)
            return widgets.HTML(
                "<p style='color:#b00'>Could not get the batch list from NOMAD "
                f"({type(exc).__name__}). Check your login; uploading TIFFs and the demo "
                "still work.</p>"
            )

    def _on_demo_load(self, _b) -> None:
        self._load(lambda: self._dm.load_offline(DEMO_FIXTURE_PATH), "demo images")

    def _on_batch_load(self, batch_selector: widgets.SelectMultiple) -> None:
        batches = list(batch_selector.value)
        if not batches:
            ErrorHandler.log_error("Select at least one batch.", output_widget=self._load_out)
            return
        self._load(lambda: self._dm.load(batches), "images from NOMAD")

    def _on_upload(self, files: list[tuple[str, bytes]]) -> None:
        self._load(lambda: self._dm.add_uploads(files), "uploaded images")

    def _load(self, loader, what: str) -> None:
        before = len(self._dm.entries)
        with self._load_out:
            self._load_out.clear_output()
            ErrorHandler.log_info(f"Loading {what}...", output_widget=self._load_out)
        try:
            loader()
        except Exception as exc:
            with self._load_out:
                self._load_out.clear_output()
            ErrorHandler.log_error(f"Could not load {what}", exc, output_widget=self._load_out)
            return
        added = len(self._dm.entries) - before
        with self._load_out:
            self._load_out.clear_output()
            if not added:
                ErrorHandler.log_error(f"No {what} found.", output_widget=self._load_out)
                return
            ErrorHandler.log_success(
                f"Added {added} {what}; analysing them now.", output_widget=self._load_out
            )
        self._main.selected_index = 0
        self._analysis.analyse(only_new=True)
        self._review.refresh()

    def _on_clear(self, _b) -> None:
        self._dm.clear()
        self._analysis.refresh()
        self._review.refresh()
        with self._load_out:
            self._load_out.clear_output()
