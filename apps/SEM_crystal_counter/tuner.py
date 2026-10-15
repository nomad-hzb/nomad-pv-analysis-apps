"""Interactive parameter tuner (dev tool, not part of the Voila app).

    streamlit run tuner.py --server.address localhost -- "D:/.../SEM images"

Each stage is cached on the parameters it depends on, so moving a merge slider does not
redo denoising or the boundary map.
"""

from __future__ import annotations

import sys
from pathlib import Path

import grain_core as gc
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Grain tuner", layout="wide")

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
files = sorted(p.name for p in folder.glob("*.tif"))


@st.cache_data
def load(name: str) -> gc.SemImage:
    return gc.load_sem_tiff(folder / name)


@st.cache_data
def stage_pre(name: str, bg: float, denoise: str, strength: float) -> np.ndarray:
    sem = load(name)
    p = gc.Params(background_sigma_nm=bg, denoise=denoise, denoise_strength=strength)
    return gc.preprocess(sem.image, sem.pixel_size_nm, p)


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


with st.sidebar:
    st.header("Image")
    if not files:
        st.error(f"No .tif files in {folder}")
        st.stop()
    name = st.selectbox("File", files)
    preset = st.selectbox("Start from preset", sorted(gc.PRESETS))
    uploaded = st.file_uploader("...or load params JSON", type="json")
    base = gc.Params.model_validate_json(uploaded.getvalue()) if uploaded else gc.PRESETS[preset]

    st.header("Preprocess")
    bg = st.slider("Background sigma (nm, 0=off)", 0.0, 3000.0, base.background_sigma_nm, 100.0)
    denoise = st.selectbox(
        "Denoise", ["nlm", "gaussian", "none"], ["nlm", "gaussian", "none"].index(base.denoise)
    )
    strength = st.slider("NLM strength", 0.2, 2.0, base.denoise_strength, 0.1)

    st.header("Boundary map")
    sigma_text = st.text_input(
        "Ridge sigmas (nm, comma separated)", ", ".join(map(str, base.ridge_sigmas_nm))
    )
    sigmas = tuple(float(s) for s in sigma_text.split(",") if s.strip())
    clip = st.slider(
        "Clip bright rims above percentile", 50.0, 100.0, base.clip_bright_percentile, 1.0
    )
    weight = st.slider("Ridge weight (1 = no gradient)", 0.0, 1.0, base.ridge_weight, 0.05)

    st.header("Seeds / watershed")
    seed_method = st.selectbox(
        "Seed method", ["distance", "hminima"], ["distance", "hminima"].index(base.seed_method)
    )
    boundary_threshold = st.slider(
        "Boundary threshold (x Otsu)", 0.3, 2.0, base.boundary_threshold, 0.05
    )
    hminima_h = st.slider("h-minima depth", 0.005, 0.3, base.hminima_h, 0.005)
    min_diam = st.slider("Min grain diameter (nm)", 5.0, 200.0, base.min_grain_diameter_nm, 5.0)
    compactness = st.slider("Compactness", 0.0, 0.01, base.compactness, 0.0005, format="%.4f")

    st.header("Merge")
    merge_threshold = st.slider(
        "Merge threshold (x median boundary)", 0.0, 2.0, base.merge_threshold, 0.05
    )
    merge_sigma = st.slider("Merge ridge sigma (nm)", 2.0, 40.0, base.merge_sigma_nm, 1.0)
    min_area = st.slider("Min grain area (nm²)", 0.0, 20000.0, base.min_grain_area_nm2, 250.0)

params = gc.Params(
    background_sigma_nm=bg,
    denoise=denoise,
    denoise_strength=strength,
    ridge_sigmas_nm=list(sigmas),
    clip_bright_percentile=clip,
    ridge_weight=weight,
    seed_method=seed_method,
    boundary_threshold=boundary_threshold,
    hminima_h=hminima_h,
    min_grain_diameter_nm=min_diam,
    compactness=compactness,
    merge_threshold=merge_threshold,
    merge_sigma_nm=merge_sigma,
    min_grain_area_nm2=min_area,
)

sem = load(name)
px = sem.pixel_size_nm
pre = stage_pre(name, bg, denoise, strength)
bmap = stage_bmap(pre, px, sigmas, clip, weight)
seeds, raw, labels = stage_segment(pre, bmap, px, params.model_dump_json())
grains = gc.measure_grains(labels, px)
result = gc.Result(sem, params, pre, bmap, seeds, raw, labels, grains, {})
summary = gc.summarize(grains, labels, px, gc.intercept_grain_size(bmap, px, params))

st.title(name)
cols = st.columns(5)
cols[0].metric("Pixel size", f"{px:.3f} nm")
cols[1].metric("Seeds / raw regions", f"{int(seeds.max())} / {int(raw.max())}")
cols[2].metric("Grains (edge)", f"{summary['n_grains']} ({summary.get('n_edge', 0)})")
cols[3].metric(
    "Mean area", f"{summary.get('mean_area_planimetric_nm2', float('nan')) / 1e3:.1f}e3 nm²"
)
cols[4].metric("Intercept", f"{summary.get('mean_intercept_nm', float('nan')):.0f} nm")

tab_overlay, tab_stages, tab_hist, tab_table = st.tabs(
    ["Overlay", "Stages", "Histograms", "Grains"]
)
with tab_overlay:
    show_seeds = st.checkbox("Show seeds")
    st.image(gc.overlay(result, show_seeds=show_seeds), width="stretch")
with tab_stages:
    left, right = st.columns(2)
    left.image(pre, caption="Preprocessed", clamp=True, width="stretch")
    right.image(bmap, caption="Boundary map", clamp=True, width="stretch")
    raw_view = gc.Result(sem, params, pre, bmap, seeds, raw, raw, gc.measure_grains(raw, px), {})
    left.image(gc.overlay(raw_view, show_seeds=True), caption="Before merging", width="stretch")
    right.image(gc.overlay(result), caption="After merging", width="stretch")
with tab_hist:
    interior = grains[~grains["touches_edge"]] if len(grains) else grains
    if len(interior):
        st.bar_chart(
            pd.cut(interior["eq_diameter_nm"], bins=20)
            .value_counts(sort=False)
            .rename(index=lambda iv: f"{iv.mid:.0f}")
            .rename_axis("eq. diameter (nm)"),
        )
        st.write(pd.Series(summary).to_frame("value"))
with tab_table:
    st.dataframe(grains, width="stretch")

st.download_button(
    "Download params JSON", params.model_dump_json(indent=2), file_name="params.json"
)
st.download_button(
    "Download grains CSV", grains.to_csv(index=False), file_name=f"{Path(name).stem}_grains.csv"
)
