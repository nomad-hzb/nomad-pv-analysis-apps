"""Interactive parameter tuner (dev tool, not part of the Voila app).

    streamlit run tuner.py --server.address localhost -- <images> [<annotations> [<log dir>]]

The optional annotations folder holds ImageJ/Fiji point annotations (`<image>_Results.csv`
or `<image>_points.csv`); when one exists for the selected image, the clicks can be drawn
and the current settings are scored against them live. Pass "" to skip it but still set
a log dir.

Grains can be merged and split by clicking (needs streamlit-image-coordinates). "Save as
reviewed" writes the final grain map, the edits and the settings to the training log
(default ~/sem_grain_training_log, see training_log.py).

Opening an image loads the preset the automatic choice picks for it. Each stage is cached on
the parameters it depends on, so moving a merge slider does not redo denoising.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import grain_core as gc
import numpy as np
import pandas as pd
import streamlit as st
import training_log
from evaluate import annotation_stem, read_points, score

try:  # click-to-edit needs this small component; the rest of the tuner works without it
    from streamlit_image_coordinates import streamlit_image_coordinates as image_coordinates
except ImportError:
    image_coordinates = None

st.set_page_config(page_title="Grain tuner", layout="wide")

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
ann_folder = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
log_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path.home() / "sem_grain_training_log"
files = sorted(p.name for p in folder.glob("*.tif"))
CORE_VERSION = hashlib.sha256(Path(gc.__file__).read_bytes()).hexdigest()[:12]
"""Part of every disk-cache key: any change to grain_core invalidates the cached results."""

# Slider definitions: (field, label, min, max, step, help). The help text says what the
# parameter does and which symptom each direction fixes.
SLIDERS = {
    "Preprocess": [
        (
            "background_sigma_nm",
            "Background flattening (nm)",
            0.0,
            3000.0,
            100.0,
            "Removes slow brightness changes across the image (charging, shading) by "
            "subtracting a heavily blurred copy. Must be much larger than a grain. "
            "0 switches it off. Rarely needs changing.",
        ),
        (
            "denoise_strength",
            "Denoise strength",
            0.2,
            2.0,
            0.1,
            "How hard the non-local-means filter smooths the noise. Higher: fewer specks "
            "detected as boundaries, but faint boundaries can vanish. Lower: keeps faint "
            "boundaries, more noise.",
        ),
    ],
    "Boundary map": [
        (
            "clip_bright_percentile",
            "Clip bright rims (percentile)",
            50.0,
            100.0,
            1.0,
            "Flattens the brightest pixels (the bright edge rims next to grain boundaries) "
            "before boundaries are searched, so a rim is not mistaken for two boundaries. "
            "Lower: clips more. 100 = off. Lower it if bright rims get split into thin slivers.",
        ),
        (
            "ridge_weight",
            "Ridge vs edge weight",
            0.0,
            1.0,
            0.05,
            "1 = boundaries are found only as dark grooves (recommended). Lower values mix in "
            "brightness edges, which also fire on both sides of bright rims.",
        ),
    ],
    "Seeds (one per grain, ideally)": [
        (
            "boundary_threshold",
            "Boundary threshold (x Otsu)",
            0.3,
            2.0,
            0.05,
            "Which pixels count as boundary when placing seeds. Lower: more pixels are "
            "boundary, grain interiors shrink, fewer seeds. Higher: weak lines are ignored, "
            "more seeds.",
        ),
        (
            "min_grain_diameter_nm",
            "Smallest grain diameter (nm)",
            10.0,
            600.0,
            10.0,
            "The most important slider. Seeds are kept at least about this far apart. "
            "Too many small pieces inside grains: RAISE it. Neighbouring grains glued "
            "together: LOWER it. Smooth films work around 100 nm, striped around 300 nm.",
        ),
    ],
    "Merging (removes false boundaries)": [
        (
            "merge_threshold",
            "Merge threshold (x median boundary)",
            0.0,
            2.0,
            0.05,
            "Two neighbouring regions are joined when the line between them is weaker than "
            "this times the image's typical boundary strength. Higher: merges more (fixes "
            "grains cut by terraces or stripes). Lower: keeps more splits.",
        ),
        (
            "merge_sigma_nm",
            "Merge line width (nm)",
            2.0,
            40.0,
            1.0,
            "Width of the dark line the merge step looks for. Larger: only wide, deep "
            "grooves count as real boundaries, so fine stripes inside grains get merged away.",
        ),
        (
            "min_grain_area_nm2",
            "Minimum grain area (nm²)",
            0.0,
            20000.0,
            250.0,
            "Regions smaller than this are merged into their neighbour. Raise it to get rid "
            "of tiny slivers along boundaries.",
        ),
    ],
}
RIDGE_HELP = (
    "Widths (nm) of the dark grooves searched for, comma separated. 8 fits thin boundaries; "
    "adding 24 also catches wide grooves, which helps on striped films."
)
GROUP_EXTRAS = {"Boundary map": ["ridge_sigmas_nm"]}  # non-slider widgets shown with a group
MAIN_FIELDS = ("min_grain_diameter_nm", "merge_threshold", "boundary_threshold")
"""Shown open in the sidebar; everything else sits in the collapsed Advanced section. Chosen
by a one-at-a-time sensitivity study on the annotated images (2026-10-15): these three moved
F1 the most in both directions; the others changed it by about 0.05 or less."""
PRESET_OPTIONS = ["auto", *sorted(gc.PRESETS)]


@st.cache_data
def load(name: str) -> gc.SemImage:
    return gc.load_sem_tiff(folder / name)


def file_stamp(name: str) -> tuple:
    """Size and modification time: part of every disk-cache key, so a changed file is redone."""
    stat = (folder / name).stat()
    return stat.st_size, stat.st_mtime_ns


def auto_choice(name: str) -> tuple[str, float]:
    return _auto_choice_cached(name, file_stamp(name), CORE_VERSION)


def final_result(name: str, params_json: str, edits_json: str):
    return _final_cached(name, file_stamp(name), CORE_VERSION, params_json, edits_json)


@st.cache_data(max_entries=64, show_spinner=False)
def clicked_result(name: str, params_json: str, clicks_json: str):
    """Grains grown from the user's clicks (kind 0 = grain, 2 = hole) on the current
    boundary map."""
    _, auto, _ = final_result(name, params_json, "[]")
    clicks = json.loads(clicks_json)
    grains = [(y, x) for y, x, kind in clicks if kind != HOLE]
    holes = [(y, x) for y, x, kind in clicks if kind == HOLE]
    return gc.result_from_points(auto, grains, holes)


@st.cache_data(persist="disk", show_spinner="Choosing a preset for this image (runs both once)...")
def _auto_choice_cached(name: str, stamp: tuple, core_version: str) -> tuple[str, float]:
    # Same decision as gc.analyze_auto, but through the stage caches: only grain counts are
    # needed, and the chosen preset's segmentation is then already cached for display.
    counts = {}
    for preset_name, p in gc.PRESETS.items():
        counts[preset_name] = int(segment(name, p)[2].max())  # labels are 1..N, no gaps
    return gc.choose_preset(counts["smooth"], counts["striped"])


def segment(name: str, p: gc.Params):
    """Cached stages for one image and parameter set: (seeds, raw labels, merged labels)."""
    px = load(name).pixel_size_nm
    pre = stage_pre(name, p.background_sigma_nm, p.denoise_strength)
    bmap = stage_bmap(pre, px, tuple(p.ridge_sigmas_nm), p.clip_bright_percentile, p.ridge_weight)
    return stage_segment(pre, bmap, px, p.model_dump_json())


@st.cache_data(persist="disk", max_entries=200, show_spinner=False)
def _final_cached(name: str, stamp: tuple, core_version: str, params_json: str, edits_json: str):
    """Segmentation, measurement and replayed edits for one image, cached per settings and
    edit list, so clicking or moving one slider does not redo everything."""
    params = gc.Params.model_validate_json(params_json)
    sem = load(name)
    px = sem.pixel_size_nm
    pre = stage_pre(name, params.background_sigma_nm, params.denoise_strength)
    bmap = stage_bmap(
        pre, px, tuple(params.ridge_sigmas_nm), params.clip_bright_percentile, params.ridge_weight
    )
    seeds, raw, labels = stage_segment(pre, bmap, px, params_json)
    grains = gc.measure_grains(labels, px)
    auto_summary = gc.summarize(grains, labels, px, gc.intercept_grain_size(bmap, px, params))
    auto_result = gc.Result(sem, params, pre, bmap, seeds, raw, labels, grains, auto_summary)
    result, warnings = gc.apply_edits(auto_result, json.loads(edits_json))
    return auto_summary, result, warnings


_s, _t = gc.PRESETS["smooth"], gc.PRESETS["striped"]
assert (_s.background_sigma_nm, _s.denoise_strength) == (
    _t.background_sigma_nm,
    _t.denoise_strength,
)


@st.cache_data(persist="disk", show_spinner="Denoising (cached on disk after the first time)...")
def _pre_cached(path: str, file_stamp: tuple, core_version: str, bg: float, strength: float):
    sem = gc.load_sem_tiff(path)
    p = gc.Params(background_sigma_nm=bg, denoise_strength=strength)
    return gc.preprocess(sem.image, sem.pixel_size_nm, p)


def stage_pre(name: str, bg: float, strength: float) -> np.ndarray:
    """Preprocessed image (the slowest stage, 2-7 s), cached on disk across tuner restarts.
    The key includes the file's size and modification time and the core's source hash."""
    return _pre_cached(str(folder / name), file_stamp(name), CORE_VERSION, bg, strength)


@st.cache_data
def stage_bmap(pre: np.ndarray, px: float, sigmas: tuple, clip: float, weight: float) -> np.ndarray:
    p = gc.Params(ridge_sigmas_nm=list(sigmas), clip_bright_percentile=clip, ridge_weight=weight)
    return gc.boundary_map(pre, px, p)


@st.cache_data
def stage_segment(pre: np.ndarray, bmap: np.ndarray, px: float, params_json: str):
    p = gc.Params.model_validate_json(params_json)
    seeds = gc.find_seeds(bmap, px, p)
    raw = gc.watershed(bmap, seeds, p)
    labels = gc.merge_regions(raw, pre, px, p)
    return seeds, raw, labels


def find_annotation(name: str) -> Path | None:
    if ann_folder is None:
        return None
    stem = Path(name).stem.lower()
    for path in ann_folder.glob("*.csv"):
        found = annotation_stem(path.name)
        if found is not None and found.lower() == stem:
            return path
    return None


def apply_params(params: gc.Params) -> None:
    """Write a parameter set into the widgets' session state (used by buttons and loading)."""
    values = params.model_dump()
    for group in SLIDERS.values():
        for field, *_ in group:
            st.session_state[f"p_{field}"] = float(values[field])
    st.session_state["p_ridge_sigmas_nm"] = ", ".join(f"{v:g}" for v in values["ridge_sigmas_nm"])


