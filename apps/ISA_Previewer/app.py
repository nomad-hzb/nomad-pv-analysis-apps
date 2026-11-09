# app.py
# Thin orchestrator: picks the variant and hands it to gui_components. No business logic.
#
# The five notebooks in this folder all end here, differing only in the variant name they
# pass. What each variant shows is decided in config.VARIANTS.

import logging

import config
import gui_components
import ipywidgets as widgets

from hysprint_utils.widget_cleanup import UiRebuild

logger = logging.getLogger(__name__)

# A re-run of the cell first closes the widgets of the previous run (see UiRebuild).
_ui = UiRebuild()


def page_title(variant_name: str) -> str:
    """Browser tab title for a variant, so the notebook needs no second config import."""
    return _variant(variant_name).title


def initialize_ui(url: str, token: str, variant_name: str = "main") -> widgets.Widget:
    """Build the app for one variant.

    url:   NOMAD API endpoint, e.g. URL_BASE + API_ENDPOINT
    token: NOMAD access token
    variant_name: a key of config.VARIANTS ("main", "giwaxs", "optical", "timely", "video")
    """
    variant = _variant(variant_name)
    logger.info("Starting ISA Previewer variant %s", variant_name)

    with _ui.build():
        ui = gui_components.build_ui(url, token, variant)
    return ui


def _variant(variant_name: str) -> config.Variant:
    try:
        return config.VARIANTS[variant_name]
    except KeyError:
        raise KeyError(
            f"Unknown variant {variant_name!r}; expected one of {sorted(config.VARIANTS)}"
        ) from None
