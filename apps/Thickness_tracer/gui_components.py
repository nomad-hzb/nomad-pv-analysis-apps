# gui_components.py
# All ipywidgets code for the Thickness Tracer app.
# Today it builds only the "not implemented yet" notice; once the app is ported it also
# holds whatever controls sit around THICKNESS_TRACER's own output.

import logging

import ipywidgets as widgets

logger = logging.getLogger(__name__)

PLACEHOLDER_HTML = """
<div style="max-width:44em; padding:1.5em; font-size:1.05em; line-height:1.55">
  <h2 style="margin-top:0">Thickness Tracer</h2>
  <p><strong>To be created.</strong> This app is not implemented yet.</p>
  <p>
    The working thickness notebook currently lives outside this repository, in the
    <code>team_real_tools</code> NOMAD upload. Until it is ported here, reach it through the
    "Open Thickness Analyzer Notebook" link in the ISA Previewer.
  </p>
</div>
"""


def create_placeholder() -> widgets.Widget:
    """The notice shown in place of the not-yet-ported app."""
    return widgets.HTML(value=PLACEHOLDER_HTML)
