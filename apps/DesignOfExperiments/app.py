"""
Main application controller for the Design of Experiments Voila application.
Manages tab structure, user interactions, and coordination between modules.
"""

import base64
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import ipywidgets as widgets
import numpy as np
import pandas as pd
from IPython.display import clear_output, display

from data_manager import DataManager
from gui_components import GUIComponents
from plot_manager import PlotManager
from sampling_algorithms import SamplingEngine
from utils import Constants, ValidationUtils

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _sec(title: str) -> widgets.HTML:
    """Section header: bold label with a subtle underline, replacing h3 + hr."""
    return widgets.HTML(
        f"<div style='margin: 18px 0 8px 0; padding-bottom: 4px; "
        f"border-bottom: 1px solid #e0e0e0; font-size: 14px; "
        f"font-weight: 600; color: #333;'>{title}</div>"
    )


def _subsec(title: str) -> widgets.HTML:
    """Lighter sub-section label used within a section."""
    return widgets.HTML(
        f"<div style='margin: 12px 0 4px 0; font-size: 13px; "
        f"font-weight: 600; color: #444;'>{title}</div>"
    )


# ---------------------------------------------------------------------------
# Application controller
# ---------------------------------------------------------------------------


class DoEApplication:
    """Main application controller for Design of Experiments interface."""

    def __init__(self):
        """Initialize the DoE application with all modules."""
        self.data_manager = DataManager()
        self.sampling_engine = SamplingEngine()
        self.gui_components = GUIComponents()
        self.plot_manager = PlotManager()
        self.validator = ValidationUtils()

        self.current_samples = None
        self.current_figure = None
        self.current_algorithm = "Latin Hypercube Sampling"
        self.quality_metrics = {}

        self.main_interface = self._create_main_interface()

        if hasattr(self.gui_components, "generate_button"):
            self.gui_components.generate_button.on_click(self._on_generate_samples)

        self._setup_event_handlers()

    # ------------------------------------------------------------------
    # Interface construction
    # ------------------------------------------------------------------

    def _create_main_interface(self):
        """Create the main tabbed interface."""
        self.tabs = widgets.Tab()

        tab1 = self._create_setup_tab()
        tab2 = self._create_results_viz_tab()
        tab3 = self._create_export_tab()

        self.tabs.children = [tab1, tab2, tab3]
        for i, title in enumerate(["Setup & Variables", "Results & Visualization", "Export"]):
            self.tabs.set_title(i, title)

        header = self._create_header()
        return widgets.VBox([header, self.tabs])

    def _create_header(self):
        """Create application header with title and status."""
        title = widgets.HTML(
            value="<div style='text-align: center; font-size: 20px; font-weight: 600; "
            "color: #2E4057; padding: 10px 0 4px 0;'>Design of Experiments</div>",
            layout=widgets.Layout(margin="4px 0"),
        )
        self.status_label = widgets.HTML(
            value="<div style='text-align: center; color: #888; font-size: 13px; "
            "padding-bottom: 6px;'>Ready — select algorithm and define variables to begin</div>",
            layout=widgets.Layout(margin="0"),
        )
        return widgets.VBox([title, self.status_label])

    def _create_setup_tab(self):
        """Create Tab 1: Algorithm, Sample Config, Variable Configuration, Generate."""
        algorithm_section = self.gui_components.create_algorithm_selector()
        size_section = self.gui_components.create_sample_size_configurator()
        seed_section = self.gui_components.create_seed_configurator()
        advanced_section = self.gui_components.create_advanced_options()
        variable_section = self.gui_components.create_variable_configurator()
        control_section = self.gui_components.create_generation_controls()
        self.progress_section = self.gui_components.create_progress_section()
        self.metrics_section = self.gui_components.create_metrics_section()

        return widgets.VBox(
            [
                _sec("Algorithm"),
                algorithm_section,
                _sec("Sample Configuration"),
                size_section,
                seed_section,
                advanced_section,
                _sec("Variable Configuration"),
                variable_section,
                _sec("Generate"),
                control_section,
                self.progress_section,
                _subsec("Quality Metrics"),
                self.metrics_section,
            ],
            layout=widgets.Layout(padding="16px 20px"),
        )

    def _create_results_viz_tab(self):
        """Create Tab 2: Generated Samples, Visualizations, Summary Statistics."""
        # Info bar: New Design button + current run details
        self.run_info_label = widgets.HTML(
            value="<span style='color: #999; font-size: 13px;'>No samples generated yet</span>",
            layout=widgets.Layout(margin="0 0 0 12px"),
        )
        self.new_design_btn = widgets.Button(
            description="New Design",
            button_style="",
            icon="random",
            layout=widgets.Layout(width="130px"),
            tooltip="Randomize seed and regenerate a fresh design",
        )
        info_bar = widgets.HBox(
            [self.new_design_btn, self.run_info_label],
            layout=widgets.Layout(
                padding="6px 0 8px 0",
                align_items="center",
                border_bottom="1px solid #e0e0e0",
            ),
        )

        # Samples table
        self.table_section = widgets.VBox(
            [
                widgets.HTML(
                    "<span style='font-size: 13px; font-weight: 600; color: #444;'>"
                    "Generated Samples</span>"
                ),
                widgets.Output(
                    layout=widgets.Layout(
                        height="300px", overflow="auto", border="1px solid #e0e0e0"
                    )
                ),
            ]
        )

        # Visualization — no fixed height so large scatter matrices don't overflow
        viz_controls = self.gui_components.create_visualization_controls()
        self.plot_area = widgets.Output(layout=widgets.Layout(min_height="350px"))

        # Summary statistics at the bottom
        self.summary_section = self.gui_components.create_summary_section()

        return widgets.VBox(
            [
                info_bar,
                _sec("Samples"),
                self.table_section,
                _sec("Visualizations"),
                viz_controls,
                self.plot_area,
                _sec("Summary Statistics"),
                self.summary_section,
            ],
            layout=widgets.Layout(padding="16px 20px"),
        )

    def _create_export_tab(self):
        """Create Tab 3: Export Table and Readable Protocol."""
        explanation = widgets.HTML(
            value=(
                "<div style='font-size: 12px; color: #666; background: #f7f7f7; "
                "padding: 10px 12px; border-radius: 3px; margin-bottom: 4px; "
                "border-left: 3px solid #ddd;'>"
                "<b>Export Table</b> — the sample matrix as CSV, JSON, or Excel; "
                "machine-readable, suitable for analysis software or lab automation.<br>"
                "<b>Readable Protocol</b> — a numbered step-by-step document for a lab technician "
                "to follow manually, with optional randomised execution order."
                "</div>"
            )
        )
        export_section = self.gui_components.create_export_section()
        protocol_section = self.gui_components.create_protocol_section()

        tab_content = widgets.VBox(
            [
                explanation,
                _sec("Export Table"),
                export_section,
                _sec("Readable Protocol"),
                protocol_section,
            ],
            layout=widgets.Layout(padding="16px 20px"),
        )

        return widgets.VBox(
            children=[tab_content],
            layout=widgets.Layout(height="600px", overflow="auto"),
        )

    # ------------------------------------------------------------------
    # Event wiring
    # ------------------------------------------------------------------

    def _setup_event_handlers(self):
        """Setup event handlers for user interactions."""
        if hasattr(self.gui_components, "algorithm_dropdown"):
            self.gui_components.algorithm_dropdown.observe(
                self._on_algorithm_change, names="value"
            )

        if hasattr(self.gui_components, "generate_button"):
            self.gui_components.generate_button.on_click(self._on_generate_samples)

        # Tab 1 "Regenerate" button → same as New Design
        if hasattr(self.gui_components, "regenerate_button"):
            self.gui_components.regenerate_button.on_click(self._on_new_design)

        if hasattr(self.gui_components, "plot_type_dropdown"):
            self.gui_components.plot_type_dropdown.observe(
                self._on_plot_type_change, names="value"
            )

        if hasattr(self.gui_components, "export_plot_button"):
            self.gui_components.export_plot_button.on_click(self._on_export_plot)

        if hasattr(self, "new_design_btn"):
            self.new_design_btn.on_click(self._on_new_design)

    # ------------------------------------------------------------------
    # Generation handlers
    # ------------------------------------------------------------------

    def _on_algorithm_change(self, change):
        self.current_algorithm = change["new"]
        self._update_status(f"Algorithm changed to: {self.current_algorithm}")
        self.gui_components.update_advanced_options(self.current_algorithm)

    def _on_generate_samples(self, button):
        """Generate samples with current settings and seed."""
        if hasattr(self.gui_components, "generate_button"):
            self.gui_components.generate_button.disabled = True

        try:
            variables = self.gui_components.get_variables_from_widgets()

            if not variables:
                self._update_status("Error: Please define at least one variable", error=True)
                return

            self.data_manager.clear_all_variables()
            for var in variables:
                success, msg = self.data_manager.add_variable(var)
                if not success:
                    self._update_status(f"Error: {msg}", error=True)
                    return

            params = self.gui_components.get_sampling_parameters()
            self._show_progress("Generating samples…")

            self.current_samples = self.sampling_engine.generate_samples(
                variables=variables,
                algorithm=self.current_algorithm,
                **params,
            )

            self.quality_metrics = self.sampling_engine.calculate_quality_metrics(
                self.current_samples, variables
            )

            self._update_results_display()
            self._update_metrics_display()
            self._update_viz_options(variables)
            self._update_visualizations()

            self._hide_progress()

            n = len(self.current_samples)
            seed = params.get("random_state", 42)
            self._update_status(f"Generated {n} samples successfully")

            # Update info bar on tab 2
            self.run_info_label.value = (
                f"<span style='color: #555; font-size: 13px;'>"
                f"Seed&nbsp;<b>{seed}</b>&nbsp;&nbsp;·&nbsp;&nbsp;"
                f"{n}&nbsp;samples&nbsp;&nbsp;·&nbsp;&nbsp;"
                f"{self.current_algorithm}</span>"
            )

            # Tab badge
            self.tabs.set_title(1, f"Results & Visualization ({n})")

            if self.current_samples is not None and not self.current_samples.empty:
                self.gui_components.set_current_data(
                    samples=self.current_samples,
                    variables=variables,
                    metrics=self.quality_metrics,
                    algorithm=self.current_algorithm,
                    random_seed=seed,
                )
                self.tabs.selected_index = 1

        except Exception as e:
            self._hide_progress()
            self._update_status(f"Error generating samples: {str(e)}", error=True)
            logger.exception("Error generating samples: %s", e)
        finally:
            if hasattr(self.gui_components, "generate_button"):
                self.gui_components.generate_button.disabled = False

    def _on_new_design(self, button):
        """Randomize seed and regenerate — produces a genuinely different design."""
        new_seed = int(np.random.randint(1, 2**31))
        if hasattr(self.gui_components, "random_seed"):
            self.gui_components.random_seed.value = new_seed
        self._on_generate_samples(button)

    def _on_plot_type_change(self, change):
        if self.current_samples is not None:
            self._update_visualizations()

    # ------------------------------------------------------------------
    # Progress / status
    # ------------------------------------------------------------------

    def _show_progress(self, message):
        if hasattr(self, "progress_section"):
            self.gui_components.show_progress(self.progress_section, message)

    def _hide_progress(self):
        if hasattr(self, "progress_section"):
            self.gui_components.hide_progress(self.progress_section)

    def _update_status(self, message, error=False):
        color = "#c0392b" if error else "#888"
        self.status_label.value = (
            f"<div style='text-align: center; color: {color}; font-size: 13px; "
            f"padding-bottom: 6px;'>{message}</div>"
        )

    # ------------------------------------------------------------------
    # Display updates
    # ------------------------------------------------------------------

    def _update_results_display(self):
        if self.current_samples is not None:
            if hasattr(self, "table_section"):
                alg = self.current_algorithm.replace("_", " ")
                self.table_section.children = (
                    widgets.HTML(
                        f"<span style='font-size: 13px; font-weight: 600; color: #444;'>"
                        f"Generated Samples — {alg}</span>"
                    ),
                    self.table_section.children[1],
                )

            self.gui_components.update_data_table(self.table_section, self.current_samples)

            variables = self.data_manager.get_variables()
            self.gui_components.update_summary_statistics(
                self.summary_section, self.current_samples, variables
            )

    def _update_metrics_display(self):
        if self.quality_metrics:
            self.gui_components.update_metrics_display(
                self.metrics_section, self.quality_metrics
            )

    def _update_viz_options(self, variables):
        """Filter plot type options based on the number of numeric variables."""
        if not hasattr(self.gui_components, "plot_type_dropdown"):
            return

        n_numeric = sum(1 for v in variables if v.type.value in ("continuous", "discrete"))

        options = [
            ("Scatter Plot Matrix", "splom"),
            ("Parallel Coordinates", "parallel"),
            ("Distribution Plots", "distributions"),
            ("Space-Filling Quality", "quality"),
        ]
        if n_numeric >= 3:
            options.insert(3, ("3D Scatter Plot", "3d_scatter"))
        if n_numeric >= 2:
            options.append(("Correlation Heatmap", "correlation"))

        current = self.gui_components.plot_type_dropdown.value
        self.gui_components.plot_type_dropdown.options = options
        valid = [o[1] for o in options]
        self.gui_components.plot_type_dropdown.value = current if current in valid else "splom"

    def _update_visualizations(self):
        if self.current_samples is None or not hasattr(self, "plot_area"):
            return

        with self.plot_area:
            clear_output(wait=True)
            try:
                plot_type = self.gui_components.get_selected_plot_type()
                variables = self.data_manager.get_variables()

                fig = self.plot_manager.create_plot(
                    plot_type=plot_type,
                    data=self.current_samples,
                    variables=variables,
                    algorithm=self.current_algorithm,
                )

                if fig:
                    fig.show()
                    self.current_figure = fig
            except Exception as e:
                logger.error("Error creating plot: %s", e)

    def _on_export_plot(self, button):
        if not hasattr(self, "current_figure") or self.current_figure is None:
            with self.plot_area:
                clear_output(wait=True)
                display(
                    widgets.HTML(
                        "<p style='color: #c0392b;'>No plot to export. Generate samples first.</p>"
                    )
                )
            return

        try:
            with self.plot_area:
                clear_output(wait=True)
                display(self.current_figure)
                display(widgets.HTML("<p style='color: #888; font-size: 13px;'>Creating file…</p>"))

            html_content = self.current_figure.to_html(include_plotlyjs=True)
            b64 = base64.b64encode(html_content.encode()).decode()

            link_html = (
                f"<a download='doe_plot.html' href='data:text/html;base64,{b64}' "
                f"style='background: #333; color: #fff; padding: 8px 14px; "
                f"text-decoration: none; border-radius: 3px; font-size: 13px; "
                f"display: inline-block; margin-top: 6px;'>Download Plot (HTML)</a>"
            )

            with self.plot_area:
                clear_output(wait=True)
                display(self.current_figure)
                display(widgets.HTML(link_html))

        except Exception as e:
            with self.plot_area:
                clear_output(wait=True)
                display(self.current_figure)
                display(
                    widgets.HTML(f"<p style='color: #c0392b;'>Export failed: {str(e)}</p>")
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self):
        return {
            "variables_count": len(self.data_manager.get_variables()),
            "samples_generated": (
                len(self.current_samples) if self.current_samples is not None else 0
            ),
            "current_algorithm": self.current_algorithm,
            "has_quality_metrics": bool(self.quality_metrics),
        }

    def get_current_tab(self):
        return self.tabs.selected_index if hasattr(self, "tabs") else 0

    def export_configuration(self):
        config = {
            "timestamp": datetime.now().isoformat(),
            "algorithm": self.current_algorithm,
            "variables": [var.to_dict() for var in self.data_manager.get_variables()],
            "samples": (
                self.current_samples.to_dict("records")
                if self.current_samples is not None
                else None
            ),
            "quality_metrics": self.quality_metrics,
            "version": Constants.APPLICATION_VERSION,
        }
        return json.dumps(config, indent=2, default=str)

    def import_configuration(self, config_json):
        try:
            config = json.loads(config_json)

            self.current_algorithm = config.get("algorithm", "Latin Hypercube Sampling")

            variables = config.get("variables", [])
            self.data_manager.set_variables(variables)

            if config.get("samples"):
                self.current_samples = pd.DataFrame(config["samples"])

            self.quality_metrics = config.get("quality_metrics", {})

            self.gui_components.update_from_configuration(config)
            self._update_results_display()
            self._update_metrics_display()
            self._update_visualizations()

            self._update_status("Configuration imported successfully")
            return True

        except Exception as e:
            self._update_status(f"Error importing configuration: {str(e)}", error=True)
            return False