def effective_preset(name: str, choice: str) -> str:
    return auto_choice(name)[0] if choice == "auto" else choice


def reset_to_preset() -> None:
    preset = effective_preset(st.session_state["image"], st.session_state["preset_choice"])
    apply_params(gc.PRESETS[preset])


def auto_button() -> None:
    st.session_state["preset_choice"] = "auto"
    reset_to_preset()


def load_uploaded_params() -> None:
    uploaded = st.session_state.get("params_upload")
    if uploaded is not None:
        apply_params(gc.Params.model_validate_json(uploaded.getvalue()))


if not files:
    st.error(f"No .tif files in {folder}")
    st.stop()

with st.sidebar:
    st.header("Image")
    name = st.selectbox("File", files, key="image")
    choice = st.selectbox(
        "Preset",
        PRESET_OPTIONS,
        key="preset_choice",
        help="'auto' picks smooth or striped for this image by itself (recommended). "
        "smooth: plain grains (VP317, VP352). striped: grains with terraces inside "
        "(VP401, VP411, VP412).",
    )
    preset = effective_preset(name, choice)
    if st.session_state.get("loaded_for") != (name, choice):
        apply_params(gc.PRESETS[preset])  # new image or preset: start from the right values
        st.session_state["loaded_for"] = (name, choice)
    if choice == "auto":
        st.caption(
            f"Auto chose **{preset}** (count ratio {auto_choice(name)[1]:.1f}; >3 = striped)"
        )

    left, right = st.columns(2)
    left.button(
        "Auto",
        on_click=auto_button,
        help="Pick the preset for this image automatically and load its tuned values.",
        width="stretch",
    )
    right.button(
        "Reset",
        on_click=reset_to_preset,
        help="Undo all slider changes: back to the values of the current preset.",
        width="stretch",
    )
    st.file_uploader(
        "Load params JSON", type="json", key="params_upload", on_change=load_uploaded_params
    )

    with st.expander("Which slider do I need?"):
        st.markdown(
            "- **Many small pieces inside grains** (over-splitting): raise *Smallest grain "
            "diameter*, then *Merge threshold*.\n"
            "- **Several grains inside one outline** (under-splitting): lower *Smallest "
            "grain diameter*, then *Merge threshold*.\n"
            "- **Thin slivers along bright rims**: lower *Clip bright rims*, raise *Minimum "
            "grain area*.\n"
            "- **Faint boundaries missed**: lower *Denoise strength* or *Merge threshold*.\n"
            "- Lost? Press **Reset**."
        )

    slider_specs = {spec[0]: spec for group in SLIDERS.values() for spec in group}

    def render(field: str) -> None:
        if field == "ridge_sigmas_nm":
            st.text_input("Groove widths (nm)", key="p_ridge_sigmas_nm", help=RIDGE_HELP)
        else:
            _, label, lo, hi, step, help_text = slider_specs[field]
            st.slider(label, lo, hi, step=step, key=f"p_{field}", help=help_text)

    st.header("Main settings")
    for field in MAIN_FIELDS:
        render(field)
    with st.expander("Advanced settings", expanded=False):
        st.caption(
            "These barely changed the result on the annotated images; the preset values "
            "are fine for normal use."
        )
        for group, sliders in SLIDERS.items():
            fields = GROUP_EXTRAS.get(group, []) + [spec[0] for spec in sliders]
            fields = [f for f in fields if f not in MAIN_FIELDS]
            if fields:
                st.markdown(f"**{group}**")
                for field in fields:
                    render(field)

