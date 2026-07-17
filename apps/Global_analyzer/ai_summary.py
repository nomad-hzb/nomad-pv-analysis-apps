"""
AI Summary Generator Module

Collects experiment data and generates intelligent summaries using LLM API.
Uses compact CSV-based dataset representation and multi-turn conversation history.

Author: HySprint Team
"""

import logging
import re

import config
import ipywidgets as widgets
import pandas as pd
import requests
from IPython.display import HTML, clear_output, display

logger = logging.getLogger(__name__)


# ── Fixed hidden preamble — prepended to first LLM call only, never shown in editor ──
_HIDDEN_PREAMBLE = """You are an expert in photovoltaics and solar cell research at Helmholtz-Zentrum Berlin (HZB).
You are analyzing perovskite solar cell fabrication and characterization data from the HySprint laboratory.

DATA STRUCTURE:
- Each sample is a solar cell substrate containing multiple pixels (individual cells).
  In the result tables, each pixel appears as a separate row — multiple rows with the
  same sample_id are different pixels or scan directions of the same sample.
  Scan direction (forward/reverse) is indicated by the cell_name field when present.
- Process steps describe the fabrication sequence (cleaning, spin coating, evaporation,
  inkjet printing, etc.). Parameters within each step are fabrication variables.
- Result data is provided as labeled CSV blocks per measurement type.
  Each block has a header row and one data row per pixel measurement.
- Process data is split by material and deduplicated. Each process type (e.g., spin_coating)
  is split into separate sections by layer material (e.g., spin_coating_NiO, spin_coating_perovskite).
  Within each section, samples with identical parameter combinations are grouped together.
  MATERIAL lines indicate which material that section describes.
  CONSTANT lines list parameters identical for all samples in that material group.
  The CSV rows show: count (number with these parameters), samples (list if ≤3, or 
  "first+last" range if >3), then the varied parameter values.
  Plus notation indicates ranges (e.g., "1_A_C-1+1_A_C-23" means samples 1 through 23).
- SID_PREFIX lines indicate a common sample_id prefix that has been stripped from all
  sample_id values in that section. Additionally, the "_C-" pattern is removed for compactness
  (e.g., full ID "HZB_JJ_1_A_C-01" becomes "1_A_01" when prefix is "HZB_JJ_").
- The VARIATIONS section shows unique experimental variations with: count (number of samples),
  samples (list if ≤3, or "first+last" range if >3), and variation (description).
  Plus notation indicates ranges (e.g., "1_A_C-1+1_A_C-4" means samples 1 through 4).
- Batch names are simplified to just numbers (e.g., "1, 2, 3, 4" instead of full codes).
- Columns with no data for any sample are omitted entirely.

FIELD ALIASES (short codes used in the data):
eff=efficiency(%), voc=open_circuit_voltage(V), jsc=short_circuit_current_density(mA/cm2),
ff=fill_factor(%), rs=series_resistance(Ohm*cm2), rsh=shunt_resistance(Ohm*cm2),
vmpp=voltage_at_mpp(V), jmpp=current_density_at_mpp(mA/cm2), li=light_intensity(%),
cell=cell_name, mat=layer_material_name, ltype=layer_type,
Tann=annealing_temperature(C), tann=annealing_time(min), atm=annealing_atmosphere,
Tsub=substrate_temperature(C), bg=bandgap(eV), lqy=luminescence_quantum_yield,
qfls=quasi_fermi_level_splitting(eV), ivoc=implied_voc(V), vol=solution_volume(uL),
sid=sample_id
"""

# ── Fixed summary request — shown in editor, user can modify ──
_DEFAULT_SUMMARY_REQUEST = """Please structure your response with the following 6 sections, each as a separate paragraph with a heading. Do not merge sections together.

1. Experiment Overview
Brief overview of the experiment series (2-3 sentences).

2. Fabrication Methods and Materials
The key fabrication methods and materials used.

3. Varied Parameters
What parameters were systematically varied and their ranges.

4. Performance Trends
Analysis of performance trends — is efficiency improving? What factors seem important?

5. Notable Findings
Any notable findings or patterns in the data.

6. Recommendations
Recommendations for next experiments if patterns are clear.

Keep the total response concise (200-300 words). Use technical language appropriate for solar cell researchers."""


