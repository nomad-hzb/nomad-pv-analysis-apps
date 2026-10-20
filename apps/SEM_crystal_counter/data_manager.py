"""
SEM Data Manager
================
Pure Python, no widget imports. Loads SEM images (from NOMAD batches, direct uploads or the
demo fixture), runs the grain analysis of grain_core on them, keeps the per-image manual
corrections (clicked grains and holes, merge/split edits), builds the per-image and
per-sample tables and exports, and saves reviews to the training log.
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import grain_core as gc
import numpy as np
import pandas as pd
import training_log

from hysprint_utils.api_calls import (
    download_raw_file,
    get_all_eqe,
    get_ids_in_batch,
    get_sample_description,
)
from hysprint_utils.config import ENTRY_TYPES
from hysprint_utils.usage_tracking import usage_log_dir

logger = logging.getLogger(__name__)

# Measurement type constant -- imported by gui_components.py
MEASUREMENT_TYPE = ENTRY_TYPES["sem"]
SHEETS = ("About", "Samples", "Images", "Grains", "Settings")
HOLE = 2  # click kind for holes, the same number as the ImageJ counter used for annotations
PRESET_CHOICES = ("auto", *gc.PRESETS)


def app_version() -> str:
    """Version from this app's pyproject.toml (shown in exports)."""
    text = (Path(__file__).parent / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else "unknown"


def training_log_dir() -> Path:
    """Reviews go next to the usage logs (shared/log/ of the upload, or wherever
    HYSPRINT_USAGE_LOG_DIR points), so every user of the upload adds to one training set."""
    return usage_log_dir() / "sem_training_log"


@dataclass
class SemEntry:
    """One SEM image and everything done with it."""

    name: str
    sample_id: str
    variation: str = ""
    source: str = "upload"  # "nomad", "upload" or "demo"
    sem: gc.SemImage | None = None
    error: str | None = None
    preset: str = "auto"
    result: gc.Result | None = None  # automatic result (compacted, see _compact)
    edits: list[dict] = field(default_factory=list)
    clicks: list[tuple[float, float, int]] = field(default_factory=list)  # (y, x, kind)
    use_clicks: bool = False
    ignored: bool = False  # left out of every result (e.g. a cross-section image)
    overrides: dict = field(default_factory=dict)  # per-image detection settings (sliders)
    _final: tuple | None = field(default=None, repr=False)  # (key, result, warnings) cache

    @property
    def analysed(self) -> bool:
        return self.result is not None


class SemDataManager:
    """Loads SEM images, analyses them and keeps the corrections."""

    def __init__(self, url: str = "", token: str = "") -> None:
        self._url = url
        self._token = token
        self.entries: dict[str, SemEntry] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    @property
    def names(self) -> list[str]:
        return list(self.entries)

    def load(self, batch_ids: list[str], progress=None) -> int:
        """Fetch every SEM image of the samples in the given batches from NOMAD. Returns the
        number of images added; images that fail to download or read are kept with an error."""
        sample_ids = get_ids_in_batch(self._url, self._token, batch_ids)
        if not sample_ids:
            return 0
        descriptions = get_sample_description(self._url, self._token, list(sample_ids))
        raw = get_all_eqe(self._url, self._token, sample_ids, eqe_type=MEASUREMENT_TYPE)
        files = [
            (sample_id, data, meta, path)
            for sample_id, entries in raw.items()
            for data, meta in entries
            for path in data.get("detector_data") or []
        ]
        added = 0
        for i, (sample_id, _data, meta, path) in enumerate(files):
            if progress is not None:
                progress(i, len(files), Path(path).name)
            entry = SemEntry(
                name=self._unique_name(Path(path).name),
                sample_id=sample_id,
                variation=descriptions.get(sample_id, ""),
                source="nomad",
            )
            try:
                content = download_raw_file(self._url, self._token, meta["upload_id"], path)
                entry.sem = gc.load_sem_tiff(content, name=Path(path).name)
            except Exception as exc:  # one broken file must not stop the batch
                logger.warning("Could not load %s: %s", path, exc)
                entry.error = f"could not load: {exc}"
            self.entries[entry.name] = entry
            added += 1
        return added

    def add_uploads(self, files: list[tuple[str, bytes]]) -> int:
        """Add uploaded TIFFs (name, content). The sample is taken from the file name
        ('VP317_01.tif' -> 'VP317'). Returns the number of images added."""
        for file_name, content in files:
            entry = SemEntry(
                name=self._unique_name(file_name),
                sample_id=gc.sample_name(file_name),
                source="upload",
            )
            try:
                entry.sem = gc.load_sem_tiff(bytes(content), name=file_name)
            except Exception as exc:
                logger.warning("Could not read %s: %s", file_name, exc)
                entry.error = f"could not read: {exc}"
            self.entries[entry.name] = entry
        return len(files)

    def load_offline(self, fixture_path) -> bool:
        """Demo mode: load the images listed in a fixture JSON
        {"images": [{"file": <path relative to the JSON>, "sample_id": ..., "variation": ...}]}."""
        fixture_path = Path(fixture_path)
        spec = json.loads(fixture_path.read_text(encoding="utf-8"))
        for item in spec["images"]:
            path = fixture_path.parent / item["file"]
            entry = SemEntry(
                name=self._unique_name(path.name),
                sample_id=item.get("sample_id") or gc.sample_name(path.name),
                variation=item.get("variation", ""),
                source="demo",
            )
            entry.sem = gc.load_sem_tiff(path)
            self.entries[entry.name] = entry
        return bool(spec["images"])

    def clear(self) -> None:
        self.entries.clear()

    def _unique_name(self, name: str) -> str:
        if name not in self.entries:
            return name
        stem, suffix = Path(name).stem, Path(name).suffix
        n = 2
        while f"{stem} ({n}){suffix}" in self.entries:
            n += 1
        return f"{stem} ({n}){suffix}"

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    def analyse(self, name: str, preset: str = "auto") -> SemEntry:
        """Run the automatic analysis on one image, with its per-image detection settings
        (entry.overrides) on top of the preset. Corrections made earlier are kept: they are
        stored as image positions and replayed on the new result."""
        entry = self.entries[name]
        if entry.sem is None:
            return entry
        if entry.sem.pixel_size_nm is None:
            entry.error = "no pixel size in the TIFF metadata"
            return entry
        try:
            chosen, ratio, result = preset, None, None
            if preset == "auto":
                if entry.overrides and entry.result is not None:
                    chosen = entry.result.summary.get("preset", "smooth")
                    ratio = entry.result.summary.get("preset_ratio")
                else:
                    result = gc.analyze_auto(entry.sem)
                    chosen, ratio = result.summary["preset"], result.summary["preset_ratio"]
            if entry.overrides or result is None:
                params = gc.PRESETS[chosen].model_copy(update=entry.overrides)
                result = gc.analyze(entry.sem, params)
            result.summary.update(
                {"preset": chosen, "preset_ratio": ratio, "custom_settings": bool(entry.overrides)}
            )
        except Exception as exc:
            logger.exception("Analysis of %s failed", name)
            entry.error = f"analysis failed: {exc}"
            return entry
        entry.result = _compact(result)
        entry.preset = preset
        entry.error = None
        return entry

    def analyse_all(self, preset: str = "auto", progress=None, only_new: bool = True) -> None:
        todo = [e for e in self.entries.values() if e.sem is not None]
        if only_new:
            todo = [e for e in todo if not e.analysed]
        for i, entry in enumerate(todo):
            if progress is not None:
                progress(i, len(todo), entry.name)
            self.analyse(entry.name, preset)

    def final_result(self, name: str) -> tuple[gc.Result | None, list[str]]:
        """The result as the user sees it: grains from clicks when click mode is on,
        otherwise the automatic result with merge/split edits replayed. Also returns the
        warnings of edits that no longer apply."""
        entry = self.entries[name]
        if entry.result is None:
            return None, []
        key = (id(entry.result), entry.use_clicks, tuple(entry.clicks), json.dumps(entry.edits))
        if entry._final is not None and entry._final[0] == key:
            return entry._final[1], entry._final[2]
        result, warnings = self._compute_final(entry)
        entry._final = (key, result, warnings)
        return result, warnings

    def _compute_final(self, entry: SemEntry) -> tuple[gc.Result, list[str]]:
        if entry.use_clicks:
            grains = [(y, x) for y, x, kind in entry.clicks if kind != HOLE]
            holes = [(y, x) for y, x, kind in entry.clicks if kind == HOLE]
            if not grains:
                return entry.result, []
            return gc.result_from_points(entry.result, grains, holes), []
        return gc.apply_edits(entry.result, entry.edits)

    # ------------------------------------------------------------------
    # Corrections
    # ------------------------------------------------------------------
    def set_click_mode(self, name: str, on: bool) -> None:
        self.entries[name].use_clicks = on

    def start_clicks_from_automatic(self, name: str) -> None:
        entry = self.entries[name]
        if entry.result is not None:
            entry.clicks = [(y, x, 0) for y, x in gc.grain_centres(entry.result)]

    def params(self, name: str) -> gc.Params:
        """The detection settings in use for an image: its preset plus its own overrides."""
        entry = self.entries[name]
        preset = entry.result.summary.get("preset", "smooth") if entry.result else "smooth"
        return gc.PRESETS[preset].model_copy(update=entry.overrides)

    def set_overrides(self, name: str, overrides: dict) -> SemEntry:
        """Change an image's detection settings (empty dict = back to its preset) and
        re-analyse it."""
        entry = self.entries[name]
        entry.overrides = dict(overrides)
        return self.analyse(name, entry.preset)

    def set_ignored(self, name: str, ignored: bool) -> None:
        self.entries[name].ignored = ignored

    def add_click(self, name: str, y: float, x: float, kind: int = 0, radius: float = 7.0):
        """Add a grain (kind 0) or hole (HOLE) click. A click on an existing dot adds nothing
        (two dots in one grain would split it). Returns "added" or "exists"."""
        if self._near(name, y, x, radius):
            return "exists"
        self.entries[name].clicks.append((float(y), float(x), int(kind)))
        return "added"

    def remove_click(self, name: str, y: float, x: float, radius: float = 10.0):
        """Remove the dot nearest to (y, x) within radius. Returns "removed" or "none"."""
        near = self._near(name, y, x, radius)
        if not near:
            return "none"
        clicks = self.entries[name].clicks
        nearest = min(near, key=lambda i: (clicks[i][0] - y) ** 2 + (clicks[i][1] - x) ** 2)
        clicks.pop(nearest)
        return "removed"

    def _near(self, name: str, y: float, x: float, radius: float) -> list[int]:
        return [
            i
            for i, (cy, cx, _) in enumerate(self.entries[name].clicks)
            if (cy - y) ** 2 + (cx - x) ** 2 <= radius**2
        ]

    def toggle_click(self, name: str, y: float, x: float, kind: int = 0, radius: float = 7.0):
        """Add a grain (kind 0) or hole (HOLE) click, or remove the click within `radius`
        pixels of (y, x) if there is one. Returns "added" or "removed"."""
        clicks = self.entries[name].clicks
        near = [
            i for i, (cy, cx, _) in enumerate(clicks) if (cy - y) ** 2 + (cx - x) ** 2 <= radius**2
        ]
        if near:
            clicks.pop(near[-1])
            return "removed"
        clicks.append((float(y), float(x), int(kind)))
        return "added"

    def add_edit(self, name: str, edit: dict) -> None:
        self.entries[name].edits.append(edit)

    def undo(self, name: str) -> None:
        """Undo the last correction of the current mode."""
        entry = self.entries[name]
        target = entry.clicks if entry.use_clicks else entry.edits
        if target:
            target.pop()

    def clear_corrections(self, name: str) -> None:
        entry = self.entries[name]
        if entry.use_clicks:
            entry.clicks = []
        else:
            entry.edits = []

    def save_review(self, name: str, note: str = "") -> Path:
        """Store the image's final grain map and corrections in the training log."""
        entry = self.entries[name]
        result, warnings = self.final_result(name)
        if result is None:
            raise ValueError(f"{name} has not been analysed")
        grains = [(y, x) for y, x, k in entry.clicks if k != HOLE] if entry.use_clicks else None
        holes = [(y, x) for y, x, k in entry.clicks if k == HOLE] if entry.use_clicks else None
        return training_log.save_review(
            training_log_dir(),
            result,
            [] if entry.use_clicks else entry.edits,
            warnings,
            raw_n_grains=entry.result.summary.get("n_grains"),
            note=note,
            points=grains,
            holes=holes,
        )

    # ------------------------------------------------------------------
    # Tables and exports
    # ------------------------------------------------------------------
    def image_table(self) -> pd.DataFrame:
        """One row per image: sample, source, status and the image-level statistics."""
        rows = []
        for entry in self.entries.values():
            row = {
                "image": entry.name,
                "sample": entry.sample_id,
                "variation": entry.variation,
                "source": entry.source,
                "pixel_size_nm": entry.sem.pixel_size_nm if entry.sem else None,
                "status": "ignored"
                if entry.ignored
                else entry.error or ("analysed" if entry.analysed else "not analysed"),
                "corrected": "clicks" if entry.use_clicks else ("edits" if entry.edits else ""),
            }
            if entry.analysed and not entry.ignored:
                result, _ = self.final_result(entry.name)
                summary = result.summary
                row.update(
                    {
                        "preset": entry.result.summary.get("preset")
                        + (" (own settings)" if entry.overrides else ""),
                        "n_grains": summary.get("n_grains"),
                        "mean_eq_diameter_nm": summary.get("mean_eq_diameter_nm"),
                        "mean_area_planimetric_nm2": summary.get("mean_area_planimetric_nm2"),
                        "grains_per_um2": summary.get("grains_per_um2"),
                        "hole_area_fraction": summary.get("hole_area_fraction"),
                        "reliable": summary.get("reliable"),
                    }
                )
            rows.append(row)
        return pd.DataFrame(rows)

    def sample_table(self) -> pd.DataFrame:
        """Per-sample statistics over the analysed images (unreliable ones left out when the
        sample has reliable images), with the magnification-consistency score."""
        images = []
        for entry in self.entries.values():
            if not entry.analysed or entry.ignored:
                continue
            result, _ = self.final_result(entry.name)
            images.append({"sample": entry.sample_id, **result.summary})
        if not images:
            return pd.DataFrame()
        return gc.summarize_samples(pd.DataFrame(images))

    def grains_table(self) -> pd.DataFrame:
        """Every grain of every analysed image, with image and sample columns."""
        frames = []
        for entry in self.entries.values():
            if not entry.analysed or entry.ignored:
                continue
            result, _ = self.final_result(entry.name)
            grains = result.grains.copy()
            grains.insert(0, "sample", entry.sample_id)
            grains.insert(0, "image", entry.name)
            frames.append(grains)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def settings_table(self) -> pd.DataFrame:
        """Every setting used, one row each, for reproducibility. The preset each image got is
        in the image table."""
        rows = [
            ("app version", app_version(), "SEM_crystal_counter"),
            (
                "auto_ratio_threshold",
                gc.AUTO_RATIO_THRESHOLD,
                "smooth/probe grain-count ratio above which an image is treated as striped",
            ),
        ]
        for field_name, value in gc.CLASSIFIER_PROBE.model_dump().items():
            rows.append(
                (
                    f"classifier_probe.{field_name}",
                    value,
                    "fixed setting for the film-type decision",
                )
            )
        for preset, params in gc.PRESETS.items():
            for field_name, value in params.model_dump().items():
                description = gc.Params.model_fields[field_name].description or ""
                rows.append((f"{preset}.{field_name}", value, description))
        for entry in self.entries.values():
            for field_name, value in entry.overrides.items():
                rows.append(
                    (f"{entry.name}: {field_name}", value, "own setting of this image (slider)")
                )
        return pd.DataFrame(
            [(k, json.dumps(v) if isinstance(v, list) else v, d) for k, v, d in rows],
            columns=["setting", "value", "meaning"],
        )

    def results_workbook(self, sheets=SHEETS) -> bytes:
        """The results in one Excel file, with the chosen sheets (in the order of SHEETS)."""
        if not sheets:
            raise ValueError("choose at least one sheet")
        images, samples = self.image_table(), self.sample_table()
        n_ignored = int((images["status"] == "ignored").sum()) if len(images) else 0
        about = pd.DataFrame(
            [
                ("Created", datetime.now().strftime("%Y-%m-%d %H:%M")),
                ("App", f"SEM Crystal Counter {app_version()}"),
                ("Images", len(images)),
                ("Ignored images", f"{n_ignored} (listed in Images, left out of every result)"),
                ("Samples", len(samples)),
                (
                    "Grain definition",
                    "the region inside the deep outer groove; stripes or "
                    "facets inside a grain do not split it; holes are not grains",
                ),
                (
                    "Samples sheet",
                    "per sample: mean and spread over its images (images with "
                    f"fewer than {gc.MIN_GRAINS_FOR_STATS} grains left out), magnification spread",
                ),
                (
                    "Images sheet",
                    "per image: preset used, grain count, mean diameter, density, "
                    "hole area, reliability, manual corrections",
                ),
                (
                    "Grains sheet",
                    "every grain of every image, sizes in nm; touches_edge grains "
                    "are excluded from the size means",
                ),
                ("Settings sheet", "every parameter used, for reproducing the results"),
            ],
            columns=["item", "value"],
        )
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            tables = {
                "About": lambda: about,
                "Samples": lambda: samples,
                "Images": lambda: images,
                "Grains": self.grains_table,
                "Settings": self.settings_table,
            }
            for sheet in SHEETS:
                if sheet in sheets:
                    tables[sheet]().to_excel(writer, sheet_name=sheet, index=False)
        return buffer.getvalue()


def _compact(result: gc.Result) -> gc.Result:
    """Keep what the corrections and displays need and drop the rest: the preprocessed image
    and the pre-merge labels are only needed inside the analysis, and the boundary map is
    stored as float32. About 10 MB per image instead of about 25 MB."""
    return gc.Result(
        result.sem,
        result.params,
        None,
        result.bmap.astype(np.float32),
        result.seeds,
        None,
        result.labels,
        result.grains,
        result.summary,
    )
