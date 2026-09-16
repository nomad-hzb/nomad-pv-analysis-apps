# gui_components.py
# All ipywidgets code for the ISA Previewer. The four notebooks differ only in the Variant
# they hand to build_ui, so everything below is variant driven rather than duplicated.

import logging

import config
import data_manager
import ipywidgets as widgets
import matplotlib.pyplot as plt
from insitu_analyser.Preview.perfect_previewer import PERFECTPREVIEWER
from insitu_analyser.timely_teller import TIMELYTELLER
from insitu_analyser.utils.search_bar_widget import create_spinner
from IPython.display import display

logger = logging.getLogger(__name__)

OVERFLOW_CSS = """
<style>
/* Only apply horizontal scroll to actual output area */
.output_subarea {
    overflow-x: auto !important;
    width: 100% !important;
}

/* Prevent nested divs from adding more scrollbars */
.jp-OutputArea-output > div,
.output_subarea > div,
.widget-output > div {
    overflow-x: visible !important;
}
</style>
"""
"""The previewer's figures are wider than the page and must scroll sideways on their own.
Returned as part of the widget tree rather than display()ed, because a bare display() from
outside a cell execution is silently dropped under Voila."""


class Session:
    """One opened selection: the object the sections were built from, and those widgets.

    The source is a PERFECTPREVIEWER for a measurement variant and a TIMELYTELLER for an
    upload variant; this class only has to hold it alive and let go of it again.

    Exists so a new selection can tear the previous one down completely. clear_output only
    hides widgets, it neither closes them nor frees the figures behind them, and an ISA h5
    is large enough that leaking one per selection is felt within a session.
    """

    def __init__(self, source, contents: list[widgets.Widget]):
        self.source = source
        self.contents = contents

    def dispose(self) -> None:
        """Close every figure and widget this session owns."""
        # plt.close("all") rather than staticfunctions.close_figs: the previewer does not
        # hand out its figure objects, and by this point every figure alive belongs to the
        # session being dropped.
        plt.close("all")
        for widget in self.contents:
            try:
                widget.close()
            except Exception:
                logger.exception("Failed to close a previewer widget")
        self.contents = []
        self.source = None


def build_ui(url: str, token: str, variant: config.Variant) -> widgets.Widget:
    """Build the whole app: the selector row, the output area, and their wiring."""
    user = data_manager.get_current_user()

    uploads_filter = widgets.Text(description="Filter")
    uploads = widgets.Select(description="Uploads", layout=widgets.Layout(**config.SELECT_LAYOUT))
    samples = widgets.Select(description="Samples", layout=widgets.Layout(**config.SELECT_LAYOUT))
    measurements = widgets.Select(
        description="Measurements", layout=widgets.Layout(**config.SELECT_LAYOUT)
    )
    pixel_width = widgets.IntText(description="Pixel width", value=config.DEFAULT_PIXEL_WIDTH)
    out = widgets.Output()
    spinner = create_spinner()

    all_uploads = data_manager.list_uploads_with_measurements(url, token)
    uploads.options = all_uploads

    upload_only = variant.selection == config.SELECTION_UPLOAD

    session: dict[str, Session | None] = {"current": None}

    def on_filter(_change):
        """Narrow the upload list as the user types. Case insensitive substring match."""
        term = uploads_filter.value.strip().lower()
        uploads.options = [o for o in all_uploads if term in o[0].lower()] if term else all_uploads

    def on_select_upload(_change):
        if upload_only:
            # The upload is the whole selection here, so there is nothing left to narrow down.
            open_selection()
            return
        measurements.options = []
        if not uploads.value:
            samples.options = []
            return
        samples.options = data_manager.list_samples_in_upload(url, token, uploads.value)

    def on_select_sample(_change):
        # An empty list leaves .value at None, and the first option is the "---" placeholder;
        # querying with either cannot succeed, so clear the dependent list instead.
        if not uploads.value or not samples.value:
            measurements.options = []
            return
        measurements.options = data_manager.list_h5_measurements(
            url, token, samples.value, uploads.value
        )

    def on_select_measurement(_change):
        open_selection()

    def on_pixel_width(_change):
        # Rebuild the current selection at the new width. The old notebooks reached this by
        # re-running the sample query so the measurement list was rewritten and its observer
        # fired again; going straight at the file skips two NOMAD requests.
        open_selection()

    def current_target() -> str | None:
        """What the variant opens for the current selection, or None while nothing is picked.

        A path either way: the selected h5 for a measurement variant, the selected upload's
        folder for an upload variant. None also covers an upload that is listed in NOMAD but
        not mounted for this user, which is nothing to open rather than an error.
        """
        if upload_only:
            return data_manager.upload_folder_path(uploads.value) if uploads.value else None
        return measurements.value or None

    def open_selection() -> None:
        target = current_target()
        if target is None:
            return

        out.clear_output()
        with out:
            display(spinner)

        if session["current"] is not None:
            session["current"].dispose()
            session["current"] = None

        source = open_source(target, variant, pixel_width.value)
        contents = build_sections(source, variant)
        # Publish before rendering, so a link opened from the rendered page finds the file.
        handover = handover_row(target, user, pixel_width.value, variant)
        if handover is not None:
            contents.append(handover)

        session["current"] = Session(source, contents)

        out.clear_output()
        with out:
            for widget in contents:
                display(widget)

    uploads_filter.observe(on_filter, names=["value"])
    uploads.observe(on_select_upload, names=["value"])
    pixel_width.observe(on_pixel_width, names=["value"])
    if not upload_only:
        samples.observe(on_select_sample, names=["value"])
        measurements.observe(on_select_measurement, names=["value"])

    if variant.select_from_store:
        preselect_from_store(uploads, samples, measurements, pixel_width)

    # The sample and measurement columns are left out of the tree of an upload variant rather
    # than shown empty: they would suggest a selection that has no effect on what it opens.
    columns = [uploads_filter, uploads]
    if not upload_only:
        columns += [samples, measurements]
    return widgets.VBox([widgets.HTML(OVERFLOW_CSS), widgets.HBox(columns), pixel_width, out])


