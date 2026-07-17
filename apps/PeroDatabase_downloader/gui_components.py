"""The ipywidgets front end.

The only module that knows about widgets. It holds no business logic:
every handler reads widget values, calls a DataManager method, and writes
the result back to a widget. Moving to Dash means rewriting this file
alone and keeping everything else.
"""

import base64

import config
import ipywidgets as widgets
from auth import authenticate
from IPython.display import HTML, clear_output, display


def _download_link(data_bytes, filename, label):
    b64 = base64.b64encode(data_bytes).decode()
    href = f"data:text/csv;base64,{b64}"
    return (
        f'<a download="{filename}" href="{href}" style="font-weight:600;color:#E8730C;">{label}</a>'
    )


def _header(text):
    return widgets.HTML(f"<h3 style='margin:8px 0 2px 0;color:#0A2540;'>{text}</h3>")


class ExtractorGUI:
    def __init__(self, data_manager, auth=None):
        self.dm = data_manager
        self.auth = auth
        self._build()

    # -- construction -----------------------------------------------------
    def _build(self):
        # Server selector. Same token works across servers, so switching is
        # only about which data you want.
        self.server_dd = widgets.Dropdown(
            options=[(label, s["url"]) for label, s in config.SERVERS.items()],
            value=self.dm.client.api_url,
            description="Server",
            layout=widgets.Layout(width="560px"),
            style={"description_width": "70px"},
        )
        self.server_dd.observe(self._on_server, names="value")
        self.auth_html = widgets.HTML(self._auth_banner_html())

        # Entry type selector: the population anchor. Fetched from the server
        # so it reflects real types, defaulting to the most common one.
        self.entry_type_dd = widgets.Combobox(
            placeholder="leave blank for all entries",
            description="Entry type",
            ensure_option=False,
            layout=widgets.Layout(width="560px"),
            style={"description_width": "90px"},
        )
        self.entry_type_dd.observe(self._on_entry_type, names="value")
        self.entry_type_help = widgets.HTML("")
        self.reload_types_btn = widgets.Button(
            description="Reload types", layout=widgets.Layout(width="130px")
        )
        self.reload_types_btn.on_click(lambda _b: self._load_entry_types())
        # Apply the per server default scope so central starts on the
        # perovskite database rather than all of NOMAD.
        init_type = config.default_entry_type_for(self.dm.client.api_url)
        self.dm.set_entry_type(init_type)
        self.entry_type_dd.value = init_type

        # Catalog dropdown. Selecting an item fills path and name below.
        options = [("Choose a field ...", "")]
        options += [(c["label"], c["path"]) for c in self.dm.catalog]
        self.catalog_dd = widgets.Dropdown(
            options=options,
            value="",
            description="Catalog",
            layout=widgets.Layout(width="560px"),
            style={"description_width": "70px"},
        )
        self.catalog_dd.observe(self._on_pick, names="value")

        self.path_input = widgets.Text(
            placeholder="path, e.g. results.properties.optoelectronic.solar_cell.fill_factor",
            description="Path",
            layout=widgets.Layout(width="560px"),
            style={"description_width": "70px"},
        )
        self.name_input = widgets.Text(
            description="Name",
            placeholder="column name",
            layout=widgets.Layout(width="360px"),
            style={"description_width": "70px"},
        )

        self.test_btn = widgets.Button(description="Test path")
        self.test_btn.on_click(self._on_test)
        self.add_btn = widgets.Button(description="Add field", button_style="success")
        self.add_btn.on_click(self._on_add)
        self.msg = widgets.HTML("")

        self.fields_box = widgets.VBox([])

        # Extraction and results
        self.run_btn = widgets.Button(
            description="Extract", button_style="primary", icon="download"
        )
        self.run_btn.on_click(self._on_run)
        self.progress = widgets.IntProgress(
            value=0, min=0, max=1, layout=widgets.Layout(width="560px")
        )
        self.status = widgets.HTML("")
        self.coverage_out = widgets.HTML("")
        self.complete_only = widgets.RadioButtons(
            options=[("All rows", False), ("Only rows with every selected field", True)],
            value=False,
            description="Download",
        )
        self.csv_out = widgets.HTML("")
        self.preview_out = widgets.Output()

        # Debug panel, collapsed by default.
        self.debug_out = widgets.HTML("<i>Nothing logged yet.</i>")
        self.debug_box = widgets.Accordion(children=[self.debug_out])
        self.debug_box.set_title(0, "Debug log")
        self.debug_box.selected_index = None  # collapsed

        # Attach the download-mode observer once, not on every extraction.
        self.complete_only.observe(lambda _c: self._render_csv_link(), names="value")

        self._refresh_fields()
        self._load_entry_types()

    def _load_entry_types(self):
        """Fetch entry types from the server to offer as suggestions. The
        default scope comes from config, not from the most common type, so
        central starts on the perovskite database and does not silently pick
        whatever type happens to be largest.
        """
        try:
            types = self.dm.list_entry_types()
        except Exception:
            types = []
        self._render_debug()
        if types:
            self.entry_type_dd.options = [t for t, _ in types]
            summary = ", ".join(f"{t} ({c})" for t, c in types[:4])
            self.entry_type_help.value = (
                f"<span style='color:#555'>Available types include: {summary}. "
                f"Blank means every entry type.</span>"
            )
        else:
            self.entry_type_help.value = (
                "<span style='color:#555'>Type list unavailable. The default "
                "scope still applies. Type a type by hand, or leave blank for "
                "all. See the debug log.</span>"
            )

    # -- helpers ----------------------------------------------------------
    def _refresh_fields(self):
        rows = []
        for spec in self.dm.fields:
            label = widgets.HTML(
                f"<code>{spec.output_name()}</code> "
                f"<span style='color:#888'>&larr; {spec.path}</span>"
            )
            btn = widgets.Button(description="remove", layout=widgets.Layout(width="90px"))
            btn.on_click(self._make_remover(spec.output_name()))
            rows.append(widgets.HBox([btn, label]))
        self.fields_box.children = rows or [widgets.HTML("<i>No fields selected yet.</i>")]

    def _make_remover(self, output_name):
        def handler(_):
            self.dm.remove_field(output_name)
            self._refresh_fields()

        return handler

    def _auth_banner_html(self):
        a = self.auth
        if a is None:
            return ""
        if a.ok:
            body = (
                f"Authenticated as <b>{a.user}</b>"
                + (f" ({a.email})" if a.email else "")
                + ". Access includes your visible entries."
            )
            bg = "#eaf6ea"
        else:
            body = a.message
            bg = "#fdf3e3"
        return (
            f"<div style='padding:6px 10px;background:{bg};border-radius:4px;"
            f"margin:4px 0'>{body}</div>"
        )

    def _on_entry_type(self, change):
        self.dm.set_entry_type(change["new"].strip())

    def _on_server(self, change):
        url = change["new"]
        self.dm.set_server(url)
        # Same token, re-verify against the newly selected server.
        self.auth = authenticate(url, token=self.dm.client.token)
        self.dm.client.set_token(self.auth.token)
        self.auth_html.value = self._auth_banner_html()
        # Apply the destination server's default scope.
        dest_type = config.default_entry_type_for(url)
        self.dm.set_entry_type(dest_type)
        self.entry_type_dd.value = dest_type
        self.msg.value = (
            "<span style='color:#555'>Switched server. "
            "Previous results cleared, extract again.</span>"
        )
        self.csv_out.value = ""
        self.coverage_out.value = ""
        with self.preview_out:
            clear_output()
        self._load_entry_types()

    # -- handlers ---------------------------------------------------------
    def _on_pick(self, change):
        path = change["new"]
        if not path:
            return
        entry = self.dm.catalog_by_path.get(path, {})
        self.path_input.value = path
        self.name_input.value = entry.get("column", path.split(".")[-1])

    def _on_test(self, _):
        path = self.path_input.value.strip()
        if not path:
            self.msg.value = "<span style='color:#b00'>Enter a path first.</span>"
            return
        self.msg.value = "<span style='color:#555'>Testing against a live sample ...</span>"
        try:
            exists, coverage = self.dm.validate(path)
        except Exception as exc:
            self.msg.value = f"<span style='color:#b00'>Test failed: {exc}</span>"
            self._render_debug()
            return
        self._render_debug()
        if exists:
            self.msg.value = (
                f"<span style='color:#127a12'>Found. Present in "
                f"{coverage:.0%} of the sample.</span>"
            )
        else:
            self.msg.value = (
                "<span style='color:#b00'>Not found in the sample. "
                "Check the spelling, or it may be an archive only path.</span>"
            )

    def _on_add(self, _):
        path = self.path_input.value.strip()
        if not path:
            self.msg.value = "<span style='color:#b00'>Enter a path first.</span>"
            return
        spec = self.dm.make_field(path, self.name_input.value.strip())
        warning = self.dm.add_field(spec)
        if warning:
            self.msg.value = f"<span style='color:#b00'>{warning}</span>"
            return
        saved = self.dm.add_to_catalog(spec)
        if saved:
            self._refresh_catalog_dd()
        note = " Saved to catalog." if saved else ""
        self.msg.value = f"<span style='color:#127a12'>Added '{spec.output_name()}'.{note}</span>"
        self.catalog_dd.value = ""
        self.path_input.value = ""
        self.name_input.value = ""
        self._refresh_fields()
        self._render_debug()

    def _refresh_catalog_dd(self):
        options = [("Choose a field ...", "")]
        options += [(c["label"], c["path"]) for c in self.dm.catalog]
        self.catalog_dd.options = options
        self.catalog_dd.value = ""

    def _on_run(self, _):
        if not self.dm.fields:
            self.status.value = (
                "<span style='color:#b00'>Add at least one field before extracting.</span>"
            )
            return
        # Immediate visual feedback the moment the button is pressed.
        self.run_btn.disabled = True
        self.run_btn.description = "Extracting ..."
        self.progress.bar_style = "info"
        self.progress.value = 0
        self.progress.max = 1
        self.status.value = "<span style='color:#555'>Contacting NOMAD ...</span>"
        self.csv_out.value = ""
        self.coverage_out.value = ""
        try:
            df = self.dm.run(progress=self._progress)
        except Exception as exc:
            self.progress.bar_style = "danger"
            self.status.value = f"<span style='color:#b00'>Extraction failed: {exc}</span>"
            self._render_debug()
            self._reset_run_btn()
            return
        self.progress.bar_style = "success"
        self._render_debug()
        self._show_results(df)
        self._reset_run_btn()

    def _reset_run_btn(self):
        self.run_btn.disabled = False
        self.run_btn.description = "Extract"

    def _progress(self, current, total, message):
        self.progress.max = max(int(total), 1)
        self.progress.value = min(int(current), self.progress.max)
        self.status.value = f"<span style='color:#555'>{message}</span>"

    def _show_results(self, df):
        cov = self.dm.coverage()
        if cov:
            items = "".join(f"<li><code>{c}</code>: {v:.0%}</li>" for c, v in cov.items())
            self.coverage_out.value = (
                f"<b>Coverage across {len(df)} rows:</b><ul style='margin:4px 0'>{items}</ul>"
            )
        with self.preview_out:
            clear_output()
            display(HTML("<i>No rows returned.</i>") if df.empty else df.head(config.PREVIEW_ROWS))
        self._render_csv_link()

    def _render_debug(self):
        log = self.dm.debug_log
        if not log:
            self.debug_out.value = "<i>Nothing logged yet.</i>"
            return
        lines = "<br>".join(str(x).replace("<", "&lt;") for x in log)
        self.debug_out.value = (
            f"<pre style='white-space:pre-wrap;font-size:12px;margin:0'>{lines}</pre>"
        )

    def _render_csv_link(self):
        complete = self.complete_only.value
        data = self.dm.to_csv_bytes(complete_only=complete)
        n = len(self.dm.get_dataframe(complete_only=complete))
        fname = f"nomad_export_{'complete' if complete else 'all'}.csv"
        self.csv_out.value = _download_link(data, fname, f"Download CSV ({n} rows)")

    # -- render -----------------------------------------------------------
    def render(self):
        panel = widgets.VBox(
            [
                widgets.HTML(
                    "<h2 style='color:#0A2540;margin-bottom:0'>NOMAD field extractor</h2>"
                ),
                self.server_dd,
                self.auth_html,
                _header("1. Which entries (entry type)"),
                widgets.HBox([self.entry_type_dd, self.reload_types_btn]),
                self.entry_type_help,
                _header("2. Pick or type the fields you want"),
                self.catalog_dd,
                self.path_input,
                self.name_input,
                widgets.HBox([self.test_btn, self.add_btn]),
                self.msg,
                widgets.HTML("<b>Selected fields</b>"),
                self.fields_box,
                _header("3. Extract and download"),
                self.run_btn,
                self.progress,
                self.status,
                self.coverage_out,
                self.complete_only,
                self.csv_out,
                widgets.HTML("<b>Preview</b>"),
                self.preview_out,
                self.debug_box,
            ]
        )
        # Return the panel only. The notebook cell displays the returned
        # value once. Calling display() here as well would draw it twice.
        return panel
