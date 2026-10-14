# gui_components.py
# All ipywidgets code. No NOMAD/API calls or Excel generation logic lives here - it all
# funnels through data_manager.py, which owns ExperimentState and never imports a widget
# library.

import logging

import ipywidgets as widgets
from data_manager import (
    ExperimentState,
    ProcessFieldSpec,
    apply_variation_template,
    auto_fill_variation_column,
    iter_varying_fields,
    populate_column_from_first,
    set_field_manual,
)
from gui_fields import _guard_forbidden_characters, _quick_fill_button_for, _sync_widget_value

logger = logging.getLogger(__name__)


def _split_varying_field_label(combined_label: str) -> tuple[str, str]:
    """iter_varying_fields() labels are always '<process label> - <field key>' (see its
    docstring); process labels never contain ' - ' themselves, so a first-occurrence split
    reliably separates them for the matrix's two-line header."""
    process_part, _, field_part = combined_label.partition(" - ")
    return (process_part, field_part) if field_part else ("", process_part)


class _MatrixCell:
    """One (sample, varying-field-or-Variation) cell in VaryingFieldsMatrix: a persistent
    Text input (+ optional quick-fill button, for a Date/Datetime/Operator field moved
    into the matrix - see _quick_fill_button_for's docstring for why it keeps the
    button), kept alive across matrix re-renders instead of rebuilt on every edit.
    Mirrors _FieldRow; see its class docstring for why. Here the win is much bigger: a
    per-keystroke change used to rebuild the ENTIRE matrix (every sample x every varying
    column, header included), which was very likely the real cause behind "the table
    sometimes doesn't appear"."""

    def __init__(self, field_key: str, warning_html: widgets.HTML, on_change):
        self.text = widgets.Text(
            layout=widgets.Layout(width="180px"),
            # continuous_update=False - see _FieldRow's value_widget for why.
            continuous_update=False,
        )
        self._observer = _guard_forbidden_characters(self.text, warning_html, on_change)
        quick_fill_button = _quick_fill_button_for(field_key, self.text)
        self.widget: widgets.Widget = (
            self.text
            if quick_fill_button is None
            else widgets.HBox(
                [self.text, quick_fill_button], layout=widgets.Layout(align_items="center")
            )
        )

    def sync(self, value) -> None:
        _sync_widget_value(self.text, self._observer, "" if value is None else str(value))


# (column_key, kind, spec, header_html, field_part, address) tuples describing the
# matrix's current columns, left to right - see VaryingFieldsMatrix._current_columns.
# kind is one of "sample"/"subbatch"/"field"/"variation"/"warning"; address is the
# label a caller (including tests) uses with header_widget/cell_widget - the exact
# iter_varying_fields label for a field column, "Sample"/"Subbatch"/"Variation" for
# those fixed columns, None for the warning column (not individually addressable, use
# row_warning_widget instead).
_MatrixColumn = tuple[object, str, "ProcessFieldSpec | None", str, str, "str | None"]