def preselect_from_store(
    uploads: widgets.Select,
    samples: widgets.Select,
    measurements: widgets.Select,
    pixel_width: widgets.IntText,
) -> None:
    """Open on the file the main previewer handed over, if it handed one over.

    Setting uploads.value cascades through the observers, so samples and measurements fill
    themselves; this only has to pick the right entry at each step. An upload variant is done
    after that first step: its upload is the whole selection. Nothing stored means the
    notebook was opened directly instead of through a link, which is not an error: the app
    then starts on an empty selection like the main previewer does.
    """
    h5_path = data_manager.get_stored_h5_path()
    if not h5_path:
        logger.info("No h5_path in the IPython store; starting on an empty selection")
        return

    screenwidth = data_manager.get_stored_screenwidth()
    if screenwidth:
        pixel_width.value = screenwidth

    upload_id = data_manager.upload_id_from_path(h5_path)
    if upload_id is None:
        return
    if upload_id not in [option[1] for option in uploads.options]:
        logger.warning("Stored file lives in upload %s, which is not selectable", upload_id)
        return
    uploads.value = upload_id
    if not samples.options:
        # Nothing left to narrow down: an upload variant fills no sample column at all, and an
        # upload without samples has no measurement to pick either.
        return

    sample_name = data_manager.sample_name_in_h5(h5_path)
    if sample_name:
        for option in samples.options:
            if data_manager.sample_id_from_option(option) in sample_name:
                samples.value = option
                break

    if h5_path in [option[1] for option in measurements.options]:
        measurements.value = h5_path


def open_source(target: str, variant: config.Variant, screenwidth: int):
    """Open what the variant selects and return the object its sections are built from.

    A measurement variant gets a PERFECTPREVIEWER on the selected h5, an upload variant a
    TIMELYTELLER on the selected upload folder, which scans that folder for h5 files itself.
    """
    if variant.selection == config.SELECTION_UPLOAD:
        return TIMELYTELLER(search_dir=target, screenwidth=screenwidth)
    return PERFECTPREVIEWER(
        target,
        screenwidth=screenwidth,
        initialize_overview=variant.initialize_overview,
    )


def handover_row(
    target: str, user: str, screenwidth: int, variant: config.Variant
) -> widgets.Widget | None:
    """Publish the current file for the linked notebooks and return their link row.

    Only a measurement variant has a single file to hand on: an upload variant opened a whole
    folder, so it neither overwrites the stored selection nor offers links that would be about
    a file it is not showing.
    """
    if variant.selection == config.SELECTION_UPLOAD:
        return None
    data_manager.store_for_linked_notebooks(target, screenwidth)
    return build_link_row(target, user, variant.link_key)


def section_builders(source, variant: config.Variant) -> dict:
    """One builder per section name a variant may list.

    The source is whatever open_source returned for this variant, so a section only appears
    here next to the sections built from the same kind of source.

    Every value is a lambda, so the keys can be read without a source to hand: that is what
    lets a config listing an unknown section be caught up front rather than when someone
    opens a file.
    """
    return {
        "overview": lambda: overview_widgets(source, variant),
        "optical_data": lambda: source.display_optical_data(),
        "logging": lambda: source.display_logging(),
        "cuts": lambda: source.display_cuts(),
        "comparison": lambda: source.display_comparison(),
        "export": lambda: source.display_export(),
        "timely_teller": lambda: source.display(),
    }


SECTION_NAMES = tuple(section_builders(None, None))
"""Every section name config.Variant.sections may contain."""


def build_sections(source, variant: config.Variant) -> list[widgets.Widget]:
    """The widgets this variant shows, in the order config lists them.

    A section that has nothing to show for this h5 returns None and is skipped, so a variant
    never has to know in advance what a given file contains.
    """
    builders = section_builders(source, variant)

    contents: list[widgets.Widget] = []
    for section in variant.sections:
        built = builders[section]()
        if built is None:
            logger.info("Section %s has nothing to show for this file", section)
            continue
        # display_comparison and overview_widgets return several widgets, the rest return one.
        contents.extend(built if isinstance(built, (list, tuple)) else [built])
    return contents


def overview_widgets(previewer: PERFECTPREVIEWER, variant: config.Variant) -> list[widgets.Widget]:
    """The three widgets display_widgets returns, in the order the dashboard stacks them."""
    built = previewer.display_widgets(xrd=variant.xrd, optical=variant.optical)
    return [built["giwaxs_content"], built["ui"], built["optical_content"]]


def build_link_row(h5_path: str, user: str, exclude: str | None = None) -> widgets.Widget | None:
    """The row of "open that other notebook" links this h5 qualifies for.

    exclude is the calling variant's own link key, so a notebook does not link to itself.
    """
    links = data_manager.available_links(h5_path, user, exclude)
    if not links:
        return None
    html = " ".join(
        f'<a href="{url}" target="_blank" style="margin-right:2em">{label}</a>'
        for label, url in links
    )
    return widgets.HTML(f'<div style="font-size:20px; padding-top:1em">{html}</div>')
