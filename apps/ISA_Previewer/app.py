# app.py
# Thin orchestrator: picks the variant and hands it to gui_components. No business logic.
#
# The three notebooks in this folder all end here, differing only in the variant name they
# pass. What each variant shows is decided in config.VARIANTS.

import logging

import config
import gui_components
import ipywidgets as widgets

logger = logging.getLogger(__name__)

# Widgets built by the previous call are closed before new ones are made. clear_output only
# hides widgets, it does not destroy them, so without this every re-run of the cell leaves
# another set of live observers behind and one upload click fires all of them.
_ui_widget_ids: set = set()


def page_title(variant_name: str) -> str:
    """Browser tab title for a variant, so the notebook needs no second config import."""
    return _variant(variant_name).title


def initialize_ui(url: str, token: str, variant_name: str = "main") -> widgets.Widget:
    """Build the app for one variant.

    url:   NOMAD API endpoint, e.g. URL_BASE + API_ENDPOINT
    token: NOMAD access token
    variant_name: a key of config.VARIANTS ("main", "giwaxs", "optical")
    """
    global _ui_widget_ids

    variant = _variant(variant_name)
    logger.info("Starting ISA Previewer variant %s", variant_name)

    for widget_id in list(_ui_widget_ids):
        widget = widgets.Widget.widgets.get(widget_id)
        if widget is not None:
            try:
                widget.close()
            except Exception:
                logger.exception("Failed to close stale widget %s", widget_id)
    _ui_widget_ids = set()
    ids_before = set(widgets.Widget.widgets.keys())

    ui = gui_components.build_ui(url, token, variant)

    _ui_widget_ids = set(widgets.Widget.widgets.keys()) - ids_before
    return ui


def _variant(variant_name: str) -> config.Variant:
    try:
        return config.VARIANTS[variant_name]
    except KeyError:
        raise KeyError(
            f"Unknown variant {variant_name!r}; expected one of {sorted(config.VARIANTS)}"
        ) from None