try:
    sigmas = tuple(float(v) for v in st.session_state["p_ridge_sigmas_nm"].split(",") if v.strip())
except ValueError:
    st.sidebar.error("Groove widths must be numbers separated by commas")
    st.stop()
params = gc.Params(
    **{field: st.session_state[f"p_{field}"] for group in SLIDERS.values() for field, *_ in group},
    ridge_sigmas_nm=list(sigmas) or [8.0],
)

sem = load(name)
if sem.pixel_size_nm is None:
    st.error(f"{name} has no 'Image Pixel Size' in its metadata; sizes in nm are impossible.")
    st.stop()
px = sem.pixel_size_nm
# Manual edits are replayed on top of the automatic result, so they survive slider changes;
# edits that no longer apply are reported, not silently dropped.
edits = st.session_state.setdefault("edits", {}).setdefault(name, [])
with st.spinner("Segmenting..."):
    auto_summary, result, edit_warnings = final_result(
        name, params.model_dump_json(), json.dumps(edits)
    )
result.summary.update(
    {"preset": preset, "preset_ratio": auto_choice(name)[1] if choice == "auto" else None}
)
SOURCES = ["automatic detection", "my clicks (one per grain)"]
HOLE = 2  # same number as the ImageJ counter for holes
source = st.session_state.get("grain_source", SOURCES[0])
clicks = st.session_state.setdefault("clicks", {}).setdefault(name, [])
by_clicks = source == SOURCES[1]
if by_clicks:
    # Your clicks decide what a grain is; the program only finds the borders.
    result = clicked_result(name, params.model_dump_json(), json.dumps(clicks))
    edit_warnings = []
