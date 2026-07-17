import logging

import data_manager as dm
import gui_components as gui
import ipywidgets as widgets

logger = logging.getLogger(__name__)


def setup_app():
    """Assemble and return the app dashboard widget."""
    user = dm.get_current_user()
    uploads_path = dm.get_uploads_path()

    if not user:
        logger.warning("NOMAD_CLIENT_USER not set; generated links may be incorrect.")

    sections = []
    for category, entries in dm.CATEGORIES.items():
        cards = []
        for entry in entries:
            if not dm.notebook_exists(entry):
                logger.warning(
                    "Notebook not found for %s: %s/%s", entry.name, entry.folder, entry.notebook
                )
            voila_url = dm.build_voila_url(entry, user, uploads_path)
            full_url = f"{dm.URL_BASE}{voila_url}"
            cards.append(gui.create_app_card(entry, voila_url, full_url))
        sections.append(gui.create_category_section(category, cards))

    return widgets.VBox(
        [gui.create_style(), gui.create_header(user), *sections, gui.create_footer()],
        layout=widgets.Layout(padding="10px"),
    )
