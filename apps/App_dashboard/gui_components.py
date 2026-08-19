import ipywidgets as widgets

CATEGORY_ICONS = {
    "Projects": "fa-layer-group",
    "Data Management": "fa-database",
    "Device Characterization": "fa-solar-panel",
    "Optical & Structural Analysis": "fa-microscope",
    "Utilities & Calculators": "fa-toolbox",
    "Build Your Own": "fa-robot",
    "Experimental / In Progress": "fa-flask",
}

STYLE = """
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
<style>
.dashboard-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
}
.dashboard-header h1 { margin-bottom: 4px; }
.dashboard-subtitle { color: #555; margin-top: 0; }
.dashboard-warning { color: #a94442; }
.whats-new-link {
    flex-shrink: 0;
    padding: 6px 12px;
    border-radius: 6px;
    background-color: rgba(52, 152, 219, 0.12);
    color: #3498db;
    text-decoration: none;
    font-size: 0.85em;
    font-weight: 600;
    white-space: nowrap;
}
.whats-new-link:hover { background-color: rgba(52, 152, 219, 0.22); }
.whats-new-link i { margin-right: 5px; }
.category-title {
    margin: 0 0 10px 0;
    padding-bottom: 6px;
    border-bottom: 2px solid #eee;
    color: #333;
}
.category-title i { color: #3498db; margin-right: 8px; }
.app-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 340px));
    gap: 14px;
    width: 100%;
}
@media (max-width: 640px) {
    .app-grid { grid-template-columns: repeat(2, 1fr); }
}
.app-card {
    display: flex;
    align-items: center;
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    padding: 12px;
    border-radius: 8px;
    background-color: #f5f5f5;
    text-decoration: none;
    color: inherit;
    transition: background-color 0.2s, box-shadow 0.2s;
}
.app-card:hover {
    background-color: #e9f7fe;
    box-shadow: 0 2px 6px rgba(0,0,0,0.15);
}
.app-icon {
    width: 44px;
    height: 44px;
    min-width: 44px;
    font-size: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-right: 12px;
    color: #3498db;
    background-color: rgba(52, 152, 219, 0.12);
    border-radius: 8px;
}
.app-title { font-weight: 600; }
.app-badge {
    margin-left: 6px;
    padding: 1px 6px;
    font-size: 0.7em;
    font-weight: 600;
    text-transform: uppercase;
    color: #a94442;
    background-color: #f2dede;
    border-radius: 4px;
    vertical-align: middle;
}
.app-description { font-size: 0.85em; color: #666; margin-top: 2px; }
button.app-card {
    border: none;
    cursor: pointer;
    font-size: 1em;
    justify-content: flex-start;
}
button.app-card:hover {
    background-color: #e9f7fe;
    box-shadow: 0 2px 6px rgba(0,0,0,0.15);
}
.dashboard-footer { margin-top: 10px; color: #777; font-size: 0.9em; }
</style>
"""


def create_style() -> widgets.HTML:
    return widgets.HTML(STYLE)


WHATS_NEW_URL = "https://github.com/nomad-hzb/nomad-pv-analysis-apps/releases"


def create_header(user: str) -> widgets.HTML:
    if user:
        subtitle = (
            f"Signed in as <strong>{user}</strong> &mdash; "
            "links below open your NOMAD session directly."
        )
    else:
        subtitle = (
            "<span class='dashboard-warning'>Could not detect your NOMAD username "
            "(NOMAD_CLIENT_USER is not set) &mdash; links below may not resolve. "
            "Try reopening this dashboard from your NOMAD upload page.</span>"
        )
    return widgets.HTML(f"""
        <div class="dashboard-header">
            <div>
                <h1>NOMAD Analysis Tools</h1>
                <p class="dashboard-subtitle">{subtitle}</p>
            </div>
            <a class="whats-new-link" href="{WHATS_NEW_URL}" target="_blank"
               title="See recent changes and releases">
                <i class="fas fa-bullhorn"></i>What's New
            </a>
        </div>
    """)


def create_app_card(entry, href: str, full_url: str) -> widgets.HTML:
    badge = '<span class="app-badge">experimental</span>' if entry.experimental else ""
    return widgets.HTML(f"""
        <a class="app-card" href="{href}" target="_blank" title="{full_url}">
            <div class="app-icon"><i class="fas {entry.icon}"></i></div>
            <div class="app-body">
                <div class="app-title">{entry.name}{badge}</div>
                <div class="app-description">{entry.description}</div>
            </div>
        </a>
    """)


def create_hub_card(name: str, description: str, icon: str, on_click) -> widgets.Button:
    """A clickable card that opens a sub-page (e.g. a project's app menu, the learning
    notebook list) instead of linking straight out to an app or notebook."""
    btn = widgets.Button(
        description=name,
        tooltip=description,
        icon=icon.removeprefix("fa-"),
        layout=widgets.Layout(width="100%", height="100%"),
    )
    btn.add_class("app-card")
    btn.on_click(on_click)
    return btn


def create_project_card(project, on_click) -> widgets.Button:
    return create_hub_card(project.name, project.description, project.icon, on_click)


def create_back_button(on_click) -> widgets.Button:
    btn = widgets.Button(
        description="Back to Dashboard",
        icon="arrow-left",
        layout=widgets.Layout(margin="0 0 14px 0"),
    )
    btn.on_click(on_click)
    return btn


def create_category_section(title: str, cards: list) -> widgets.VBox:
    icon = CATEGORY_ICONS.get(title, "fa-folder")
    header = widgets.HTML(f'<h2 class="category-title"><i class="fas {icon}"></i>{title}</h2>')
    grid = widgets.GridBox(cards, layout=widgets.Layout(width="100%"))
    grid.add_class("app-grid")
    return widgets.VBox([header, grid], layout=widgets.Layout(margin="0 0 26px 0"))


def create_footer() -> widgets.HTML:
    return widgets.HTML("""
        <div class="dashboard-footer">
            <p>Links open in a new tab and point at your current NOMAD session and upload.
            If a link 404s, refresh this dashboard from the NOMAD upload page so it picks up
            your current username and upload.</p>
        </div>
    """)
