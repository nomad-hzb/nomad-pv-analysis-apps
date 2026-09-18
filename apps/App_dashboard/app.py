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
    # Button.on_click fires from a comm message, not a cell execution, so a bare
    # display() call inside it has no output area to land in and is silently
    # dropped by Voila. Routing it through a real Output() widget that's part of
    # the displayed tree is what actually renders (and runs) it.
    js_output = widgets.Output(layout=widgets.Layout(width="0px", height="0px", overflow="hidden"))

    def open_app(name: str, url: str, _button=None):
        """Log the launch, then open the app in a new tab.

        App-launch cards are Buttons (not real <a> links) specifically so this
        click reaches the Python kernel and can be logged -- opening the new
        tab itself still needs a one-line injected script, since only the
        browser can open tabs and only this kernel can write the log file.
        """
        dm.log_navigation(name)
        with js_output:
            js_output.clear_output(wait=True)
            display(Javascript(f"window.open({json.dumps(url)}, '_blank')"))

    def render_app_card(entry):
        if entry.external_url:
            full_url = entry.external_url
        else:
            if not entry.upload_id and not dm.notebook_exists(entry):
                logger.warning(
                    "Notebook not found for %s: %s/%s", entry.name, entry.folder, entry.notebook
                )
            full_url = f"{dm.URL_BASE}{dm.build_voila_url(entry, user, uploads_path)}"
        return gui.create_app_card_overlay(
            entry, full_url, lambda _b, name=entry.name, url=full_url: open_app(name, url)
        )

    def render_learning_card():
        entry = dm.LEARNING_FOLDER
        full_url = f"{dm.URL_BASE}{dm.build_jupyter_url(entry, user, dm.get_upload_id())}"
        return gui.create_app_card_overlay(
            entry, full_url, lambda _b, name=entry.name, url=full_url: open_app(name, url)
        )

    def open_whats_new(_button=None):
        open_app("whats_new", gui.WHATS_NEW_URL)

    def show_main(_button=None):
        project_cards = [
            gui.create_project_card(project, lambda _b, p=project: show_project(p))
            for project in dm.PROJECTS
        ]

        sections = []
        for category, entries in dm.CATEGORIES.items():
            cards = [render_app_card(e) for e in entries]
            if category == "Build Your Own":
                # Omit the section entirely on a deployment with no configured
                # projects, rather than showing an empty "Projects" header.
                if project_cards:
                    sections.append(gui.create_category_section("Projects", project_cards))
                cards.insert(0, render_learning_card())
            sections.append(gui.create_category_section(category, cards))

        root.children = [
            gui.create_style(),
            gui.create_header(user, open_whats_new),
            *sections,
            gui.create_footer(),
        ]

    def show_project(project):
        dm.log_navigation(f"open_project:{project.name}")
        cards = [render_app_card(e) for e in project.apps]
        root.children = [
            gui.create_style(),
            gui.create_header(user, open_whats_new),
            gui.create_back_button(go_back),
            gui.create_category_section(project.name, cards),
            gui.create_footer(),
        ]

    def go_back(_button=None):
        dm.log_navigation("back_to_dashboard")
        show_main()

    show_main()
    return widgets.VBox([root, js_output])
