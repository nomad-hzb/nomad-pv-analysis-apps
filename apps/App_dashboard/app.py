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

    root = widgets.VBox(layout=widgets.Layout(padding="10px"))

    def render_app_card(entry):
        if entry.external_url:
            href = full_url = entry.external_url
        else:
            if not entry.upload_id and not dm.notebook_exists(entry):
                logger.warning(
                    "Notebook not found for %s: %s/%s", entry.name, entry.folder, entry.notebook
                )
            href = dm.build_voila_url(entry, user, uploads_path)
            full_url = f"{dm.URL_BASE}{href}"
        return gui.create_app_card(entry, href, full_url)

    def render_learning_card(entry):
        href = dm.build_jupyter_url(entry, user)
        full_url = f"{dm.URL_BASE}{href}"
        return gui.create_app_card(entry, href, full_url)

    def show_main(_button=None):
        project_cards = [
            gui.create_project_card(project, lambda _b, p=project: show_project(p))
            for project in dm.PROJECTS
        ]
        projects_section = gui.create_category_section("Projects", project_cards)
        learning_hub_card = gui.create_hub_card(
            "Learning",
            "Guided Python & NOMAD tutorial notebooks, numbered start to finish.",
            "fa-graduation-cap",
            show_learning,
        )
        learning_section = gui.create_category_section("Learning", [learning_hub_card])

        sections = []
        for category, entries in dm.CATEGORIES.items():
            if category == "Build Your Own":
                sections.append(projects_section)
                sections.append(learning_section)
            sections.append(
                gui.create_category_section(category, [render_app_card(e) for e in entries])
            )

        root.children = [
            gui.create_style(),
            gui.create_header(user),
            *sections,
            gui.create_footer(),
        ]

    def show_project(project):
        cards = [render_app_card(e) for e in project.apps]
        root.children = [
            gui.create_style(),
            gui.create_header(user),
            gui.create_back_button(show_main),
            gui.create_category_section(project.name, cards),
            gui.create_footer(),
        ]

    def show_learning(_button=None):
        cards = [render_learning_card(e) for e in dm.LEARNING_NOTEBOOKS]
        root.children = [
            gui.create_style(),
            gui.create_header(user),
            gui.create_back_button(show_main),
            gui.create_category_section("Learning", cards),
            gui.create_footer(),
        ]

    show_main()
    return root
