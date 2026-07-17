"""
app.py
------
Thin assembly layer for the Wetting Envelope app.
Single public method: display().
"""

from __future__ import annotations

import logging

import data_manager as dm
import gui_components as gui
import ipywidgets as widgets
import plot_manager as pm  # noqa: F401
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)


class WettingEnvelopeApp:
    """
    Usage::

        app = WettingEnvelopeApp()
        app.display()
    """

    def __init__(self) -> None:
        self._dm = dm.WettingDataManager()

        self._plot_panel = gui.PlotPanel()
        self._mat_panel = gui.MaterialPanel(self._dm)
        self._sol_panel = gui.SolventPanel(self._dm)
        self._settings_panel = gui.PlotSettingsPanel(
            data_mgr=self._dm,
            plot_panel=self._plot_panel,
            material_panel=self._mat_panel,
            solvent_panel=self._sol_panel,
        )

    def display(self) -> None:
        top_row = widgets.HBox(
            [self._mat_panel.widget, self._sol_panel.widget],
            layout=widgets.Layout(gap="16px", flex_wrap="wrap"),
        )
        app_layout = widgets.VBox(
            [top_row, self._settings_panel.widget, self._plot_panel.widget],
            layout=widgets.Layout(padding="12px", gap="8px"),
        )
        ipydisplay(app_layout)
