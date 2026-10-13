# File_Uploader: widget-lifecycle constraints

- Display `batch_selection_container` intact: splitting its children across two VBox parents breaks rendering. `load_batch_button` (children[2]) is dropped with `children = children[:2]`.
- On a re-run close only the widgets in `_ui_widget_ids` (`app.py`), never all of `Widget.widgets`: ipyvuetify keeps shared template singletons alive.
- Observers on `dropdown_all_files` use the `_registered_observer = [None]` pattern so they do not pile up.
- Widget duplication after several re-runs in the VS Code notebook view is a VS Code quirk; it does not happen under Voila.