grains, summary, labels = result.grains, result.summary, result.labels
pre, bmap, seeds, raw = result.pre, result.bmap, result.seeds, result.raw_labels

ann_path = find_annotation(name)
points = read_points(ann_path, sem.image.shape, sem.image.shape[1]) if ann_path else None

st.title(name)
no_clicks_yet = by_clicks and not any(kind != HOLE for _, _, kind in clicks)
if no_clicks_yet:
    st.info(
        "No grain clicks yet. Under 'Overlay and editing', click the centre of every grain, "
        "or start from the automatic grain centres or your ImageJ clicks."
    )
if not no_clicks_yet:
    cols = st.columns(5)
    cols[0].metric("Pixel size", f"{px:.3f} nm")
    cols[1].metric("Grains (at edge)", f"{summary['n_grains']} ({summary.get('n_edge', 0)})")
    cols[2].metric(
        "Mean area", f"{summary.get('mean_area_planimetric_nm2', float('nan')) / 1e3:.1f}e3 nm²"
    )
    cols[3].metric(
        "Mean eq. diameter", f"{summary.get('mean_eq_diameter_nm', float('nan')):.0f} nm"
    )
    cols[4].metric(
        "Your clicks" if by_clicks else "Manual edits",
        sum(kind != HOLE for _, _, kind in clicks) if by_clicks else len(edits),
        help=f"Automatic result: {auto_summary['n_grains']} grains. Kept per image.",
    )
