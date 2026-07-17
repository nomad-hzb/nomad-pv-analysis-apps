"""
app.py
Thin assembly layer.  Instantiates data managers, builds panels, wires tabs.
"""

from __future__ import annotations

import logging

import data_manager as dm
import gui_components as gc
import ipywidgets as widgets
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)
class HansenApp:
    """
    Unified Hansen Solubility Parameter app.

    Tabs
    ----
    1. 3D Solvent Explorer   – all solvents from db.csv, colour + search
    2. 2D Properties         – scatter and correlation matrix
    3. Blend Optimiser       – SLSQP optimisation to match a target HSP
    4. Mixture Calculator    – manual % blend → weighted averages
    5. Inks                  – PlottedInks.xlsx (Inks sheet) with solute envelopes
    6. Perovskite            – PlottedInks.xlsx (Sheet2 / Sheet3)
    """

    def __init__(
        self,
        db_path: str = "db.csv",
        inks_path: str = "PlottedInks.xlsx",
    ):
        self._db_path = db_path
        self._inks_path = inks_path

        # Data managers
        self._solvent_dm = dm.SolventDataManager(db_path)
        self._ink_dm = dm.InkDataManager(inks_path, sheet="Inks")
        self._perov_dm = dm.PerovskiteDataManager(inks_path)

    # ------------------------------------------------------------------
    def display(self):
        logger.info("Loading data...")

        ok, msg = self._solvent_dm.load()
        logger.info("db.csv: %s -- %s", "ok" if ok else "fail", msg)

        ok_ink, msg_ink = self._ink_dm.load()
        logger.info("Inks sheet: %s -- %s", "ok" if ok_ink else "fail", msg_ink)

        ok_pv, msg_pv = self._perov_dm.load()
        logger.info("Perovskite: %s -- %s", "ok" if ok_pv else "fail", msg_pv)

        tabs = []
        labels = []

        # Tabs that require db.csv
        if self._solvent_dm.is_loaded:
            tabs.append(gc.SolventExplorerPanel(self._solvent_dm).widget)
            labels.append("3D Solvent Space")

            tabs.append(gc.DataVisualizerPanel(self._solvent_dm).widget)
            labels.append("2D Properties")

            tabs.append(gc.BlendCalculatorPanel(self._solvent_dm).widget)
            labels.append("Blend Optimiser")

            tabs.append(gc.MixtureCalculatorPanel(self._solvent_dm).widget)
            labels.append("Mixture Calculator")
        else:
            placeholder = widgets.HTML(
                "<p style='padding:20px;color:red'>"
                "db.csv not found.  Place it next to the notebook and restart.</p>"
            )
            for label in (
                "3D Solvent Space",
                "2D Properties",
                "Blend Optimiser",
                "Mixture Calculator",
            ):
                tabs.append(placeholder)
                labels.append(label)

        # Inks tab
        if ok_ink:
            tabs.append(gc.InksPanel(self._ink_dm).widget)
        else:
            tabs.append(
                widgets.HTML(f"<p style='padding:20px;color:red'>Inks not loaded: {msg_ink}</p>")
            )
        labels.append("Inks")

        # Perovskite tab
        if ok_pv:
            tabs.append(gc.PerovskitePanel(self._perov_dm).widget)
        else:
            tabs.append(
                widgets.HTML(
                    f"<p style='padding:20px;color:red'>Perovskite not loaded: {msg_pv}</p>"
                )
            )
        labels.append("Perovskite")

        tab_widget = widgets.Tab(children=tabs)
        for i, lbl in enumerate(labels):
            tab_widget.set_title(i, lbl)

        header = widgets.HTML(
            "<h2 style='text-align:center;margin-bottom:4px'>"
            "Hansen Solubility Parameter Tool Suite</h2>"
            "<p style='text-align:center;color:grey;margin-top:0'>"
            "HySPRINT · unified app</p>"
        )

        ipydisplay(widgets.VBox([header, tab_widget]))
