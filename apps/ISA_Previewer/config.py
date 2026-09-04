# config.py
# Every value the ISA Previewer used to carry inline, in one place.
#
# The three notebooks in this folder are one codebase run three ways. They differ only in
# the VARIANT they pass to app.initialize_ui(), so a section moves between notebooks by
# editing a tuple here, never by copying notebook cells.
#
# Values that would only restate an insitu_analyser default are deliberately absent: the
# slider width (PREVIEWER_CONFIG["slider_width"]) and the sample entry type
# (get_samples_in_upload's own default) are left unpassed so the library value applies, and
# there is one definition of each rather than two that can drift apart.

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# NOMAD schema entry types
# ---------------------------------------------------------------------------
# The entry type ISA writes one archive JSON per h5 measurement as
# (see isa_inducer.upload_h5_json). The sample entry type is not repeated here: it is
# get_samples_in_upload's default.
MEASUREMENT_ENTRY_TYPE = "HySprint_Process"

# ISA uploads carry no HySprint_Batch entry, which is why this app selects by upload name
# rather than by batch: a batch query returns nothing for exactly the uploads it is for.

# ---------------------------------------------------------------------------
# Selector behaviour
# ---------------------------------------------------------------------------
H5_SUFFIX = ".h5"
"""Only data_file entries ending in this become selectable measurements."""

PLACEHOLDER_OPTION = "---"
"""First entry of the sample list, meaning "nothing selected". Selecting it clears the
measurement list instead of firing a query that cannot succeed. The string mirrors what
get_sample_description prepends; it is here because this app has to recognise it, not
because it configures it."""

DEFAULT_PIXEL_WIDTH = 1680
"""Starting value of the editable screen width in px, which drives every figure's size.
insitu_analyser treats screenwidth=None as "decide for me", but this app shows the number
in a field the user can change, so it needs a concrete starting point."""

SELECT_LAYOUT = {"width": "800px", "height": "80px"}
"""Layout of each of the three Select columns (uploads, samples, measurements)."""


# ---------------------------------------------------------------------------
# Links to sibling apps
# ---------------------------------------------------------------------------
VOILA_PATH_TEMPLATE = "/nomad-oasis/north/user/{user}/voila/voila/render"
"""Same NORTH tool App_dashboard renders its cards through. Links are built from the
current working directory plus the sibling app's folder, so no Oasis specific upload id is
hardcoded anywhere. This is deliberately NOT how insitu_analyser's own
PERFECTPREVIEWER.link_* methods work: those keep their hardcoded per Oasis paths so the
per upload notebooks already deployed on CE-AME go on working untouched."""


@dataclass(frozen=True)
class AppLink:
    """One "open that other notebook" link shown under the previewer."""

    label: str
    folder: str
    """App folder under apps/. Empty string means a notebook in this app's own folder."""
    notebook: str
    upload_id: str | None = None
    """Set only for a target living in a different NOMAD upload than this app. All current
    targets are siblings in this repo, so all of them leave it None."""
    requires_h5_dataset: str | None = None
    """When set, the link appears only if the opened h5 contains this dataset. Every variant
    offers every link, so this is what keeps a link off a file it could not open anyway."""


APP_LINKS = {
    "optical_analysis": AppLink(
        label="Open Optical Analysis",
        folder="",
        notebook="optical_analysis.ipynb",
        # OPTICALANALYSER reads this group; without it the notebook has nothing to show.
        requires_h5_dataset="raw_optical_measurements",
    ),
    "giwaxs_analysis": AppLink(
        label="Open GIWAXS Analysis",
        folder="",
        notebook="giwaxs_analysis.ipynb",
        # Cuts and comparison both need the detector images, and the geometry is what makes
        # them readable. Same single test PERFECTPREVIEWER.has_2d_data uses, so an h5 whose
        # diffractograms were reduced elsewhere (the KMC2 XRD import) offers no link.
        requires_h5_dataset="diffractogram/initial_params",
    ),
    "thickness": AppLink(
        label="Open Thickness Tracer",
        folder="Thickness_tracer",
        notebook="thickness_tracer.ipynb",
        # Thickness modelling needs reflectance; same check link_thickness makes today.
        requires_h5_dataset=(
            "raw_optical_measurements/raw_reflectance_measurements/raw_reflectance_data"
        ),
    ),
    "peak_analyzer": AppLink(
        label="Open Peak Analyzer",
        folder="Peak_Explorer",
        notebook="peak_analyzer.ipynb",
        # Ungated, as it is today: the peak analyzer opens any h5 the previewer can open.
    ),
}

LINK_ORDER = ("optical_analysis", "giwaxs_analysis", "thickness", "peak_analyzer")
"""Order the links are rendered in. Every variant offers all of them, so which links a
given notebook shows is decided by the h5 in front of it, not by which notebook it is."""


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------
# Section keys map to one PERFECTPREVIEWER call each:
#   overview      display_widgets(xrd=..., optical=...)  the slider row, heatmaps and 1D plots
#   optical_data  display_optical_data()
#   logging       display_logging()
#   cuts          display_cuts()
#   comparison    display_comparison()                   returns two widgets
#   export        display_export()


@dataclass(frozen=True)
class Variant:
    """One notebook's worth of behaviour."""

    title: str
    """Browser tab title."""
    sections: tuple[str, ...]
    initialize_overview: bool = True
    """PERFECTPREVIEWER(initialize_overview=...). False skips building the heatmaps and the
    reshaped image, which the two analysis variants do not show and which dominate load
    time."""
    xrd: bool = True
    optical: bool = False
    """Only read for the "overview" section: display_widgets(xrd=..., optical=...)."""
    select_from_store: bool = False
    """True for the variants reachable from a main previewer link: if a file was handed over
    through the IPython store, open on it instead of on an empty selection.

    It is a head start, never a requirement. Every variant builds the full upload, sample and
    measurement selectors, so all three notebooks work standalone when opened from the app
    dashboard; a linked one just arrives with the selection already made."""


VARIANTS = {
    "main": Variant(
        title="ISA Previewer",
        sections=("overview", "logging", "export"),
        initialize_overview=True,
        xrd=True,
        optical=True,
    ),
    "giwaxs": Variant(
        title="ISA GIWAXS Analysis",
        sections=("cuts", "comparison"),
        initialize_overview=False,
        select_from_store=True,
    ),
    "optical": Variant(
        title="ISA Optical Analysis",
        sections=("optical_data",),
        initialize_overview=False,
        select_from_store=True,
    ),
}