if not no_clicks_yet and not summary.get("reliable", True):
    st.warning(
        f"Only about {summary['n_planimetric']:.0f} grains in this image: too few for a reliable "
        "mean. Use a lower magnification for grain statistics."
    )
for warning in edit_warnings:
    st.warning(f"Edit skipped: {warning}")

if points is not None and not no_clicks_yet:
    m = score(labels, points, px)
    st.subheader("Score against your clicks")
    sc = st.columns(4)
    sc[0].metric(
        "Grains: found / clicked",
        f"{m['n_pred']} / {m['n_true']}",
        help="Your clicks include grains you marked unsure.",
    )
    sc[1].metric(
        "F1 (higher is better)",
        f"{m['f1']:.2f}",
        help="1.0 = every grain has exactly one click and every click its own grain. "
        "Drops for both over- and under-splitting.",
    )
    sc[2].metric(
        "Mean area error",
        f"{m['area_error']:+.0%}",
        help="Negative: grains too small (over-split). Positive: too large (merged).",
    )
    sc[3].metric(
        "Split / merged regions",
        f"{m['split_rate']:.0%} / {m['merge_rate']:.0%}",
        help="Split: regions without any click (a grain cut in pieces). "
        "Merged: regions holding 2+ clicks (grains glued together).",
    )
elif ann_folder is not None:
    st.caption(f"No annotation file for {name} in {ann_folder}")


def undo_edit() -> None:
    if st.session_state["edits"].get(name):
        st.session_state["edits"][name].pop()


def clear_edits() -> None:
    st.session_state["edits"][name] = []
    st.session_state.setdefault("pending_merge", {}).pop(name, None)


def load_saved_edits(saved: list[dict]) -> None:
    st.session_state["edits"][name] = [dict(e) for e in saved]


def set_clicks(new_clicks: list) -> None:
    """Store clicks as (y, x, kind); plain (y, x) pairs are grains."""
    st.session_state["clicks"][name] = [
        (float(c[0]), float(c[1]), int(c[2]) if len(c) > 2 else 0) for c in new_clicks
    ]


def clicks_from_table(table) -> list:
    """ImageJ-style points (read_points) -> clicks: grains and unsure grains, plus holes."""
    return [
        (y, x, HOLE if hole else 0) for y, x, hole in zip(table["y"], table["x"], table["hole"])
    ]


def undo_click() -> None:
    if st.session_state["clicks"].get(name):
        st.session_state["clicks"][name].pop()


def automatic_centres() -> list:
    _, auto, _ = final_result(name, params.model_dump_json(), "[]")
    return gc.grain_centres(auto)