class VaryingFieldsMatrix(widgets.VBox):
    """One column per currently-varying field, one row per sample, plus a leading
    Sample/Subbatch pair of label columns (Subbatch = the sample's variation_group_index
    from Sample Setup, shown 1-based to match the Excel "Subbatch" value - see
    data_manager.subbatch_for_sample), a trailing (always-last) Variation column, and a
    shared per-sample warning column. Every field/Variation cell is directly editable -
    Variation is NOT auto-computed live (see update_variation_column's docstring for
    why); use the "Auto-fill Variation" button above VariationTemplatePanel for an
    on-demand bulk fill. Every field/Variation column header has a small arrow-down
    "populate" button that copies that column's first row down into every other row - a
    time-saver when most samples share one value.

    Rendered as an HBox of per-COLUMN VBoxes (header cell on top, then one cell per
    sample stacked underneath), NOT the row-per-sample HBox layout this table used to
    have. A CSS-grid GridBox with explicit layout.grid_row/grid_column placement was
    tried first (to decouple visual position from DOM/insertion order) and confirmed
    LIVE, via a real local Voila session, to silently NOT apply grid_row/grid_column at
    all in this environment's bundled frontend widget JS (every cell fell back to
    default grid auto-flow, which follows insertion order - i.e. the table visually
    scrambled itself into column-major "rows" instead of a normal table). This
    column-stacked layout sidesteps that entirely: it's plain, universally-supported
    flexbox nesting, so VISUAL position and DOM/Tab order are simply the same thing here
    - which is exactly what's wanted anyway, since the product ask was for Tab to move
    down a column (next sample) rather than across a row (next field), and building the
    DOM in that order natively gets both right with nothing fragile in between.
    Populate-down buttons in the header cell are excluded from the Tab cycle
    (`tabbable = False`, same trick _FieldRow already uses for its 'varies' checkbox) so
    Tab-ing off the last sample in one column lands directly on the first sample of the
    next column, not a header button in between.

    Every header cell, body cell, AND the per-column VBox wrapper itself is created once
    and cached (keyed by column identity, + sample_number for body cells) and only ever
    mutated in place afterward on subsequent renders - mirrors _FieldRow/_MatrixCell's
    established "keep widgets alive across renders" fix, extended here to the header row
    AND the column containers too: recreating a fresh Label/Button/VBox for every header
    cell (the old per-render `_build_column_header`), or even just a fresh per-column
    VBox wrapping the SAME cached cell widgets, on every single keystroke-commit anywhere
    in the table caused a real, live-verified regression - the VBox recreation alone was
    enough to bounce focus out to <body> on the very next Tab after a single edit (the
    frontend detaches/reattaches child views when a container widget's `.children` is
    reassigned to brand-new sibling widget instances, even when those instances' own
    children are unchanged) - and was the one remaining full-rebuild cost left in this
    table after the per-cell fix landed elsewhere in the app. It's what made large tables
    feel unresponsive even though every individual cell already had
    continuous_update=False."""

    _LABEL_COLUMN_WIDTH = "70px"
    _WARNING_COLUMN_WIDTH = "220px"
    # Every header's button slot (the real populate button, or a same-size blank
    # placeholder for a column that doesn't have one) reserves this height, so it's
    # uniform across every column kind - see _header_for's docstring.
    _HEADER_BUTTON_HEIGHT = "28px"

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change
        # overflow="auto": with enough varying columns, natural (unshrunk - see each
        # column VBox's own flex="0 0 auto" below) column widths can exceed whatever
        # width this widget is given by its parent. Without this, the browser's default
        # flex behavior SHRINKS every column below its intended width to fit instead of
        # overflowing - live-verified as the actual cause of "the table loses its
        # format" with more than ~2 varying columns: each column's own container
        # visibly narrower than the fixed-width Text input inside it, so inputs spilled
        # into neighboring columns. A single shared horizontal scrollbar for the whole
        # table (header row included, since headers live inside the same per-column
        # VBoxes) is the fix instead - not per-cell scrolling.
        self._columns_box = widgets.HBox([], layout=widgets.Layout(overflow="auto", width="100%"))
        self._column_boxes: dict[object, widgets.VBox] = {}
        self._header_cells: dict[object, widgets.Widget] = {}
        self._label_cells: dict[tuple[object, int], widgets.Label] = {}
        self._field_cells: dict[tuple[object, int], _MatrixCell] = {}
        self._row_warnings: dict[int, widgets.HTML] = {}
        super().__init__([])
        self._render()

    def refresh(self) -> None:
        self._render()

    def hard_refresh(self) -> None:
        """Drops every cached widget (header, cell, and warning) before rebuilding from
        nothing, instead of the normal refresh()'s reuse-in-place - manual fallback for
        when the frontend has been reported to get into a stuck render for very large
        tables (root cause unconfirmed - this is the standard ipywidgets folk remedy, not
        a proven fix). Wired to the 'Refresh Table' button in app.py."""
        self.children = []
        self._columns_box.children = []
        self._column_boxes = {}
        self._header_cells = {}
        self._label_cells = {}
        self._field_cells = {}
        self._row_warnings = {}
        self._render()

    def _notify_change(self) -> None:
        self._render()
        if self.on_change:
            self.on_change()

    def _current_columns(self, varying_fields=None) -> list[_MatrixColumn]:
        if varying_fields is None:
            varying_fields = iter_varying_fields(self.state)
        variation_spec = self.state.experiment_info_fields.get("Variation")
        # Every header's text is forced to two real HTML lines (a leading blank "<br>"
        # for headers that are conceptually single-line) - see _header_for's docstring
        # for why matching REAL rendered line count, not a guessed CSS min-height, is
        # what actually keeps every column's header the same height.
        columns: list[_MatrixColumn] = [
            ("__sample__", "sample", None, "<br>Sample", "", "Sample"),
            ("__subbatch__", "subbatch", None, "<br>Subbatch", "", "Subbatch"),
        ]
        for label, spec in varying_fields:
            process_part, field_part = _split_varying_field_label(label)
            columns.append(
                (id(spec), "field", spec, f"{process_part}<br>{field_part}", field_part, label)
            )
        columns.append(
            (
                "__variation__",
                "variation",
                variation_spec,
                "<br>Variation",
                "Variation",
                "Variation",
            )
        )
        columns.append(("__warning__", "warning", None, "&nbsp;<br>&nbsp;", "", None))
        return columns

    def _drop_stale(self, columns: list[_MatrixColumn], sample_numbers: list[int]) -> None:
        live_keys = {column[0] for column in columns}
        live_samples = set(sample_numbers)
        for key in list(self._column_boxes):
            if key not in live_keys:
                del self._column_boxes[key]
        for key in list(self._header_cells):
            if key not in live_keys:
                del self._header_cells[key]
        for key in list(self._label_cells):
            col_key, sample_number = key
            if col_key not in live_keys or sample_number not in live_samples:
                del self._label_cells[key]
        for key in list(self._field_cells):
            col_key, sample_number = key
            if col_key not in live_keys or sample_number not in live_samples:
                del self._field_cells[key]
        for sample_number in list(self._row_warnings):
            if sample_number not in live_samples:
                del self._row_warnings[sample_number]

    def _header_for(
        self, key: object, kind: str, spec: ProcessFieldSpec | None, header_html: str
    ) -> widgets.Widget:
        """Every column's header - regardless of kind - is the SAME two-part shape: a
        two-line text block followed by a button-height slot (the real populate button
        for a field/Variation column, or an equal-height blank placeholder for columns
        that don't have one - Sample/Subbatch/the warning column).

        The text block is always given TWO REAL lines - a genuine leading `<br>` for
        headers that are conceptually single-line ("Sample", "Variation", the blank
        warning header - see _current_columns) - rather than one line stretched to a
        guessed CSS min-height. An earlier version tried the min-height approach (a
        fixed pixel value meant to match a two-line block's height) and it was
        confirmed WRONG by live measurement: a real two-line "<process><br><field>"
        block rendered taller than the chosen min-height (the browser's actual line
        height for this font exceeded the guess), so single-line columns still stayed
        visibly shorter than field columns even with a "matching" min-height set -
        the two-line content simply overflowed past the floor. Forcing every header to
        genuinely contain two rendered lines sidesteps needing to guess a pixel value
        at all: the browser lays out two real lines the same way for every column,
        so their heights come out equal for free. Without this, each column's header
        naturally ends up a different height (since each column is an independently-
        packed VBox), which pushes every OTHER column's body rows out of alignment with
        it - live-verified against a real Voila table both before AND after this fix."""
        widget = self._header_cells.get(key)
        if widget is not None:
            return widget
        width = (
            self._WARNING_COLUMN_WIDTH
            if kind == "warning"
            else self._LABEL_COLUMN_WIDTH
            if kind in ("sample", "subbatch")
            else "180px"
        )
        text = widgets.HTML(
            value=f"<div style='width:{width}; text-align:center;'>{header_html}</div>"
        )
        if spec is None:
            button_or_slot: widgets.Widget = widgets.Label(
                value="", layout=widgets.Layout(height=self._HEADER_BUTTON_HEIGHT)
            )
        else:
            populate_button = widgets.Button(
                icon="arrow-down",
                tooltip="Copy the first row's value into every row below",
                layout=widgets.Layout(
                    width="30px", height=self._HEADER_BUTTON_HEIGHT, margin="2px auto 0 auto"
                ),
            )
            # Not in the Tab cycle - see the class docstring for why.
            populate_button.tabbable = False
            populate_button.on_click(lambda _button, s=spec: self._on_populate_column(s))
            button_or_slot = populate_button
        widget = widgets.VBox([text, button_or_slot], layout=widgets.Layout(align_items="center"))
        self._header_cells[key] = widget
        return widget

    def _label_cell_for(self, key: object, sample_number: int, value: str) -> widgets.Label:
        label = self._label_cells.get((key, sample_number))
        if label is None:
            label = widgets.Label(layout=widgets.Layout(width=self._LABEL_COLUMN_WIDTH))
            self._label_cells[(key, sample_number)] = label
        if label.value != value:
            label.value = value
        return label

    def _row_warning_for(self, sample_number: int) -> widgets.HTML:
        warning = self._row_warnings.get(sample_number)
        if warning is None:
            warning = widgets.HTML(
                value="", layout=widgets.Layout(width=self._WARNING_COLUMN_WIDTH)
            )
            self._row_warnings[sample_number] = warning
        return warning

    def _field_cell_for(
        self, key: object, field_part: str, sample_number: int, value, on_valid
    ) -> widgets.Widget:
        cell = self._field_cells.get((key, sample_number))
        if cell is None:
            cell = _MatrixCell(field_part, self._row_warning_for(sample_number), on_valid)
            self._field_cells[(key, sample_number)] = cell
        cell.sync(value)
        return cell.widget

    def _render(self) -> None:
        varying_fields = iter_varying_fields(self.state)
        sample_numbers = self.state.sample_numbers()

        if not varying_fields or not sample_numbers:
            self._column_boxes = {}
            self._header_cells = {}
            self._label_cells = {}
            self._field_cells = {}
            self._row_warnings = {}
            self._columns_box.children = []
            self.children = [
                widgets.HTML(
                    value="<i>Mark fields as varying, and add samples, to see the matrix.</i>"
                )
            ]
            return

        columns = self._current_columns(varying_fields)
        self._drop_stale(columns, sample_numbers)

        set_by_sample = {s.sample_number: s.variation_group_index for s in self.state.samples}
        variation_spec = self.state.experiment_info_fields.get("Variation")

        column_boxes = []
        for key, kind, spec, header_html, field_part, _address in columns:
            column_widgets = [self._header_for(key, kind, spec, header_html)]

            for sample_number in sample_numbers:
                if kind == "sample":
                    widget = self._label_cell_for(key, sample_number, str(sample_number))
                elif kind == "subbatch":
                    set_index = set_by_sample.get(sample_number)
                    widget = self._label_cell_for(
                        key, sample_number, "" if set_index is None else str(set_index + 1)
                    )
                elif kind == "warning":
                    widget = self._row_warning_for(sample_number)
                elif kind == "field":
                    widget = self._field_cell_for(
                        key,
                        field_part,
                        sample_number,
                        spec.per_sample_values.get(sample_number),
                        lambda new_value, s=spec, sn=sample_number: self._on_cell_change(
                            s, sn, new_value
                        ),
                    )
                else:  # "variation"
                    value = (
                        variation_spec.per_sample_values.get(sample_number)
                        if variation_spec is not None
                        else None
                    )
                    widget = self._field_cell_for(
                        key,
                        field_part,
                        sample_number,
                        value,
                        lambda new_value, sn=sample_number: self._on_variation_cell_change(
                            sn, new_value
                        ),
                    )
                column_widgets.append(widget)

            column_box = self._column_boxes.get(key)
            if column_box is None:
                # flex="0 0 auto": keep this column at its natural (content-driven)
                # width instead of the browser's default flex-shrink squeezing it below
                # that to fit _columns_box - see this class's __init__ for why.
                column_box = widgets.VBox(
                    [], layout=widgets.Layout(align_items="center", flex="0 0 auto")
                )
                self._column_boxes[key] = column_box
            column_box.children = column_widgets
            column_boxes.append(column_box)

        self._columns_box.children = column_boxes
        self.children = [self._columns_box]

    def _on_cell_change(self, spec: ProcessFieldSpec, sample_number: int, new_value) -> None:
        set_field_manual(spec, new_value, sample_number=sample_number)
        self._notify_change()

    def _on_variation_cell_change(self, sample_number: int, new_value) -> None:
        variation_spec = self.state.experiment_info_fields.get("Variation")
        if variation_spec is not None:
            # Variation is always per-sample; force the scope before writing so a manual
            # edit lands in per_sample_values, not the (unused for this field) constant
            # value slot.
            variation_spec.varies = True
            set_field_manual(variation_spec, new_value, sample_number=sample_number)
        self._notify_change()

    def _on_populate_column(self, spec: ProcessFieldSpec) -> None:
        # Looked up live (not a closure-captured list) since the header widget carrying
        # this button is now cached/reused across renders - see the class docstring.
        populate_column_from_first(spec, self.state.sample_numbers())
        self._notify_change()

    # -- Test/debug accessors -------------------------------------------------------
    # White-box helpers for inspecting the currently-rendered table without reaching
    # into _columns_box internals directly - addressed the same way iter_varying_fields
    # labels a column ("Sample"/"Subbatch"/"Variation", or a varying field's full
    # "<process> - <field>" string).

    def columns(self) -> list[str]:
        return [column[5] for column in self._current_columns() if column[5] is not None]

    def header_widget(self, column_label: str) -> widgets.Widget:
        for key, _kind, _spec, _header_html, _field_part, address in self._current_columns():
            if address == column_label:
                return self._header_cells[key]
        raise KeyError(column_label)

    def cell_widget(self, sample_number: int, column_label: str) -> widgets.Widget:
        for key, kind, _spec, _header_html, _field_part, address in self._current_columns():
            if address == column_label:
                if kind in ("sample", "subbatch"):
                    return self._label_cells[(key, sample_number)]
                return self._field_cells[(key, sample_number)].widget
        raise KeyError(column_label)

    def row_warning_widget(self, sample_number: int) -> widgets.HTML:
        return self._row_warnings[sample_number]

    def tab_order(self) -> list[widgets.Widget]:
        """Every widget in this matrix flattened into actual DOM/Tab order - test/debug
        helper mirroring the real column-major traversal (each column's VBox top to
        bottom, left to right across columns)."""
        order: list[widgets.Widget] = []
        for column in self._columns_box.children:
            order.extend(column.children)
        return order


