import json
import logging

import data_manager as dm
import gui_components as gui
import ipywidgets as widgets
from IPython.display import Javascript, display

logger = logging.getLogger(__name__)


def setup_app():
    """Assemble and return the app dashboard widget."""
    user = dm.get_current_user()
    uploads_path = dm.get_uploads_path()

    if not user:
        logger.warning("NOMAD_CLIENT_USER not set; generated links may be incorrect.")

    root = widgets.VBox(layout=widgets.Layout(padding="10px"))

    def open_app(name: str, url: str, _button=None):
        """Log the launch, then open the app in a new tab.

        App-launch cards are Buttons (not real <a> links) specifically so this
        click reaches the Python kernel and can be logged -- opening the new
        tab itself still needs a one-line injected script, since only the
        browser can open tabs and only this kernel can write the log file.
        """
        dm.log_navigation(f"open_app:{name}")
        display(Javascript(f"window.open({json.dumps(url)}, '_blank')"))

    def render_app_card(entry):
        if entry.external_url:
            href = full_url = entry.external_url
            return gui.create_app_card(entry, href, full_url)

        if not entry.upload_id and not dm.notebook_exists(entry):
            logger.warning(
                "Notebook not found for %s: %s/%s", entry.name, entry.folder, entry.notebook
            )
        href = dm.build_voila_url(entry, user, uploads_path)
        full_url = f"{dm.URL_BASE}{href}"
        return gui.create_app_launch_card(
            entry, full_url, lambda _b, name=entry.name, url=full_url: open_app(name, url)
        )

    def render_learning_card():
        entry = dm.LEARNING_FOLDER
        href = dm.build_jupyter_url(entry, user, dm.get_upload_id())
        full_url = f"{dm.URL_BASE}{href}"
        return gui.create_app_card(entry, href, full_url)

    def show_main(_button=None):
        project_cards = [
            gui.create_project_card(project, lambda _b, p=project: show_project(p))
            for project in dm.PROJECTS
        ]
        projects_section = gui.create_category_section("Projects", project_cards)

        sections = []
        for category, entries in dm.CATEGORIES.items():
            cards = [render_app_card(e) for e in entries]
            if category == "Build Your Own":
                sections.append(projects_section)
                cards.insert(0, render_learning_card())
            sections.append(gui.create_category_section(category, cards))

        root.children = [
            gui.create_style(),
            gui.create_header(user),
            *sections,
            gui.create_footer(),
        ]

    def show_project(project):
        dm.log_navigation(f"open_project:{project.name}")
        cards = [render_app_card(e) for e in project.apps]
        root.children = [
            gui.create_style(),
            gui.create_header(user),
            gui.create_back_button(go_back),
            gui.create_category_section(project.name, cards),
            gui.create_footer(),
        ]

    def go_back(_button=None):
        dm.log_navigation("back_to_dashboard")
        show_main()

    show_main()
    return root