tab_overlay, tab_stages, tab_hist, tab_table = st.tabs(
    ["Overlay and editing", "Stages", "Histograms", "Grains"]
)
with tab_overlay:
    toggles = st.columns(3)
    show_outlines = toggles[0].toggle("Grain outlines", value=True)
    show_seeds = toggles[1].toggle("Seeds (red)")
    show_clicks = toggles[2].toggle(
        "My ImageJ clicks (cyan, unsure yellow)",
        value=points is not None and not by_clicks,
        disabled=points is None,
    )
    st.radio(
        "Grains come from",
        SOURCES,
        horizontal=True,
        key="grain_source",
        help="Automatic: the program finds the grains; fix mistakes by merging or splitting. "
        "My clicks: click the centre of every grain, the program finds the borders. Use this "
        "when the automatic result is not good enough. You can start from the automatic "
        "centres and only add missing grains or remove wrong ones.",
    )
    if by_clicks:
        mode = "add or remove grains"
        kind = st.radio(
            "A click on the image adds a",
            ["grain", "hole"],
            horizontal=True,
            key="click_kind",
            help="Hole: a pinhole or void, not a crystal. Its area is left out of the grain "
            "statistics and reported as hole area fraction.",
        )
        st.caption(
            "Click a grain centre to add a grain (blue dot). Click on a blue dot to remove it. "
            "Every grain needs a dot: a grain without one is absorbed by its neighbours."
        )
        starts = st.columns(2)
        starts[0].button(
            "Start from the automatic grain centres",
            on_click=lambda: set_clicks(automatic_centres()),
            help="Fills in one dot per automatically found grain; then only fix what is wrong.",
        )
        starts[1].button(
            "Load my ImageJ clicks",
            on_click=lambda: set_clicks(clicks_from_table(points)),
            disabled=points is None,
            help="Uses your annotation for this image: grains and unsure grains become grain "
            "clicks, counter-2 points become holes.",
        )
    else:
        mode = st.radio(
            "Clicking on the image will",
            ["do nothing", "merge two grains", "split a grain"],
            horizontal=True,
            key="click_mode",
            help="Merge: click two neighbouring grains (removes the boundary between them). "
            "Split: click inside a grain where a second grain should be; the new boundary "
            "follows the darkest groove between your click and the far side of the grain.",
        )
    pending = st.session_state.setdefault("pending_merge", {}).get(name)
    if mode != "merge two grains" and pending is not None:
        st.session_state["pending_merge"].pop(name)
        pending = None

    image = gc.overlay(result, show_seeds=show_seeds, show_outlines=show_outlines)
    if show_clicks and points is not None:
        sure = points[~points["unsure"]]
        unsure = points[points["unsure"]]
        gc.draw_dots(image, sure["y"].round(), sure["x"].round(), (0, 220, 255), radius=3)
        gc.draw_dots(image, unsure["y"].round(), unsure["x"].round(), (255, 220, 0), radius=3)
    if by_clicks and clicks:
        for wanted, color in ((0, (40, 110, 255)), (HOLE, (255, 40, 40))):
            dots = [c for c in clicks if (c[2] == HOLE) == (wanted == HOLE)]
            gc.draw_dots(image, [c[0] for c in dots], [c[1] for c in dots], color, 3)
    if pending is not None:
        gc.draw_dots(image, [pending[0]], [pending[1]], (255, 0, 255), radius=5)
        st.info("First grain selected (magenta). Now click the grain to merge it with.")

    if mode == "do nothing" or image_coordinates is None:
        if mode != "do nothing":
            st.error("Click editing needs: pip install streamlit-image-coordinates")
        st.image(image, width="stretch")
    else:
        click = image_coordinates(image, key=f"click_{name}", width="stretch", cursor="crosshair")
        if click and click != st.session_state.get("last_click"):
            st.session_state["last_click"] = click
            scale = sem.image.shape[1] / click.get("width", sem.image.shape[1])
            y = min(int(click["y"] * scale), sem.image.shape[0] - 1)
            x = min(int(click["x"] * scale), sem.image.shape[1] - 1)
            if mode == "add or remove grains":
                near = [
                    i for i, (cy, cx, _) in enumerate(clicks) if (cy - y) ** 2 + (cx - x) ** 2 <= 49
                ]
                if near:  # clicked on an existing dot: remove it
                    clicks.pop(near[-1])
                else:
                    clicks.append((float(y), float(x), HOLE if kind == "hole" else 0))
            elif mode == "split a grain":
                edits.append({"op": "split", "point": [y, x]})
            elif pending is None:
                st.session_state["pending_merge"][name] = (y, x)
            else:
                edits.append({"op": "merge", "points": [list(pending), [y, x]]})
                st.session_state["pending_merge"].pop(name)
            st.rerun()
    st.caption(
        "Green: grains counted. Orange: grains cut by the image edge (counted as half). "
        "Magenta: first grain of a merge. Blue: your grain clicks. Red: holes."
    )

    buttons = st.columns(3)
    if by_clicks:
        buttons[0].button("Undo last click", on_click=undo_click, disabled=not clicks)
        buttons[1].button("Clear all clicks", on_click=set_clicks, args=([],), disabled=not clicks)
    else:
        buttons[0].button("Undo last edit", on_click=undo_edit, disabled=not edits)
        buttons[1].button("Clear all edits", on_click=clear_edits, disabled=not edits)

    st.subheader("Save as reviewed (training log)")
    previous = training_log.find_review(log_dir, sem)
    if previous is not None:
        meta = previous.meta
        st.caption(
            f"Saved before: {meta['saved_at']} by {meta['user']}, {len(meta['edits'])} edits, "
            f"{meta['n_grains_after_edits']} grains."
        )
        if meta["edits"] and not edits and not by_clicks:
            st.button("Load the saved edits", on_click=load_saved_edits, args=(meta["edits"],))
        saved_points = previous.folder / "points.csv"
        if by_clicks and not clicks and saved_points.exists():
            saved = read_points(saved_points, sem.image.shape, sem.image.shape[1])
            st.button(
                "Load the saved clicks",
                on_click=set_clicks,
                args=(clicks_from_table(saved),),
            )
    note = st.text_input(
        "Note (optional)", key=f"note_{name}", placeholder="e.g. unsure about the top-left grains"
    )
    if st.button(
        "Save as reviewed",
        type="primary",
        help="Store this image's final grain map, your edits and the settings in the training "
        f"log ({log_dir}). Saving again replaces the earlier review of this image. Save also "
        "when no edit was needed: confirmed results are training data too.",
    ):
        folder = training_log.save_review(
            log_dir,
            result,
            [] if by_clicks else edits,
            edit_warnings,
            raw_n_grains=auto_summary["n_grains"],
            note=note,
            points=[(y, x) for y, x, k in clicks if k != HOLE] if by_clicks else None,
            holes=[(y, x) for y, x, k in clicks if k == HOLE] if by_clicks else None,
        )
        st.success(f"Saved to {folder}")
