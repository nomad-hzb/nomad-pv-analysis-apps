"""
Resizable Plot Utility for JV Analysis Application
Adds resizable containers to Plotly figures in Jupyter notebooks
"""

__author__ = "Edgar Nandayapa"
__institution__ = "Helmholtz-Zentrum Berlin"
__created__ = "August 2025"

import logging
import uuid

import ipywidgets as widgets
import plotly.graph_objects as go
from IPython.display import HTML, display

logger = logging.getLogger(__name__)


class ResizablePlotManager:
    """Enhanced plot manager that creates resizable plots"""

    @staticmethod
    def display_plots_resizable(figs, names, container_widget=None):
        """
        Display multiple plots as resizable widgets.

        Args:
            figs: List of Plotly figures
            names: List of plot names/titles
            container_widget: Optional widget container for output
        """
        if container_widget:
            with container_widget:
                ResizablePlotManager._display_plots_internal(figs, names)
        else:
            ResizablePlotManager._display_plots_internal(figs, names)

    @staticmethod
    def _display_plots_internal(figs, names):
        """Internal method to display plots"""
        from IPython.display import clear_output

        clear_output(wait=True)

        for i, (fig, name) in enumerate(zip(figs, names)):
            try:
                display(widgets.HTML(f'<h4 style="margin:12px 0 2px 0;padding:0;">{name}</h4>'))
                # Reduce the bottom margin so there is no large blank gap below each plot
                try:
                    b = fig.layout.margin.b
                    if b is None or b > 25:
                        fig.update_layout(margin=dict(b=25))
                except Exception:
                    pass
                # Wrap as a FigureWidget: Voila renders ipywidgets natively via the comm
                # protocol, whereas a plain go.Figure relies on the notebook's plotly
                # mimetype renderer, which isn't guaranteed to be registered server-side
                # (this is why plots showed in VS Code but not on the deployed server).
                #
                # Plotly's bundled JS (part of the widget, not a CDN fetch) only re-fits
                # itself to its container on a *window* resize event, and only sizes an
                # axis to 100% of its container when that axis has no explicit
                # layout.width/height -- so both need clearing here, and dragging the CSS
                # resize handle needs a ResizeObserver that dispatches a synthetic window
                # resize to make Plotly notice.
                fig.update_layout(autosize=True, width=None, height=None)
                fig_widget = go.FigureWidget(fig)
                fig_widget._config = {"responsive": True, "displaylogo": False}
                # FigureWidget.layout is Plotly's own chart layout (titles/axes), not the
                # ipywidgets DOM layout, so the resize handle has to go on a wrapping Box
                # instead of on the widget itself.
                resize_class = f"jv-resizable-plot-{uuid.uuid4().hex[:8]}"
                box = widgets.Box(
                    [fig_widget],
                    layout=widgets.Layout(
                        width="900px",
                        height="620px",
                        min_width="420px",
                        min_height="320px",
                        max_width="1600px",
                        max_height="1200px",
                        border="1px solid #ccc",
                        overflow="hidden",
                    ),
                )
                box.add_class(resize_class)
                display(box)
                # IPython.display.HTML (not ipywidgets.HTML) is required here: ipywidgets.HTML
                # renders by setting innerHTML on its DOM node, which never executes embedded
                # <script> tags. IPython's own display area re-inserts <script> tags so they
                # actually run -- this is why the original implementation used it too.
                display(
                    HTML(f"""
                    <style>
                    .{resize_class} {{ resize: both !important; }}
                    .{resize_class}:hover {{ border-color: #007bff !important; }}
                    .{resize_class} > div {{ width: 100% !important; height: 100% !important; }}
                    </style>
                    <script>
                    (function retry(attempts) {{
                        var el = document.querySelector(".{resize_class}");
                        if (!el) {{
                            if (attempts > 0) setTimeout(function() {{ retry(attempts - 1); }}, 100);
                            return;
                        }}
                        var pending = null;
                        new ResizeObserver(function() {{
                            clearTimeout(pending);
                            pending = setTimeout(function() {{
                                window.dispatchEvent(new Event("resize"));
                            }}, 80);
                        }}).observe(el);
                    }})(30);
                    </script>
                    """)
                )
            except Exception as e:
                logger.error("Error displaying plot %d (%s): %s", i + 1, name, e)