def _render_markdown(text: str) -> str:
    """Convert subset of markdown to HTML for display in the output widget."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = text.split("\n")
    html_lines = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        stripped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)

        num_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if num_match:
            if not in_list:
                html_lines.append('<ol style="line-height:1.9;padding-left:1.4em;">')
                in_list = "ol"
            html_lines.append(f"<li>{num_match.group(2)}</li>")
            continue

        bul_match = re.match(r"^[-*]\s+(.*)", stripped)
        if bul_match:
            if not in_list:
                html_lines.append('<ul style="line-height:1.9;padding-left:1.4em;">')
                in_list = "ul"
            html_lines.append(f"<li>{bul_match.group(1)}</li>")
            continue

        if in_list:
            html_lines.append(f"</{in_list}>")
            in_list = False

        if not stripped:
            html_lines.append("<br/>")
        else:
            html_lines.append(f'<p style="margin:0 0 0.6em 0;">{stripped}</p>')

    if in_list:
        html_lines.append(f"</{in_list}>")

    return "\n".join(html_lines)


class ExperimentSummarizer:
    """Generates AI-powered summaries of experiment data."""

    def __init__(self, api_key: str):
        self.api_url = "https://api.helmholtz-blablador.fz-juelich.de/v1"
        self.api_key = api_key
        self.model = "alias-large"  # also alias-huge
        self.fallback_model = "alias-fast"

    # ── CSV dataset builder ───────────────────────────────────────────────────

    def build_dataset_csv(self, data_manager, analyzer_instance) -> tuple:
        """
        Build compact CSV-based string representation of the loaded dataset.
        Returns (dataset_str, metadata_dict).

        Format:
            === BATCH INFO ===
            batches: ..., total_samples: N, ...

            === VARIATIONS ===
            sample_id,variation
            HZB_1,high temp series

            === RESULT: jv ===
            sid,eff,voc,jsc,...
            HZB_1,12.3,1.05,15.2,...

            === PROCESS: spin_coating ===
            CONSTANT: Tann=150, mat=NiOx
            sid,tann,vol
            HZB_1,30,100
        """
        blacklist = set(
            getattr(
                config,
                "AI_JSON_BLACKLIST",
                [
                    "voltage",
                    "current_density",
                    "jv_curve",
                    "eqe_data",
                    "wavelength",
                    "flux",
                    "intensity_array",
                    "raw_data",
                    "data_path",
                    "data_file",
                    "name",
                    "m_def",
                    "lab_id",
                    "mainfile",
                    "samples",
                ],
            )
        )
        result_skip = blacklist | {"datetime", "description", "data_file", "name", "lab_id"}
        process_skip = blacklist | {
            "description",
            "position_in_plan",
            "location",
            "variation",
            "name",
        }

        sample_ids = analyzer_instance.current_sample_ids
        current_variation = getattr(analyzer_instance, "current_variation", {})
        batch_ids = getattr(analyzer_instance, "current_batches", [])

        field_aliases = {
            "sample_id": "sid",
            "efficiency": "eff",
            "open_circuit_voltage": "voc",
            "short_circuit_current_density": "jsc",
            "fill_factor": "ff",
            "series_resistance": "rs",
            "shunt_resistance": "rsh",
            "potential_at_maximum_power_point": "vmpp",
            "current_density_at_maximun_power_point": "jmpp",
            "light_intensity": "li",
            "cell_name": "cell",
            "layer_material_name": "mat",
            "layer_type": "ltype",
            "annealing_temperature": "Tann",
            "annealing_time": "tann",
            "annealing_atmosphere": "atm",
            "substrate_temperature": "Tsub",
            "bandgap": "bg",
            "luminescence_quantum_yield": "lqy",
            "quasi_fermi_level_splitting": "qfls",
            "i_voc": "ivoc",
            "solution_volume": "vol",
        }
        type_aliases = {
            "jv_measurement": "jv",
            "eqe_measurement": "eqe",
            "simple_mpp_tracking": "mpp",
            "mpp_tracking": "mpp",
            "abspl_measurement": "abspl",
            "pl_measurement": "pl",
            "trpl_measurement": "trpl",
        }

        def _a(name):
            return field_aliases.get(name, name)

        def _clean(val):
            if isinstance(val, list):
                return None
            try:
                if pd.isna(val):
                    return None
            except (TypeError, ValueError):
                pass
            if isinstance(val, float):
                return round(val, 3)
            return val

        def _fmt(val):
            return "" if val is None else str(val)

        blocks = []

        # ── Timeframe ──
        all_datetimes = []
        for df in data_manager.current_results.values():
            if df is not None and "datetime" in df.columns:
                dates = pd.to_datetime(df["datetime"], errors="coerce").dropna()
                all_datetimes.extend(dates.tolist())
        timeframe = {}
        if all_datetimes:
            mn, mx = min(all_datetimes), max(all_datetimes)
            timeframe = {
                "first": mn.strftime("%Y-%m-%d"),
                "last": mx.strftime("%Y-%m-%d"),
                "days": (mx - mn).days,
            }

        # ── Batch info block ──
        # Simplify batch names: extract numbers from HZB_JJ_X_Y pattern
        simplified_batches = []
        for bid in batch_ids:
            match = re.search(r"HZB_JJ_(\d+)", bid)
            if match:
                simplified_batches.append(match.group(1))
            else:
                simplified_batches.append(bid)

        info_lines = [
            "=== BATCH INFO ===",
            f"batches: {', '.join(simplified_batches)}",
            f"total_samples: {len(sample_ids)}",
        ]
        if timeframe:
            info_lines.append(
                f"timeframe: {timeframe['first']} to {timeframe['last']} ({timeframe['days']} days)"
            )
        info_lines.append(f"process_types: {', '.join(data_manager.current_metadata.keys())}")
        info_lines.append(f"measurement_types: {', '.join(data_manager.current_results.keys())}")
        blocks.append("\n".join(info_lines))

        # ── Sample ID compression ──
        # Aggressive compression: remove HZB_JJ_ if all have it, else common prefix
        sid_prefix = ""
        if len(sample_ids) > 1:
            # First check if all start with HZB_JJ_
            if all(sid.startswith("HZB_JJ_") for sid in sample_ids):
                sid_prefix = "HZB_JJ_"
            else:
                # Find longest common prefix
                prefix = sample_ids[0]
                for sid in sample_ids[1:]:
                    while not sid.startswith(prefix) and prefix:
                        prefix = prefix[:-1]
                # Only use if it saves meaningful space
                if len(prefix) >= 4 and len(sample_ids) >= 3:
                    sid_prefix = prefix

        def _compress_sid(sid):
            if sid_prefix and sid.startswith(sid_prefix):
                compressed = sid[len(sid_prefix) :]
                # Also remove C- pattern if present (e.g., 1_A_C-01 → 1_A_01)
                compressed = compressed.replace("_C-", "_")
                return compressed
            return sid

        # ── Variations block (with counts and ranges) ──
        variations = {
            sid: current_variation[sid]
            for sid in sample_ids
            if current_variation.get(sid, "").strip()
        }
        if variations:
            # Extract batch_variation key: HZB_JJ_4_A_C-01 → 4_A
            def _extract_batch_var(sid):
                sid_short = _compress_sid(sid)
                parts = sid_short.split("_")
                if len(parts) >= 2:
                    return f"{parts[0]}_{parts[1]}"
                return sid_short

            # Group by batch_variation and count samples
            bv_groups = {}
            for sid, var in variations.items():
                bv = _extract_batch_var(sid)
                if bv not in bv_groups:
                    bv_groups[bv] = {"variation": var, "samples": []}
                bv_groups[bv]["samples"].append(_compress_sid(sid))

            var_lines = ["=== VARIATIONS ==="]
            if sid_prefix:
                var_lines.append(f"SID_PREFIX: {sid_prefix}")
            var_lines.append("count,samples,variation")

            for bv in sorted(bv_groups.keys()):
                info = bv_groups[bv]
                count = len(info["samples"])
                samples = info["samples"]

                # Show range with + if >3, else comma-separated list
                if count <= 3:
                    sample_str = ", ".join(samples)
                else:
                    sample_str = f"{samples[0]}+{samples[-1]}"

                var_lines.append(f"{count},{sample_str},{info['variation']}")

            if len(var_lines) > (3 if sid_prefix else 2):  # more than just headers
                blocks.append("\n".join(var_lines))

        # ── Result CSV blocks ──
        result_stats = {}
        for mtype, df in data_manager.current_results.items():
            if df is None or df.empty:
                continue
            alias = type_aliases.get(mtype, mtype)
            raw_cols = ["sample_id"] + [
                c for c in df.columns if c != "sample_id" and c not in result_skip
            ]

            # Drop columns that are entirely empty
            non_empty_cols = ["sample_id"]
            for col in raw_cols[1:]:
                if df[col].notna().any():
                    cleaned_vals = [_clean(v) for v in df[col]]
                    if any(v is not None for v in cleaned_vals):
                        non_empty_cols.append(col)

            if len(non_empty_cols) == 1:  # only sample_id
                continue

            aliased_cols = [_a(c) for c in non_empty_cols]

            csv_lines = [f"=== RESULT: {alias} ==="]
            if sid_prefix:
                csv_lines.append(f"SID_PREFIX: {sid_prefix}")
            csv_lines.append(",".join(aliased_cols))

            row_count = 0
            for _, row in df.iterrows():
                sid_val = _compress_sid(_fmt(_clean(row.get("sample_id"))))
                other_vals = [_fmt(_clean(row.get(c))) for c in non_empty_cols[1:]]
                vals = [sid_val] + other_vals
                if any(v for v in vals[1:]):
                    csv_lines.append(",".join(vals))
                    row_count += 1

            if row_count > 0:
                blocks.append("\n".join(csv_lines))
                result_stats[alias] = row_count

        # ── Process CSV blocks (split by material, deduplicated) ──
        def _process_section(ptype_name, df_section, material_filter=None):
            """Process a single process section (possibly filtered by material)."""
            raw_cols = [c for c in df_section.columns if c != "sample_id" and c not in process_skip]

            # If we filtered by material, drop the material column (redundant)
            if material_filter and "layer_material_name" in raw_cols:
                raw_cols.remove("layer_material_name")

            # Hoist constant columns + drop all-empty columns
            constant = {}
            varied_raw = []
            for col in raw_cols:
                non_null = df_section[col].dropna()
                if len(non_null) == 0:
                    continue
                if len(non_null) == len(df_section) and non_null.nunique() == 1:
                    v = _clean(non_null.iloc[0])
                    if v is not None:
                        constant[_a(col)] = v
                else:
                    if df_section[col].notna().any():
                        varied_raw.append(col)

            if not varied_raw and not constant:
                return None  # Nothing to show

            # Group by varied parameters and collect samples per group
            if varied_raw:
                param_cols = ["sample_id"] + varied_raw
                df_work = df_section[param_cols].copy()

                # Clean values
                for col in varied_raw:
                    df_work[col] = df_work[col].apply(_clean)

                # Group by varied parameters
                grouped = df_work.groupby(varied_raw, dropna=False)

                # Build deduplicated rows with counts
                dedup_rows = []
                for params, group in grouped:
                    samples = [_compress_sid(_fmt(s)) for s in group["sample_id"].tolist()]
                    count = len(samples)

                    # Representative row (first in group)
                    row_dict = {"count": count}

                    # Add sample range/list (no sid needed)
                    if count <= 3:
                        row_dict["samples"] = ", ".join(samples)
                    else:
                        row_dict["samples"] = f"{samples[0]}+{samples[-1]}"

                    # Add parameter values
                    if isinstance(params, tuple):
                        for i, col in enumerate(varied_raw):
                            row_dict[col] = params[i]
                    else:
                        row_dict[varied_raw[0]] = params

                    dedup_rows.append(row_dict)

                # Convert to DataFrame
                df_dedup = pd.DataFrame(dedup_rows)
            else:
                # All parameters are constant - show count and range
                sid_first = _compress_sid(_fmt(df_section["sample_id"].iloc[0]))
                sid_last = _compress_sid(_fmt(df_section["sample_id"].iloc[-1]))
                df_dedup = pd.DataFrame(
                    [{"count": len(df_section), "samples": f"{sid_first}+{sid_last}"}]
                )

            row_cols = ["count", "samples"] + varied_raw
            aliased_rcols = [_a(c) if c in field_aliases else c for c in row_cols]

            proc_lines = [f"=== PROCESS: {ptype_name} ==="]
            if material_filter:
                proc_lines.append(f"MATERIAL: {material_filter}")
            if sid_prefix:
                proc_lines.append(f"SID_PREFIX: {sid_prefix}")
            if constant:
                const_str = ", ".join(f"{k}={v}" for k, v in constant.items())
                proc_lines.append(f"CONSTANT: {const_str}")
            proc_lines.append(",".join(aliased_rcols))

            row_count = 0
            for _, row in df_dedup.iterrows():
                vals = [_fmt(row.get("count")), _fmt(row.get("samples"))] + [
                    _fmt(row.get(c)) for c in varied_raw
                ]
                proc_lines.append(",".join(vals))
                row_count += 1

            if row_count > 0:
                return "\n".join(proc_lines), row_count
            return None

        process_stats = {}
        for ptype, df in data_manager.current_metadata.items():
            if df is None or df.empty:
                continue

            # Check if this process has a material column
            if "layer_material_name" in df.columns and df["layer_material_name"].notna().any():
                # Split by material
                for mat_name, mat_df in df.groupby("layer_material_name"):
                    if pd.isna(mat_name):
                        continue

                    section_name = f"{ptype}_{mat_name}"
                    result = _process_section(section_name, mat_df, mat_name)
                    if result:
                        block_text, row_count = result
                        blocks.append(block_text)
                        process_stats[section_name] = row_count
            else:
                # No material split
                result = _process_section(ptype, df)
                if result:
                    block_text, row_count = result
                    blocks.append(block_text)
                    process_stats[ptype] = row_count

        dataset_str = "\n\n".join(blocks)

        metadata = {
            "total_samples": len(sample_ids),
            "timeframe": timeframe,
            "result_stats": result_stats,
            "process_stats": process_stats,
            "char_count": len(dataset_str),
        }
        return dataset_str, metadata

    # ── LLM API call ──────────────────────────────────────────────────────────

    def call_llm_api(self, messages: list) -> str:
        """Send a messages list to Blablador API and return the response text."""
        try:
            response = requests.post(
                f"{self.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1000,
                    "temperature": 0.3,
                },
                timeout=60,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error: {str(e)}"

    # ── HTML display ──────────────────────────────────────────────────────────

    def display_summary(self, summary: str, metadata: dict):
        """Render the first AI summary as styled HTML with quick stats."""
        n_samples = metadata.get("total_samples", "?")
        tf = metadata.get("timeframe", {})
        timeframe_str = f"{tf['first']} → {tf['last']} ({tf['days']} days)" if tf else "N/A"
        result_stats = metadata.get("result_stats", {})
        process_stats = metadata.get("process_stats", {})
        char_count = metadata.get("char_count", 0)

        html_output = f"""
        <div style="border:2px solid #4CAF50;border-radius:10px;padding:20px;
                    background-color:#f9f9f9;font-family:Arial,sans-serif;">
            <h2 style="color:#4CAF50;margin-top:0;">🤖 AI Experiment Summary</h2>
            <div style="background-color:white;padding:15px;border-radius:5px;
                        margin-bottom:15px;border-left:4px solid #2196F3;">
                <h3 style="color:#2196F3;margin-top:0;">Quick Stats</h3>
                <ul style="line-height:1.8;">
                    <li><strong>Samples:</strong> {n_samples}</li>
                    <li><strong>Timeframe:</strong> {timeframe_str}</li>
                    <li><strong>Measurements:</strong> {
            ", ".join(f"{k} ({v} rows)" for k, v in result_stats.items()) or "N/A"
        }</li>
                    <li><strong>Process types:</strong> {
            ", ".join(f"{k} ({v} rows)" for k, v in process_stats.items()) or "N/A"
        }</li>
                    <li><strong>Data sent:</strong> {char_count:,} chars</li>
                </ul>
            </div>
            <div style="background-color:white;padding:15px;border-radius:5px;
                        border-left:4px solid #FF9800;">
                <h3 style="color:#FF9800;margin-top:0;">AI Analysis</h3>
                <div style="line-height:1.8;">{_render_markdown(summary)}</div>
            </div>
            <div style="margin-top:15px;font-size:0.9em;color:#666;">
                <em>Generated using Blablador API ({self.model})</em>
            </div>
        </div>
        """
        display(HTML(html_output))

    def display_followup(self, summary: str, turn: int):
        """Render a follow-up response."""
        html_output = f"""
        <div style="border:2px solid #9C27B0;border-radius:10px;padding:20px;
                    background-color:#f9f9f9;font-family:Arial,sans-serif;margin-top:10px;">
            <h3 style="color:#9C27B0;margin-top:0;">🔄 Follow-up Response (turn {turn})</h3>
            <div style="background-color:white;padding:15px;border-radius:5px;
                        border-left:4px solid #9C27B0;">
                <div style="line-height:1.8;">{_render_markdown(summary)}</div>
            </div>
            <div style="margin-top:10px;font-size:0.9em;color:#666;">
                <em>Generated using Blablador API ({self.model})</em>
            </div>
        </div>
        """
        display(HTML(html_output))


# ── Panel class ──────────────────────────────────────────────────────────────


class AISummaryPanel:
    """
    AI summary panel with multi-turn conversation support.

    Encapsulates all widgets and callbacks for the AI summary feature.
    Exposes a ``.widget`` property returning the top-level VBox.

    Usage::

        panel = AISummaryPanel(analyzer_instance, api_key)
        display(panel.widget)

    The legacy ``create_summary_button`` factory function is preserved below
    for backward compatibility.
    """

    def __init__(self, analyzer_instance, api_key: str):
        self._analyzer = analyzer_instance
        self._summarizer = ExperimentSummarizer(api_key)
        self._conversation_history = []
        self._dataset_cache = {"str": None, "metadata": None}
        self._build()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def widget(self) -> widgets.VBox:
        """Return the top-level VBox ready to display."""
        return self._root

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        """Create all widgets, helpers, and callbacks in one pass."""
        summarizer = self._summarizer
        conversation_history = self._conversation_history
        dataset_cache = self._dataset_cache
        analyzer_instance = self._analyzer

        # ── Widgets ────────────────────────────────────────────────────

        self.prompt_editor = widgets.Textarea(
            value=_DEFAULT_SUMMARY_REQUEST,
            placeholder="Enter your question or follow-up here...",
            description="Your Message:",
            disabled=False,
            layout=widgets.Layout(width="95%", height="220px"),
            style={"description_width": "100px"},
        )
        prompt_editor = self.prompt_editor  # local alias for callbacks

        self.include_data_checkbox = widgets.Checkbox(
            value=True,
            description="Include complete dataset (first message only)",
            style={"description_width": "initial"},
            layout=widgets.Layout(margin="4px 0px"),
        )
        include_data_checkbox = self.include_data_checkbox

        self.preview_button = widgets.Button(
            description="🔍 Preview Dataset",
            button_style="primary",
            tooltip="Print the compact CSV dataset to the log area",
            layout=widgets.Layout(width="190px", height="35px"),
        )

        self.generate_button = widgets.Button(
            description="🤖 Generate Summary",
            button_style="info",
            tooltip="Send first message with dataset + prompt (resets history)",
            layout=widgets.Layout(width="190px", height="35px"),
        )

        self.followup_button = widgets.Button(
            description="💬 Ask Follow-up",
            button_style="warning",
            tooltip="Ask a follow-up — dataset not resent, conversation history used",
            layout=widgets.Layout(width="190px", height="35px"),
            disabled=True,
        )
        followup_button = self.followup_button

        self.clear_history_button = widgets.Button(
            description="🗑 Clear History",
            button_style="danger",
            tooltip="Reset conversation — next Generate will resend the dataset",
            layout=widgets.Layout(width="160px", height="35px"),
            disabled=True,
        )
        clear_history_button = self.clear_history_button

        self.history_label = widgets.HTML(
            value='<span style="color:#666;font-size:0.9em;">No conversation yet</span>'
        )
        history_label = self.history_label

        self.summary_output = widgets.Output()
        summary_output = self.summary_output

        # ── Helpers ────────────────────────────────────────────────────

        def _get_dataset():
            if dataset_cache["str"] is None:
                dataset_cache["str"], dataset_cache["metadata"] = summarizer.build_dataset_csv(
                    analyzer_instance.data_manager, analyzer_instance
                )
            return dataset_cache["str"], dataset_cache["metadata"]

        def _update_history_label():
            n = len([m for m in conversation_history if m["role"] == "user"])
            if n == 0:
                history_label.value = (
                    '<span style="color:#666;font-size:0.9em;">No conversation yet</span>'
                )
            else:
                history_label.value = (
                    f'<span style="color:#388E3C;font-size:0.9em;">'
                    f"✓ {n} turn(s) in history — "
                    f"follow-up questions will not resend the dataset</span>"
                )

        def _call_with_fallback(messages):
            response_text = summarizer.call_llm_api(messages)
            if response_text.startswith("Error"):
                logger.warning("Primary model failed, trying faster model...")
                orig = summarizer.model
                summarizer.model = summarizer.fallback_model
                response_text = summarizer.call_llm_api(messages)
                summarizer.model = orig
            return response_text

        # ── Callbacks ──────────────────────────────────────────────────

        def on_preview(b):
            with summary_output:
                clear_output()
                if not analyzer_instance.current_sample_ids:
                    print("❌ No samples loaded. Please load batches first.")
                    return
                print("🔄 Building dataset...")
                try:
                    dataset_str, metadata = _get_dataset()
                    print(
                        f"✅ Dataset ready: {metadata['total_samples']} samples, "
                        f"{metadata['char_count']:,} chars\n"
                    )
                    print(dataset_str)
                except Exception as e:
                    logger.exception("Error building dataset preview")
                    print(f"❌ Error: {e}")

        def on_generate(b):
            """First message — resets history and optionally includes dataset."""
            # Reset history and cache on fresh generate
            conversation_history.clear()
            dataset_cache["str"] = None
            dataset_cache["metadata"] = None

            with summary_output:
                clear_output()
                if not analyzer_instance.current_sample_ids:
                    print("❌ No samples loaded. Please load batches first.")
                    return
                if not prompt_editor.value.strip():
                    print("❌ Prompt is empty.")
                    return

                print(
                    f"📊 Preparing data for {len(analyzer_instance.current_sample_ids)} samples..."
                )

                try:
                    dataset_str, metadata = _get_dataset()

                    first_message = _HIDDEN_PREAMBLE.strip() + "\n\n"
                    if include_data_checkbox.value:
                        print(f"📎 Attaching dataset ({metadata['char_count']:,} chars)...")
                        first_message += "DATASET:\n" + dataset_str + "\n\n"

                    first_message += prompt_editor.value.strip()
                    conversation_history.append({"role": "user", "content": first_message})

                    print("🤖 Sending to LLM (this may take 10-30 seconds)...")
                    response_text = _call_with_fallback(conversation_history)
                    conversation_history.append({"role": "assistant", "content": response_text})

                    followup_button.disabled = False
                    clear_history_button.disabled = False
                    _update_history_label()

                    # Clear prompt for next question
                    prompt_editor.value = ""

                    clear_output()
                    summarizer.display_summary(response_text, metadata)

                except Exception as e:
                    logger.exception("Error generating summary")
                    print(f"❌ Error: {e}")

        def on_followup(b):
            """Follow-up message — appends to history, no dataset resent."""
            with summary_output:
                clear_output()
                if not conversation_history:
                    print("❌ No conversation history. Click Generate Summary first.")
                    return
                if not prompt_editor.value.strip():
                    print("❌ Prompt is empty.")
                    return

                turn = len([m for m in conversation_history if m["role"] == "user"]) + 1
                print(f"💬 Sending follow-up (turn {turn}) — dataset not resent...")

                try:
                    conversation_history.append(
                        {"role": "user", "content": prompt_editor.value.strip()}
                    )
                    response_text = _call_with_fallback(conversation_history)
                    conversation_history.append({"role": "assistant", "content": response_text})

                    _update_history_label()

                    # Clear prompt for next question
                    prompt_editor.value = ""

                    clear_output()
                    summarizer.display_followup(response_text, turn)

                except Exception as e:
                    logger.exception("Error in follow-up")
                    print(f"❌ Error: {e}")

        def on_clear_history(b):
            conversation_history.clear()
            dataset_cache["str"] = None
            dataset_cache["metadata"] = None
            followup_button.disabled = True
            clear_history_button.disabled = True
            _update_history_label()
            with summary_output:
                clear_output()
                print("🗑 Conversation cleared. Next Generate Summary will resend the dataset.")

        self.preview_button.on_click(on_preview)
        self.generate_button.on_click(on_generate)
        self.followup_button.on_click(on_followup)
        self.clear_history_button.on_click(on_clear_history)

        # Invalidate dataset cache when batch selection changes
        try:

            def on_batch_change(change):
                dataset_cache["str"] = None
                dataset_cache["metadata"] = None

            analyzer_instance.gui.batch_selector.observe(on_batch_change, names="value")
        except Exception:
            pass  # not critical if gui not yet available

        # ── Layout ─────────────────────────────────────────────────────

        instructions = widgets.HTML(
            value="""
            <div style="background-color:#e3f2fd;padding:10px;border-radius:5px;margin-bottom:10px;">
                <strong>📝 How to use:</strong><br/>
                1. Load batches in the main interface above<br/>
                2. (Optional) Click <em>Preview Dataset</em> to inspect the compact data format<br/>
                3. The prompt editor is pre-filled with a default summary request — edit as needed<br/>
                4. Click <em>Generate Summary</em> to send the first message (clears prompt after sending)<br/>
                5. Type follow-up questions and click <em>Ask Follow-up</em> — dataset is not resent<br/>
                6. Click <em>Clear History</em> to start fresh (next Generate will resend the dataset)
            </div>
        """
        )

        button_row = widgets.HBox(
            [
                self.preview_button,
                self.generate_button,
                self.followup_button,
                self.clear_history_button,
            ],
            layout=widgets.Layout(margin="8px 0px", gap="8px", flex_wrap="wrap"),
        )

        self._root = widgets.VBox(
            [
                instructions,
                self.prompt_editor,
                self.include_data_checkbox,
                button_row,
                self.history_label,
                self.summary_output,
            ]
        )


# ── Backward-compat factory function ─────────────────────────────────────────


def create_summary_button(analyzer_instance, api_key: str) -> widgets.VBox:
    """
    Backward-compatible wrapper around :class:`AISummaryPanel`.

    .. deprecated::
        Instantiate ``AISummaryPanel`` directly and use its ``.widget`` property.
    """
    return AISummaryPanel(analyzer_instance, api_key).widget
