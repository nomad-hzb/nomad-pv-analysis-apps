import ipywidgets as widgets

CATEGORY_ICONS = {
    "Data Management": "fa-database",
    "Device Characterization": "fa-solar-panel",
    "Optical & Structural Analysis": "fa-microscope",
    "Utilities & Calculators": "fa-toolbox",
    "Experimental / In Progress": "fa-flask",
}

STYLE = """
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
<style>
.dashboard-header h1 { margin-bottom: 4px; }
.dashboard-subtitle { color: #555; margin-top: 0; }
.dashboard-warning { color: #a94442; }
.category-title {
    margin: 0 0 10px 0;
    padding-bottom: 6px;
    border-bottom: 2px solid #eee;
    color: #333;
}
.category-title i { color: #3498db; margin-right: 8px; }
.app-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
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
.dashboard-footer { margin-top: 10px; color: #777; font-size: 0.9em; }
</style>
"""


def create_style() -> widgets.HTML:
    return widgets.HTML(STYLE)


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
            <h1>NOMAD Analysis Tools</h1>
            <p class="dashboard-subtitle">{subtitle}</p>
        </div>
    """)


def create_app_card(entry, voila_url: str, full_url: str) -> widgets.HTML:
    badge = '<span class="app-badge">experimental</span>' if entry.experimental else ""
    return widgets.HTML(f"""
        <a class="app-card" href="{voila_url}" target="_blank" title="{full_url}">
            <div class="app-icon"><i class="fas {entry.icon}"></i></div>
            <div class="app-body">
                <div class="app-title">{entry.name}{badge}</div>
                <div class="app-description">{entry.description}</div>
            </div>
        </a>
    """)


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