class VariationTemplatePanel(widgets.VBox):
    """Optional custom format for the computed Variation column - e.g.
    'Den=\\1_Sol-\\2_SubTemp=\\3' instead of the automatic field-slug label. '\\N' (1-based)
    refers to the Nth currently-varying column, in the SAME order as the Varying Fields
    matrix's columns (a live '\\1 = ...' legend below the input shows exactly what that
    order is right now, since it shifts as fields are marked varying/un-varying
    elsewhere). Not every varying column has to be referenced by the template, and a
    referenced column left unfilled for a given sample just renders as empty for that
    sample - see data_manager.render_variation_template.

    Deliberately exempt from the forbidden-character guard every other Text input in
    this app uses (_guard_forbidden_characters) - this pattern legitimately needs a
    backslash, it's a control input, not sample/experiment data.

    Needs an explicit refresh() wired into app.py's refresh_all: the \\N legend depends on
    iter_varying_fields(state), which changes in response to OTHER widgets' actions
    (ProcessFieldsPanel/ExperimentInfoPanel's 'varies' checkboxes), not this panel's
    own. Hides itself entirely (same condition VaryingFieldsMatrix uses to show its own
    placeholder) whenever there's no actual matrix table to apply a Variation format
    to.

    Hosts two buttons side by side, color-coded to keep them visually distinct since
    they're easy to conflate: "Apply Formula" (blue/primary) SWITCHES the active format
    (the custom pattern typed above, or automatic if left blank) and refills under it;
    "Automatically fill up Variation" (green/success) just (re)computes under WHATEVER
    format is already active, without changing it - the one to reach for after editing
    varying-field values, since Variation is a plain, directly-editable matrix column now
    and is no longer filled in live as you type (see update_variation_column's
    docstring)."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change

        self.template_input = widgets.Text(
            value=state.variation_template or "",
            placeholder=r"e.g. Den=\1_Sol-\2_SubTemp=\3 - leave blank for the automatic label",
            layout=widgets.Layout(width="420px"),
        )
        self.apply_button = widgets.Button(description="Apply Formula", button_style="primary")
        self.apply_button.on_click(self._on_apply)
        self.autofill_button = widgets.Button(
            description="Automatically fill up Variation", button_style="success"
        )
        self.autofill_button.on_click(self._on_autofill)
        self.status = widgets.HTML(value="")
        self.autofill_status = widgets.HTML(value="")
        self.legend = widgets.HTML(value="")

        caption = widgets.HTML(
            value=(
                "<i style='color:#7f8c8d; font-size:11px;'>Variation is a plain entry "
                "column - it is not filled in automatically as you type. Custom Variation "
                "format (optional): reference a varying column by position with "
                "<code>\\1</code>, <code>\\2</code>, <code>\\3</code>... in the same order "
                "as the legend below - you don't have to use every column, and a "
                "referenced column with no value for a given sample is simply left blank "
                "for that sample, not an error. <b>Apply Formula</b> switches to this "
                "format (or back to the automatic label if left blank) and refills "
                "immediately; <b>Automatically fill up Variation</b> just (re)fills under "
                "whichever format is already active, without changing it - a manually-"
                "typed Variation value is never overwritten by either.</i>"
            )
        )

        super().__init__(
            [
                caption,
                widgets.HBox([self.template_input, self.apply_button, self.autofill_button]),
                self.status,
                self.autofill_status,
                self.legend,
            ]
        )
        self.refresh()

    def _on_autofill(self, _button) -> None:
        written = auto_fill_variation_column(self.state)
        self.autofill_status.value = (
            f"<span style='color:#2c7a4b'>Filled {written} sample(s).</span>"
        )
        self.refresh()
        if self.on_change:
            self.on_change()

    def refresh(self) -> None:
        """Re-renders the \\N legend from the CURRENT varying fields - call whenever
        anything outside this panel changes which fields are marked varying. Hides the
        whole panel (same condition as VaryingFieldsMatrix's own placeholder) when
        there's no varying field, or no sample, for a Variation format to apply to."""
        varying_fields = iter_varying_fields(self.state)
        if not varying_fields or not self.state.sample_numbers():
            self.layout.display = "none"
            return
        self.layout.display = ""
        rows = [
            f"<code>\\{index}</code> = {label}"
            for index, (label, _spec) in enumerate(varying_fields, start=1)
        ]
        self.legend.value = (
            "<span style='color:#7f8c8d; font-size:11px;'>"
            + " &nbsp;|&nbsp; ".join(rows)
            + "</span>"
        )

    def _on_apply(self, _button) -> None:
        apply_variation_template(self.state, self.template_input.value)
        self.status.value = (
            "<span style='color:#2c7a4b'>Applied.</span>"
            if self.state.variation_template
            else "<span style='color:#2c7a4b'>Reverted to the automatic label.</span>"
        )
        self.refresh()
        if self.on_change:
            self.on_change()
