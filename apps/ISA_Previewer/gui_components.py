# gui_components.py
# All ipywidgets code for the ISA Previewer. The three notebooks differ only in the Variant
# they hand to build_ui, so everything below is variant driven rather than duplicated.

import logging

import config
import data_manager
import ipywidgets as widgets
import matplotlib.pyplot as plt
from insitu_analyser.Preview.perfect_previewer import PERFECTPREVIEWER
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


class PreviewerSession:
    """One opened h5 file: the PERFECTPREVIEWER and the widgets built from it.

    Exists so a new selection can tear the previous one down completely. clear_output only
    hides widgets, it neither closes them nor frees the figures behind them, and an ISA h5
    is large enough that leaking one per selection is felt within a session.
    """

    def __init__(self, previewer: PERFECTPREVIEWER, contents: list[widgets.Widget]):
        self.previewer = previewer
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
        self.previewer = None


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

    session: dict[str, PreviewerSession | None] = {"current": None}

    def on_filter(_change):
        """Narrow the upload list as the user types. Case insensitive substring match."""
        term = uploads_filter.value.strip().lower()
        uploads.options = [o for o in all_uploads if term in o[0].lower()] if term else all_uploads

    def on_select_upload(_change):
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
        if not measurements.value:
            return
        open_file(measurements.value)

    def on_pixel_width(_change):
        # Rebuild the current file at the new width. The old notebooks reached this by
        # re-running the sample query so the measurement list was rewritten and its observer
        # fired again; going straight at the file skips two NOMAD requests.
        if measurements.value:
            open_file(measurements.value)

    def open_file(h5_path: str) -> None:
        out.clear_output()
        with out:
            display(spinner)

        if session["current"] is not None:
            session["current"].dispose()
            session["current"] = None

        previewer = PERFECTPREVIEWER(
            h5_path,
            screenwidth=pixel_width.value,
            initialize_overview=variant.initialize_overview,
        )
        contents = build_sections(previewer, variant)
        # Publish before rendering, so a link opened from the rendered page finds the file.
        data_manager.store_for_linked_notebooks(h5_path, pixel_width.value)
        link_row = build_link_row(h5_path, user)
        if link_row is not None:
            contents.append(link_row)

        session["current"] = PreviewerSession(previewer, contents)

        out.clear_output()
        with out:
            for widget in contents:
                display(widget)

    uploads_filter.observe(on_filter, names=["value"])
    uploads.observe(on_select_upload, names=["value"])
    samples.observe(on_select_sample, names=["value"])
    measurements.observe(on_select_measurement, names=["value"])
    pixel_width.observe(on_pixel_width, names=["value"])

    if variant.select_from_store:
        preselect_from_store(uploads, samples, measurements, pixel_width)

    selectors = widgets.HBox([uploads_filter, uploads, samples, measurements])
    return widgets.VBox([widgets.HTML(OVERFLOW_CSS), selectors, pixel_width, out])


def preselect_from_store(
    uploads: widgets.Select,
    samples: widgets.Select,
    measurements: widgets.Select,
    pixel_width: widgets.IntText,
) -> None:
    """Open on the file the main previewer handed over, if it handed one over.

    Setting uploads.value cascades through the observers, so samples and measurements fill
    themselves; this only has to pick the right entry at each step. Nothing stored means the
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

    sample_name = data_manager.sample_name_in_h5(h5_path)
    if sample_name:
        for option in samples.options:
            if data_manager.sample_id_from_option(option) in sample_name:
                samples.value = option
                break

    if h5_path in [option[1] for option in measurements.options]:
        measurements.value = h5_path


def section_builders(previewer: PERFECTPREVIEWER, variant: config.Variant) -> dict:
    """One builder per section name a variant may list.

    Every value is a lambda, so the keys can be read without a previewer to hand: that is
    what lets a config listing an unknown section be caught up front rather than when
    someone opens a file.
    """
    return {
        "overview": lambda: overview_widgets(previewer, variant),
        "optical_data": lambda: previewer.display_optical_data(),
        "logging": lambda: previewer.display_logging(),
        "cuts": lambda: previewer.display_cuts(),
        "comparison": lambda: previewer.display_comparison(),
        "export": lambda: previewer.display_export(),
    }


SECTION_NAMES = tuple(section_builders(None, None))
"""Every section name config.Variant.sections may contain."""


def build_sections(previewer: PERFECTPREVIEWER, variant: config.Variant) -> list[widgets.Widget]:
    """The widgets this variant shows, in the order config lists them.

    A section that has nothing to show for this h5 returns None and is skipped, so a variant
    never has to know in advance what a given file contains.
    """
    builders = section_builders(previewer, variant)

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


def build_link_row(h5_path: str, user: str) -> widgets.Widget | None:
    """The row of "open that other notebook" links this h5 qualifies for."""
    links = data_manager.available_links(h5_path, user)
    if not links:
        return None
    html = " ".join(
        f'<a href="{url}" target="_blank" style="margin-right:2em">{label}</a>'
        for label, url in links
    )
    return widgets.HTML(f'<div style="font-size:20px; padding-top:1em">{html}</div>')
