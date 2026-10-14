"""The app manual: one `manual.md` per app, shown behind a "Manual" button.

    from hysprint_utils.manual import manual_panel
    display(manual_panel(__file__))

The file is looked up next to the module that passes `__file__`, so it works whatever the
kernel's working directory is. Markdown is rendered into an Output that stays in the displayed
widget tree (a bare display() inside a button callback is dropped under Voila).
"""

from pathlib import Path

import ipywidgets as widgets
from IPython.display import Markdown, display

MANUAL_FILE = "manual.md"


def read_manual(app_file, filename=MANUAL_FILE) -> str | None:
    """The manual text next to `app_file`, or None when the app has no manual file."""
    path = Path(app_file).resolve().parent / filename
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def manual_panel(app_file, filename=MANUAL_FILE) -> widgets.Widget:
    """A "Manual" toggle button and the rendered manual below it."""
    toggle = widgets.ToggleButton(description="📖 Manual", icon="book")
    out = widgets.Output()

    def show(change):
        out.clear_output()
        if not change["new"]:
            return
        text = read_manual(app_file, filename)
        with out:
            display(Markdown(text if text is not None else "*This app has no manual yet.*"))

    toggle.observe(show, names="value")
    return widgets.VBox([toggle, out])
