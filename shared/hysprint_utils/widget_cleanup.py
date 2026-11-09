"""Close the widgets of an app's previous UI build before building it again.

clear_output() only hides widgets; ipywidgets keeps every one alive in its registry until it
is closed. Without this, each re-run of the cell leaves another set of live on_click/observe
handlers behind (one click then fires all of them) and keeps their data in memory.
"""

import logging
from contextlib import contextmanager

import ipywidgets as widgets

logger = logging.getLogger(__name__)


def live_widgets():
    """ipywidgets' registry of open widgets, {model_id: widget}.

    ipywidgets 8.1+ keeps it in the module dict `_instances` (Widget.widgets is deprecated
    there and gone in 9); 8.0 only has Widget.widgets."""
    from ipywidgets.widgets import widget as widget_module

    instances = getattr(widget_module, "_instances", None)
    return instances if instances is not None else widgets.Widget.widgets


def close_widgets(widget_ids):
    """Close every still-open widget among widget_ids; one that fails is logged and skipped."""
    registry = live_widgets()
    for widget_id in list(widget_ids):
        widget = registry.get(widget_id)
        if widget is None:
            continue
        try:
            widget.close()
        except Exception:  # noqa: BLE001 - one broken widget must not stop the rebuild
            logger.warning("Could not close stale widget %s", widget_id, exc_info=True)


class UiRebuild:
    """The widgets one UI build created, closed when the next build starts.

    Only widgets created inside build() are tracked, never framework-level singletons that
    existed before (ipyvuetify templates and the like). Use one module-level instance per app:

        _ui = UiRebuild()

        def initialize_ui(...):
            with _ui.build():
                ui = ...
            return ui
    """

    def __init__(self):
        self.widget_ids = set()

    @contextmanager
    def build(self):
        close_widgets(self.widget_ids)
        self.widget_ids = set()
        before = set(live_widgets())
        try:
            yield self
        finally:
            # Also after a failed build, so its half-made widgets are closed next time.
            self.widget_ids = set(live_widgets()) - before
