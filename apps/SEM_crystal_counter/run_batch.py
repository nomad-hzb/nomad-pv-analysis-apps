"""Batch-run the grain pipeline over a folder of SEM TIFFs.

Writes, per image, an overlay PNG and a per-grain CSV; per run, summary_images.csv,
summary_samples.csv, params.json and report.html (a gallery of all overlays).

    python run_batch.py "D:/.../SEM images" --out results                  # preset chosen per image
    python run_batch.py "D:/.../SEM images" --out results --preset smooth
    python run_batch.py "D:/.../SEM images" --out results --params my_params.json --glob "VP4*.tif"
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import time
from pathlib import Path

import grain_core as gc
import pandas as pd
from PIL import Image

logger = logging.getLogger(__name__)


def load_params(preset: str, params_path: str | None) -> gc.Params | None:
    """Params from a JSON file or a preset name; None means 'auto' (chosen per image)."""
    if params_path:
        return gc.Params.model_validate_json(Path(params_path).read_text(encoding="utf-8"))
    if preset == "auto":
        return None
    return gc.PRESETS[preset].model_copy()


def run_one(sem: gc.SemImage, params: gc.Params | None) -> gc.Result:
    return gc.analyze_auto(sem) if params is None else gc.analyze(sem, params)


def params_json(params: gc.Params | None) -> str:
    if params is not None:
        return params.model_dump_json(indent=2)
    presets = {name: p.model_dump() for name, p in gc.PRESETS.items()}
    return json.dumps(
        {"auto_ratio_threshold": gc.AUTO_RATIO_THRESHOLD, "presets": presets}, indent=2
    )


def summarize_samples(images: pd.DataFrame) -> pd.DataFrame:
    """Per-sample mean and spread across images (images are the replicates, not grains).

    Images flagged as unreliable (too few grains, see grain_core.MIN_GRAINS_FOR_STATS) are
    left out when the sample has any reliable image; n_images_flagged reports them.
    """
    cols = [
        "grains_per_um2",
        "mean_area_planimetric_nm2",
        "mean_area_ml_nm2",
        "median_area_nm2",
        "mean_eq_diameter_nm",
        "mean_intercept_nm",
        "boundary_length_per_um2",
    ]
    if "reliable" in images:
        has_reliable = images.groupby("sample")["reliable"].transform("any")
        used = images[images["reliable"].astype(bool) | ~has_reliable]
    else:
        used = images
    grouped = used.groupby("sample")
    out = grouped[cols].agg(["mean", "std"])
    out.columns = [f"{c}_{stat}" for c, stat in out.columns]
    out.insert(0, "n_images", grouped.size())
    out.insert(1, "n_images_flagged", images.groupby("sample").size() - grouped.size())
    out.insert(2, "n_grains_total", grouped["n_grains"].sum())
    return out.reset_index()


def write_report(out: Path, images: pd.DataFrame, params: gc.Params | None) -> None:
    cards = []
    for _, row in images.iterrows():
        stats = (
            f"{row['n_grains']} grains ({row['n_edge']} at edge), "
            f"{row['pixel_size_nm']:.2f} nm/px"
            + (
                f", preset <b>{row['preset']}</b> (ratio {row['preset_ratio']:.1f})"
                if "preset" in row and isinstance(row["preset"], str)
                else ""
            )
            + (
                ' <b style="color:#c00">too few grains: excluded from sample statistics</b>'
                if "reliable" in row and not bool(row["reliable"])
                else ""
            )
            + "<br>"
            f"mean area {row['mean_area_planimetric_nm2'] / 1e3:.1f}e3 nm&sup2;, "
            f"mean eq. diameter {row['mean_eq_diameter_nm']:.0f} nm, "
            f"intercept {row['mean_intercept_nm']:.0f} nm"
        )
        png = html.escape(Path(row["image"]).stem + ".png")
        cards.append(
            f'<figure><a href="{png}"><img src="{png}" loading="lazy"></a>'
            f"<figcaption><b>{html.escape(row['image'])}</b><br>{stats}</figcaption></figure>"
        )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Grain report</title>
<style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#fafafa;color:#222}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px}}
figure{{margin:0;background:#fff;border:1px solid #ddd;padding:6px}}
img{{width:100%;display:block}} figcaption{{font-size:13px;margin-top:4px}}
pre{{background:#fff;border:1px solid #ddd;padding:8px;font-size:12px;overflow:auto}}
</style></head><body>
<h1>Grain segmentation report</h1>
<p>Green: interior grains. Orange: grains cut by the image edge (excluded from size means,
counted as half in the planimetric density).</p>
<details><summary>Parameters</summary><pre>{html.escape(params_json(params))}</pre></details>
<div class="grid">{"".join(cards)}</div></body></html>"""
    (out / "report.html").write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("folder")
    parser.add_argument("--out", default="results")
    parser.add_argument("--glob", default="*.tif")
    parser.add_argument("--preset", default="auto", choices=["auto", *sorted(gc.PRESETS)])
    parser.add_argument("--params", help="Params JSON (overrides --preset)")
    parser.add_argument("--seeds", action="store_true", help="Draw seeds on the overlays")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    params = load_params(args.preset, args.params)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "params.json").write_text(params_json(params), encoding="utf-8")

    summaries = []
    for path in sorted(Path(args.folder).glob(args.glob)):
        start = time.perf_counter()
        sem = gc.load_sem_tiff(path)
        result = run_one(sem, params)
        Image.fromarray(gc.overlay(result, show_seeds=args.seeds)).save(out / f"{path.stem}.png")
        result.grains.to_csv(out / f"{path.stem}_grains.csv", index=False)
        summary = {"sample": gc.sample_name(path.name), **result.summary}
        summaries.append(summary)
        logger.info(
            "%s: %d grains, mean area %.0f nm2 (%.1f s)",
            path.name,
            summary["n_grains"],
            summary.get("mean_area_planimetric_nm2", float("nan")),
            time.perf_counter() - start,
        )
    if not summaries:
        logger.error("No files matching %s in %s", args.glob, args.folder)
        return
    images = pd.DataFrame(summaries)
    images.to_csv(out / "summary_images.csv", index=False)
    summarize_samples(images).to_csv(out / "summary_samples.csv", index=False)
    write_report(out, images, params)
    logger.info("Report: %s", (out / "report.html").resolve())
    (out / "run_info.json").write_text(json.dumps({"n_images": len(images)}), encoding="utf-8")


if __name__ == "__main__":
    main()
