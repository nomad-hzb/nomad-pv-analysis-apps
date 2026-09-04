# app.py
# Thin orchestrator for the Thickness Tracer app. Placeholder for now: it returns the
# "to be created" notice and nothing else.
#
# What the real app will do, and what porting it needs:
#   * The working notebook (Thickness.ipynb, team_real_tools NOMAD upload) is a four line
#     wrapper: it reads h5_path and screenwidth from the IPython store, builds
#     reflectance_modeling.thickness_tracer.THICKNESS_TRACER, and calls display_thickness().
#     The ISA Previewer is what puts h5_path into the store, so this app is always entered
#     from there, never standalone.
#   * reflectance_modeling has to become a pyproject.toml dependency. Its install URL in the
#     current notebook carries a GitLab deploy token inline; that token must not enter this
#     repo, and it should be rotated, since it is readable in every NOMAD upload holding a
#     copy of that notebook. Credentials belong to the deployment environment.
#   * The proxy env vars and the pip install cell in the current notebook do not come along:
#     dependencies are declared in pyproject.toml here.
#   * Reading h5_path out of the IPython store belongs in a data_manager.py (see
#     Peak_Explorer's get_h5_path_from_ipython), added when the port happens rather than
#     left empty now. It needs a guard for the case where nothing was stored yet, i.e. the
#     app was opened directly instead of through the previewer.

import logging

import gui_components
import ipywidgets as widgets

logger = logging.getLogger(__name__)


def initialize_ui() -> widgets.Widget:
    """Build the app UI. Returns the placeholder notice until the app is ported."""
    logger.info("Thickness_tracer placeholder opened; app not implemented yet")
    return gui_components.create_placeholder()