with tab_stages:
    left, right = st.columns(2)
    left.image(pre, caption="Preprocessed", clamp=True, width="stretch")
    right.image(bmap, caption="Boundary map (bright = boundary)", clamp=True, width="stretch")
    raw_view = gc.Result(sem, params, pre, bmap, seeds, raw, raw, grains.iloc[:0], {})
    left.image(gc.overlay(raw_view, show_seeds=True), caption="Before merging", width="stretch")
    right.image(gc.overlay(result), caption="Final (with your edits)", width="stretch")
with tab_hist:
    interior = grains[~grains["touches_edge"]] if len(grains) else grains
    if len(interior):
        st.bar_chart(
            pd.cut(interior["eq_diameter_nm"], bins=20)
            .value_counts(sort=False)
            .rename(index=lambda iv: f"{iv.mid:.0f}")
            .rename_axis("eq. diameter (nm)"),
        )
    st.dataframe(pd.Series(summary).astype(str).to_frame("value"), width="stretch")
with tab_table:
    st.dataframe(grains, width="stretch")

st.download_button(
    "Download params JSON", params.model_dump_json(indent=2), file_name="params.json"
)
st.download_button(
    "Download grains CSV", grains.to_csv(index=False), file_name=f"{Path(name).stem}_grains.csv"
)
