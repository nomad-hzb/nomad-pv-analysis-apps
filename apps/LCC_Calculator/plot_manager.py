"""
plot_manager.py
----------------
Plotly figure construction for the LCC Calculator. No widget imports.

Actual $ costs only exist after colleagues fill in the exported Excel
workbook (nothing is priced yet at extraction time - see data_manager.py),
so there is nothing to chart in $ terms during a live session. Instead this
shows a per-batch line-item count breakdown (Processes / Materials found)
- a quick sanity check on what was actually extracted from NOMAD for each
selected batch before exporting. Labor is a manual per-role entry sheet,
not extracted per batch, so it has no count to chart here.
"""

from __future__ import annotations

import plotly.graph_objects as go
from data_manager import LCCDataManager


def build_line_item_count_figure(dm: LCCDataManager) -> go.Figure:
    batch_ids = sorted(dm.batch_sample_counts)

    def count_per_batch(rows) -> list[int]:
        counts = {batch_id: 0 for batch_id in batch_ids}
        for row in rows:
            if row.batch_id in counts:
                counts[row.batch_id] += 1
        return [counts[batch_id] for batch_id in batch_ids]

    fig = go.Figure()
    fig.add_bar(name="Processes", x=batch_ids, y=count_per_batch(dm.process_rows))
    fig.add_bar(name="Materials", x=batch_ids, y=count_per_batch(dm.material_rows))

    fig.update_layout(
        barmode="group",
        template="plotly_white",
        title="Extracted line items per batch (fill in costs in the exported Excel)",
        xaxis_title="Batch",
        yaxis_title="Line item count",
        height=450,
    )
    return fig
